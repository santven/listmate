import datetime
import os
import re
import json
import logging
import requests
from typing import List, Dict, Any, Optional

import shared.auth as authmod
from shared.auth import _run, _one, _init_schema

logger = logging.getLogger(__name__)

# Cache for initialized Firebase App and Credential
_firebase_initialized = False
_firebase_credential = None
_APNS_HEX_REGEX = re.compile(r'^[0-9a-fA-F]{64}$')


def _get_firebase_app():
    """Lazily initialize the Firebase Admin SDK if service credentials are present.
    Supports either:
    1. FIREBASE_SERVICE_ACCOUNT_JSON (raw JSON string or filepath)
    2. GOOGLE_APPLICATION_CREDENTIALS (filepath)
    """
    global _firebase_initialized, _firebase_credential
    if _firebase_initialized:
        return True

    try:
        import firebase_admin
        from firebase_admin import credentials

        # Check if already initialized in another module
        if firebase_admin._apps:
            _firebase_initialized = True
            try:
                _firebase_credential = firebase_admin.get_app().credential
            except Exception:
                pass
            return True

        cred_json = os.environ.get("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
        google_app_cred = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()

        if cred_json:
            if cred_json.startswith("{"):
                cred_dict = json.loads(cred_json)
                cred = credentials.Certificate(cred_dict)
            else:
                cred = credentials.Certificate(cred_json)
            firebase_admin.initialize_app(cred)
            _firebase_credential = cred
            _firebase_initialized = True
            logger.info("[PushHelper] Firebase Admin initialized with FIREBASE_SERVICE_ACCOUNT_JSON.")
            return True
        elif google_app_cred and os.path.exists(google_app_cred):
            cred = credentials.Certificate(google_app_cred)
            firebase_admin.initialize_app(cred)
            _firebase_credential = cred
            _firebase_initialized = True
            logger.info("[PushHelper] Firebase Admin initialized with GOOGLE_APPLICATION_CREDENTIALS.")
            return True
        else:
            logger.warning("[PushHelper] No Firebase Admin credentials found in environment. Push dispatch will run in mock/log mode.")
            return False
    except Exception as e:
        logger.error(f"[PushHelper] Failed to initialize Firebase Admin: {e}")
        return False


def _get_google_access_token() -> Optional[str]:
    """Retrieve an OAuth2 Bearer token using the Firebase Admin credentials."""
    global _firebase_credential
    _get_firebase_app()
    if not _firebase_credential:
        return None
    try:
        # Certificate object implements get_access_token()
        token_obj = _firebase_credential.get_access_token()
        if not token_obj:
            return None
        if hasattr(token_obj, 'access_token') and token_obj.access_token:
            return str(token_obj.access_token)
        val = str(token_obj).strip()
        return val if val and val.lower() != 'none' else None
    except Exception as e:
        logger.error(f"[PushHelper] Error obtaining Google access token: {e}")
        return None


def exchange_apns_to_fcm(apns_token: str, bundle_id: str = "com.pvkslabs.listmate") -> Optional[str]:
    """Exchange a native 64-char Apple APNs hex token for a Firebase FCM registration token
    using the Google Instance ID batchImport API.
    Tries Production first (TestFlight / AppStore), then Sandbox (local dev).
    """
    clean_apns = str(apns_token or "").strip()
    if not _APNS_HEX_REGEX.match(clean_apns):
        return clean_apns

    access_token = _get_google_access_token()
    if not access_token:
        logger.warning(f"[PushHelper] Cannot exchange APNs token: Google access token unavailable.")
        return None

    url = "https://iid.googleapis.com/iid/v1:batchImport"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
        "access_token_auth": "true",
    }

    # TestFlight and AppStore builds use production APNs environment (sandbox=False)
    # Xcode local debug builds use development APNs environment (sandbox=True)
    for is_sandbox in [False, True]:
        body = {
            "application": bundle_id,
            "sandbox": is_sandbox,
            "apns_tokens": [clean_apns],
        }
        try:
            resp = requests.post(url, json=body, headers=headers, timeout=4)
            if resp.status_code == 200:
                data = resp.json()
                results = data.get("results", [])
                if results and results[0].get("status") == "OK" and results[0].get("registration_token"):
                    fcm_token = results[0]["registration_token"]
                    env_name = "sandbox" if is_sandbox else "production"
                    print(f"[PushHelper] Successfully exchanged APNs token ({clean_apns[:10]}...) to FCM token ({fcm_token[:14]}...) via {env_name}.", flush=True)
                    return fcm_token
                else:
                    err_status = results[0].get("status") if results else "EMPTY_RESULTS"
                    print(f"[PushHelper] APNs exchange attempt (sandbox={is_sandbox}) returned: {err_status}", flush=True)
            else:
                print(f"[PushHelper] APNs exchange HTTP {resp.status_code} (sandbox={is_sandbox}): {resp.text}", flush=True)
        except Exception as e:
            print(f"[PushHelper] Exception exchanging APNs token: {e}", flush=True)

    return None


def resolve_fcm_tokens(tokens: List[str]) -> List[str]:
    """Inspect a list of tokens. If any are raw 64-hex APNs tokens, exchange them for FCM tokens
    and update them in the database for future dispatches.
    Preserves 1-to-1 array length matching input.
    """
    resolved = []
    for token in tokens:
        clean_tok = str(token or "").strip()
        if not clean_tok:
            resolved.append("")
            continue
        if _APNS_HEX_REGEX.match(clean_tok):
            fcm_token = exchange_apns_to_fcm(clean_tok)
            if fcm_token:
                # Update database so subsequent pushes use the FCM token directly
                try:
                    authmod.replace_push_token(clean_tok, fcm_token)
                except Exception as update_err:
                    logger.warning(f"[PushHelper] Failed to update replaced token in DB: {update_err}")
                resolved.append(fcm_token)
            else:
                # Keep original token so it can still report failure if exchange failed
                resolved.append(clean_tok)
        else:
            resolved.append(clean_tok)
    return resolved


def _send_fcm_multicast(tokens: List[str], title: str, body: str, data: Optional[Dict[str, str]] = None,
                        target_type: str = "broadcast", target_id: Optional[int] = None) -> Dict[str, Any]:
    """Send multicast notification via Firebase Cloud Messaging with dead token collection and audit logging.
    Enforces FCM 500-token batching, strict 1-to-1 token alignment, and robust dead token pruning.
    """
    # 1. Defensively clean input tokens
    clean_tokens = [str(t).strip() for t in (tokens or []) if t and str(t).strip()]
    if not clean_tokens:
        return {"sent": 0, "failed": 0, "unregistered": [], "errors": []}

    # Format custom data as strings
    clean_data = {}
    if data:
        for k, v in data.items():
            clean_data[str(k)] = str(v)

    app_ready = _get_firebase_app()
    if not app_ready:
        # Mock/development fallback: log delivery payload safely
        print(f"[PushHelper:MockDispatch] Would push to {len(clean_tokens)} token(s) | Title: '{title}' | Body: '{body}' | Data: {clean_data}")
        authmod.log_push_dispatch(
            target_type=target_type,
            target_id=target_id,
            title=title,
            body=body,
            url=clean_data.get('url', '/'),
            custom_data=clean_data,
            tokens_count=len(clean_tokens),
            sent_count=len(clean_tokens),
            failed_count=0,
            errors=[],
            is_mock=True
        )
        return {"sent": len(clean_tokens), "failed": 0, "unregistered": [], "mock": True}

    try:
        from firebase_admin import messaging

        notification = messaging.Notification(
            title=title,
            body=body,
        )

        # Build Android config (omit click_action so default launcher activity receives notification payload)
        android_config = None
        try:
            if hasattr(messaging, 'AndroidConfig') and hasattr(messaging, 'AndroidNotification'):
                android_config = messaging.AndroidConfig(
                    priority='high',
                    notification=messaging.AndroidNotification(
                        sound='default',
                        channel_id='listmate_notifications',
                    )
                )
        except Exception as ac_err:
            logger.warning(f"[PushHelper] Failed to build AndroidConfig: {ac_err}")

        # Build APNs config (Python SDK uses APNSConfig, APNSPayload, Aps)
        apns_config = None
        try:
            apns_cls = getattr(messaging, 'APNSConfig', getattr(messaging, 'ApnsConfig', None))
            apns_payload_cls = getattr(messaging, 'APNSPayload', getattr(messaging, 'ApnsPayload', None))
            aps_cls = getattr(messaging, 'Aps', None)

            if apns_cls and apns_payload_cls and aps_cls:
                apns_config = apns_cls(
                    headers={'apns-priority': '10'},
                    payload=apns_payload_cls(
                        aps=aps_cls(
                            sound='default',
                            badge=1,
                        ),
                        custom_data=clean_data,
                    )
                )
        except Exception as apns_err:
            logger.warning(f"[PushHelper] Failed to build APNSConfig: {apns_err}")

        # FCM enforces max 500 tokens per multicast message
        FCM_BATCH_SIZE = 500
        total_sent = 0
        total_failed = 0
        all_dead_tokens = []
        all_errors = []

        for i in range(0, len(clean_tokens), FCM_BATCH_SIZE):
            batch_orig_tokens = clean_tokens[i:i + FCM_BATCH_SIZE]
            # Resolve APNs tokens to FCM tokens 1-to-1
            batch_effective_tokens = resolve_fcm_tokens(batch_orig_tokens)

            # Pair original and effective tokens to maintain perfect alignment
            paired_tokens = list(zip(batch_orig_tokens, batch_effective_tokens))
            valid_pairs = [p for p in paired_tokens if p[1]]
            if not valid_pairs:
                continue

            multicast_kwargs = {
                "tokens": [p[1] for p in valid_pairs],
                "notification": notification,
                "data": clean_data,
            }
            if android_config:
                multicast_kwargs["android"] = android_config
            if apns_config:
                multicast_kwargs["apns"] = apns_config

            message = messaging.MulticastMessage(**multicast_kwargs)
            response = messaging.send_each_for_multicast(message)

            total_sent += response.success_count
            total_failed += response.failure_count

            batch_dead = []
            for idx, resp in enumerate(response.responses):
                orig_tok, eff_tok = valid_pairs[idx]
                if not resp.success:
                    err = resp.exception
                    err_str = str(err)
                    err_code = getattr(err, 'code', 'UNKNOWN')
                    print(f"[PushHelper:Failure] Token {eff_tok[:12]}... ErrorCode={err_code} Exception={err_str}", flush=True)
                    all_errors.append(f"{err_code}: {err_str}")

                    # Check for dead/unregistered tokens
                    is_unregistered = (
                        (err and hasattr(err, 'code') and err.code in ('UNREGISTERED', 'INVALID_ARGUMENT'))
                        or 'registration-token-not-registered' in err_str.lower()
                        or 'unregistered' in err_str.lower()
                    )
                    if is_unregistered:
                        # Append both so whichever is currently in the DB row gets deactivated
                        batch_dead.append(orig_tok)
                        batch_dead.append(eff_tok)
                        all_dead_tokens.append(eff_tok)
                else:
                    msg_id = getattr(resp, 'message_id', 'ok')
                    print(f"[PushHelper:Success] Token {eff_tok[:12]}... MessageId={msg_id}", flush=True)

            if batch_dead:
                unique_dead = list(set([t for t in batch_dead if t]))
                print(f"[PushHelper] Pruning {len(unique_dead)} inactive/unregistered token(s).", flush=True)
                authmod.mark_tokens_inactive(unique_dead)

        # Log push dispatch result to database
        try:
            authmod.log_push_dispatch(
                target_type=target_type,
                target_id=target_id,
                title=title,
                body=body,
                url=clean_data.get('url', '/'),
                custom_data=clean_data,
                tokens_count=len(clean_tokens),
                sent_count=total_sent,
                failed_count=total_failed,
                errors=all_errors,
                is_mock=False
            )
        except Exception as log_err:
            logger.warning(f"[PushHelper] Failed to log push dispatch: {log_err}")

        return {
            "sent": total_sent,
            "failed": total_failed,
            "unregistered": list(set(all_dead_tokens)),
            "errors": all_errors,
            "mock": False,
        }
    except Exception as e:
        print(f"[PushHelper:Exception] Multicast dispatch error: {e}", flush=True)
        logger.error(f"[PushHelper] Multicast dispatch error: {e}")
        try:
            authmod.log_push_dispatch(
                target_type=target_type,
                target_id=target_id,
                title=title,
                body=body,
                url=clean_data.get('url', '/'),
                custom_data=clean_data,
                tokens_count=len(clean_tokens),
                sent_count=0,
                failed_count=len(clean_tokens),
                errors=[str(e)],
                is_mock=False
            )
        except Exception:
            pass
        return {"sent": 0, "failed": len(clean_tokens), "error": str(e), "errors": [str(e)], "unregistered": []}


def send_push_to_user(user_id: int, title: str, body: str, data: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Send push notification to all active devices registered by a specific user.
    Handles '0 vs None' integer bounds safely.
    """
    if not user_id or user_id == 0:
        return {"sent": 0, "failed": 0, "error": "Invalid user_id"}

    token_rows = authmod.get_active_tokens_for_user(user_id)
    if not token_rows:
        try:
            authmod.log_push_dispatch(
                target_type="user",
                target_id=int(user_id),
                title=title,
                body=body,
                url=(data or {}).get("url", "/"),
                custom_data=data,
                tokens_count=0,
                sent_count=0,
                failed_count=0,
                errors=["No active push tokens for user"],
                is_mock=False
            )
        except Exception:
            pass
        return {"sent": 0, "failed": 0, "message": "No active tokens for user"}

    tokens = [r["token"] for r in token_rows if r.get("token")]
    return _send_fcm_multicast(tokens, title, body, data, target_type="user", target_id=int(user_id))


def send_push_to_household(household_id: int, title: str, body: str, data: Optional[Dict[str, str]] = None, exclude_user_id: Optional[int] = None) -> Dict[str, Any]:
    """Send push notification to all active members of a household (e.g. partner sync or list updates).
    Can exclude the actor's user_id so they don't get alerted for their own edits.
    """
    if not household_id or household_id == 0:
        return {"sent": 0, "failed": 0, "error": "Invalid household_id"}

    ex_uid = None if (exclude_user_id is None or exclude_user_id == 0) else int(exclude_user_id)
    token_rows = authmod.get_active_tokens_for_household(household_id, exclude_user_id=ex_uid)
    if not token_rows:
        try:
            authmod.log_push_dispatch(
                target_type="household",
                target_id=int(household_id),
                title=title,
                body=body,
                url=(data or {}).get("url", "/"),
                custom_data=data,
                tokens_count=0,
                sent_count=0,
                failed_count=0,
                errors=["No active push tokens for household"],
                is_mock=False
            )
        except Exception as log_err:
            logger.warning(f"[PushHelper] Failed to log empty household token dispatch: {log_err}")
        return {"sent": 0, "failed": 0, "message": "No active tokens for household"}

    tokens = [r["token"] for r in token_rows if r.get("token")]
    return _send_fcm_multicast(tokens, title, body, data, target_type="household", target_id=int(household_id))


def send_push_broadcast(title: str, body: str, data: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Send push notification to all registered active devices across the application."""
    try:
        authmod._init_schema()
        rows = authmod._run("SELECT token FROM push_subscriptions WHERE is_active = TRUE")
        tokens = [r["token"] for r in rows if r.get("token")]
        if not tokens:
            return {"sent": 0, "failed": 0, "message": "No active tokens"}
        return _send_fcm_multicast(tokens, title, body, data, target_type="broadcast", target_id=None)
    except Exception as e:
        logger.error(f"[PushHelper] Broadcast error: {e}")
        return {"sent": 0, "failed": 0, "error": str(e)}


def notify_while_shopping_addition(store_id: int, household_id: int, adding_user_id: int,
                                   adder_name: str, item_names: List[str],
                                   store_name: Optional[str] = None) -> Dict[str, Any]:
    """Alert active shoppers when a household member adds items to their current trip.
    Supports two states:
      1. Phase 2: Checkout Line Grace Window (completed trip within last 5 minutes) -> BYPASSES 2-min cooldown with urgency copy.
      2. Phase 1: In the Aisles (active trip in progress) -> ENFORCES 2-minute cooldown window per shopper/store.
      3. Strict self-exclusion (adding user is never notified).
      4. Safe integer bounds (Falsiness rule: 0 vs None).
    """
    sid = None if (store_id is None or int(store_id) == 0) else int(store_id)
    hhid = None if (household_id is None or int(household_id) == 0) else int(household_id)
    adder_id = None if (adding_user_id is None or int(adding_user_id) == 0) else int(adding_user_id)

    if not sid or not hhid:
        return {"ok": False, "reason": "invalid_parameters", "notified": 0}

    clean_item_names = [str(n).strip() for n in (item_names or []) if str(n).strip()]
    if not clean_item_names:
        return {"ok": False, "reason": "no_items", "notified": 0}

    clean_adder = (str(adder_name or "").strip() or "A family member")

    try:
        authmod._init_schema()

        # Resolve store name if not provided
        resolved_store_name = str(store_name or "").strip()
        if not resolved_store_name:
            store_row = authmod._one("SELECT name FROM stores WHERE id = %s AND household_id = %s", (sid, hhid))
            if store_row:
                resolved_store_name = store_row.get("name") or "the store"
            else:
                resolved_store_name = "the store"

        # Item summary text
        if len(clean_item_names) == 1:
            item_desc = f"'{clean_item_names[0]}'"
        elif len(clean_item_names) == 2:
            item_desc = f"'{clean_item_names[0]}' and '{clean_item_names[1]}'"
        else:
            item_desc = f"{len(clean_item_names)} items: '{clean_item_names[0]}', '{clean_item_names[1]}', and {len(clean_item_names) - 2} more"

        notified_count = 0
        suppressed_count = 0
        handled_shoppers = set()

        # ---------------------------------------------------------------------
        # 1. PHASE 2: Checkout Line Grace Window (Trip completed < 5 mins ago)
        # ---------------------------------------------------------------------
        # In this window, the shopper just tapped "Finish Trip" and is likely standing in the checkout line.
        # Cooldown is BYPASSED (high-urgency alert), with a 1-min rapid flood debounce.
        checkout_shoppers = authmod._run("""
            SELECT DISTINCT purchased_by_user_id
            FROM list_items
            WHERE store_id = %s AND household_id = %s
              AND trip_notified_at IS NOT NULL
              AND trip_notified_at >= NOW() - INTERVAL '5 minutes'
              AND purchased_by_user_id IS NOT NULL
              AND (purchased_by_user_id != %s OR %s IS NULL)
        """, (sid, hhid, adder_id, adder_id))

        for row in checkout_shoppers:
            uid = row.get("purchased_by_user_id")
            if not uid or int(uid) == 0 or int(uid) in handled_shoppers:
                continue
            uid = int(uid)
            handled_shoppers.add(uid)

            # 1-minute flood protection specifically for checkout additions (prevent rapid multiple clicks buzzing repeatedly)
            recent_checkout_push = authmod._one("""
                SELECT id FROM push_notifications_log
                WHERE target_type = 'user' AND target_id = %s
                  AND custom_data->>'type' = 'checkout_line_addition'
                  AND custom_data->>'store_id' = %s
                  AND created_at >= NOW() - INTERVAL '1 minute'
            """, (uid, str(sid)))

            if recent_checkout_push:
                suppressed_count += 1
                continue

            # Urgent checkout line push
            c_title = "🛒 Catch it before checkout!"
            c_body = f"{clean_adder} just added {item_desc} to {resolved_store_name}. Grab it before you leave!"
            push_data = {
                "type": "checkout_line_addition",
                "action": "open_store",
                "store_id": str(sid),
                "store_name": resolved_store_name,
                "url": f"/?store_id={sid}"
            }
            send_push_to_user(user_id=uid, title=c_title, body=c_body, data=push_data)
            notified_count += 1

        # ---------------------------------------------------------------------
        # 2. PHASE 1: In the Aisles (Active Trip In-Progress)
        # ---------------------------------------------------------------------
        # Shopper checked off items today that have not yet been marked completed (trip_notified_at IS NULL).
        # Enforces a 2-minute cooldown window to avoid spamming the shopper.
        active_shoppers = authmod._run("""
            SELECT DISTINCT purchased_by_user_id
            FROM list_items
            WHERE store_id = %s AND household_id = %s
              AND purchased = TRUE
              AND trip_notified_at IS NULL
              AND (purchased_at >= NOW() - INTERVAL '45 minutes' OR (purchased_at IS NULL AND added_at >= CURRENT_DATE))
              AND purchased_by_user_id IS NOT NULL
              AND (purchased_by_user_id != %s OR %s IS NULL)
        """, (sid, hhid, adder_id, adder_id))

        for row in active_shoppers:
            uid = row.get("purchased_by_user_id")
            if not uid or int(uid) == 0 or int(uid) in handled_shoppers:
                continue
            uid = int(uid)
            handled_shoppers.add(uid)

            # 2-Minute Cooldown Window check
            recent_active_push = authmod._one("""
                SELECT id FROM push_notifications_log
                WHERE target_type = 'user' AND target_id = %s
                  AND (custom_data->>'type' = 'active_trip_addition' OR custom_data->>'type' = 'checkout_line_addition')
                  AND custom_data->>'store_id' = %s
                  AND created_at >= NOW() - INTERVAL '2 minutes'
            """, (uid, str(sid)))

            if recent_active_push:
                print(f"[WhileShoppingPush] Cooldown active (2 min) for User #{uid} at Store #{sid}. Suppressed.", flush=True)
                suppressed_count += 1
                continue

            # Standard in-aisle addition push
            a_title = f"🛒 {clean_adder} added to your {resolved_store_name} trip"
            a_body = f"Added {item_desc} to the list."
            push_data = {
                "type": "active_trip_addition",
                "action": "open_store",
                "store_id": str(sid),
                "store_name": resolved_store_name,
                "url": f"/?store_id={sid}"
            }
            send_push_to_user(user_id=uid, title=a_title, body=a_body, data=push_data)
            notified_count += 1

        return {
            "ok": True,
            "notified": notified_count,
            "suppressed": suppressed_count,
            "store_name": resolved_store_name
        }
    except Exception as e:
        print(f"[notify_while_shopping_addition error]: {e}", flush=True)
        return {"ok": False, "error": str(e), "notified": 0}

# ─────────────────────────────────────────────────────────────────────────────
# 3. SCHEDULED PUSH REMINDERS (Timezone-Aware Hourly Sweeps — Issue #628)
# ─────────────────────────────────────────────────────────────────────────────

def check_trial_expiration_pushes(target_hour=8, dry_run=False, force_send=False):
    """
    Evaluates trial households approaching expiration and dispatches push reminders
    at 72 hours (Day T-3) and 24 hours (Day T-1) before expiration.
    
    Acceptance Criteria (Issue #554):
    1. Evaluates users at 8:00 AM in their local timezone (auth_users.timezone, fallback America/Chicago).
    2. Directly verifies is_premium = FALSE and subscription_status = 'trial' in PostgreSQL immediately before dispatch.
    3. Content:
       - 72h: '✨ 3 Days Left in Your ListMate Pro Trial' / 'Keep real-time household sync and smart sorting active.'
       - 24h: '⏳ Your Pro trial ends tomorrow' / 'Upgrade now to keep uninterrupted household sync.'
    4. Idempotency: Scoped via push_notifications_log with campaign IN ('trial_72h', 'trial_24h').
    5. Deep Link: action: 'open_upgrade_modal', url: '/?modal=upgrade&source=push_trial'.
    """
    _init_schema()

    print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] Checking pro trial expiration push reminders (target_hour={target_hour}, dry_run={dry_run}, force_send={force_send})...")

    # Timezone check clause: if force_send is True or target_hour is None, bypass hour matching
    hour_clause = ""
    params = {}
    if not force_send and target_hour is not None:
        hour_clause = "AND EXTRACT(HOUR FROM NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago')) = %(target_hour)s"
        params["target_hour"] = int(target_hour)

    query = f"""
        SELECT 
            h.id AS household_id,
            h.name AS household_name,
            h.trial_ends_at,
            h.is_premium,
            h.subscription_status,
            u.id AS user_id,
            u.name AS user_name,
            u.email AS user_email,
            COALESCE(u.timezone, 'America/Chicago') AS user_timezone,
            EXTRACT(HOUR FROM NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago')) AS current_local_hour,
            CASE 
                WHEN DATE(h.trial_ends_at AT TIME ZONE COALESCE(u.timezone, 'America/Chicago')) = 
                     DATE(NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago')) + INTERVAL '3 days' 
                     OR (h.trial_ends_at BETWEEN NOW() + INTERVAL '48 hours' AND NOW() + INTERVAL '72 hours')
                     THEN 'trial_72h'
                WHEN DATE(h.trial_ends_at AT TIME ZONE COALESCE(u.timezone, 'America/Chicago')) = 
                     DATE(NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago')) + INTERVAL '1 day' 
                     OR (h.trial_ends_at BETWEEN NOW() AND NOW() + INTERVAL '24 hours')
                     THEN 'trial_24h'
            END AS campaign_type
        FROM auth_households h
        JOIN auth_household_members hm ON hm.household_id = h.id
        JOIN auth_users u ON u.id = hm.user_id
        WHERE h.is_premium = FALSE
          AND h.subscription_status = 'trial'
          AND h.trial_ends_at IS NOT NULL
          {hour_clause}
          AND (
              -- 72h window check & idempotency
              (
                  (DATE(h.trial_ends_at AT TIME ZONE COALESCE(u.timezone, 'America/Chicago')) = 
                   DATE(NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago')) + INTERVAL '3 days'
                   OR (h.trial_ends_at BETWEEN NOW() + INTERVAL '48 hours' AND NOW() + INTERVAL '72 hours'))
                  AND NOT EXISTS (
                      SELECT 1 FROM push_notifications_log pnl 
                      WHERE pnl.target_type = 'user' 
                        AND pnl.target_id = u.id 
                        AND pnl.custom_data->>'campaign' = 'trial_72h'
                  )
              )
              OR
              -- 24h window check & idempotency
              (
                  (DATE(h.trial_ends_at AT TIME ZONE COALESCE(u.timezone, 'America/Chicago')) = 
                   DATE(NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago')) + INTERVAL '1 day'
                   OR (h.trial_ends_at BETWEEN NOW() AND NOW() + INTERVAL '24 hours'))
                  AND NOT EXISTS (
                      SELECT 1 FROM push_notifications_log pnl 
                      WHERE pnl.target_type = 'user' 
                        AND pnl.target_id = u.id 
                        AND pnl.custom_data->>'campaign' = 'trial_24h'
                  )
              )
          )
        ORDER BY h.trial_ends_at ASC, u.id ASC
    """

    try:
        candidates = _run(query, params if params else None)
    except Exception as e:
        print(f"[check_trial_expiration_pushes] Query error: {e}", flush=True)
        return {"ok": False, "error": str(e), "dispatched": 0, "candidates": 0}

    print(f"  -> Found {len(candidates)} candidate user(s) for trial push notifications.")
    results = []
    dispatched_count = 0

    for cand in candidates:
        uid = cand.get("user_id")
        hhid = cand.get("household_id")
        campaign = cand.get("campaign_type")

        # Defensive integer check (Falsiness rule: 0 vs None)
        if not uid or int(uid) == 0 or not hhid or int(hhid) == 0:
            continue
        uid = int(uid)
        hhid = int(hhid)

        # 2. Live Subscription Check: Directly verify in PostgreSQL before dispatching
        try:
            live_hh = _run("SELECT is_premium, subscription_status FROM auth_households WHERE id = %s", (hhid,))
            if not live_hh:
                continue
            if live_hh[0].get("is_premium") is True or live_hh[0].get("subscription_status") != "trial":
                print(f"  [Skip] User #{uid} (Household #{hhid}) upgraded or is no longer on trial (is_premium={live_hh[0].get('is_premium')}).")
                continue
        except Exception as live_err:
            print(f"  [Warning] Failed live subscription check for Household #{hhid}: {live_err}")
            continue

        # Notification content per acceptance criteria
        if campaign == "trial_72h":
            title = "✨ 3 Days Left in Your ListMate Pro Trial"
            body = "Keep real-time household sync and smart sorting active."
        elif campaign == "trial_24h":
            title = "⏳ Your Pro trial ends tomorrow"
            body = "Upgrade now to keep uninterrupted household sync."
        else:
            continue

        deep_link_url = "/?modal=upgrade&source=push_trial"
        push_data = {
            "action": "open_upgrade_modal",
            "modal": "upgrade",
            "campaign": campaign,
            "url": deep_link_url,
            "household_id": str(hhid)
        }

        if dry_run:
            print(f"  [DRY RUN] Would dispatch '{campaign}' to User #{uid} ({cand.get('user_email')}): '{title}'")
            results.append({
                "user_id": uid,
                "household_id": hhid,
                "campaign": campaign,
                "title": title,
                "body": body,
                "data": push_data,
                "status": "dry_run"
            })
            continue

        # Live dispatch via push_helper
        try:
            res = send_push_to_user(
                user_id=uid,
                title=title,
                body=body,
                data=push_data
            )
            sent_cnt = res.get("sent", 0)
            mock_mode = res.get("mock", False)
            print(f"  [Dispatch] Sent '{campaign}' push to User #{uid} (sent={sent_cnt}, mock={mock_mode}, res={res})")

            # Defensive idempotency insurance: if user had 0 registered tokens, log a record so we do not re-query
            if sent_cnt == 0 and not res.get("error"):
                authmod.log_push_dispatch(
                    target_type="user",
                    target_id=uid,
                    title=title,
                    body=body,
                    url=deep_link_url,
                    custom_data=push_data,
                    tokens_count=0,
                    sent_count=0,
                    failed_count=0,
                    errors=["no_active_tokens"],
                    is_mock=True
                )

            dispatched_count += 1
            results.append({
                "user_id": uid,
                "household_id": hhid,
                "campaign": campaign,
                "title": title,
                "result": res,
                "status": "sent"
            })
        except Exception as dispatch_err:
            print(f"  [Error] Failed to dispatch push to User #{uid}: {dispatch_err}")
            results.append({
                "user_id": uid,
                "household_id": hhid,
                "campaign": campaign,
                "error": str(dispatch_err),
                "status": "error"
            })

    return {
        "ok": True,
        "dispatched": dispatched_count,
        "candidates": len(candidates),
        "results": results,
        "dry_run": dry_run
    }


def check_still_good_fridge_lunch_pushes(target_hour: int = 7, dry_run: bool = False, force_send: bool = False):
    """
    7:00 AM Local Time Morning Fridge Lunch Planning Push Reminder (Issue #610)

    1. Evaluates candidate users at 7:00 AM local time based on their timezone
       (auth_users.timezone, fallback America/Chicago).
    2. Eligible households: Pro and active Pro Trial (subscription_status IN ('premium', 'active', 'trial')).
       If trial, ensure trial_ends_at is valid and has not expired.
    3. Requires active push subscription (permission_status = 'granted').
    4. Household must have at least 1 active refrigerator item (location = 'fridge', status = 'active').
    5. Dynamic copy based on fridge meal count:
       - 1 item: "🍱 Packing lunch today?" / "You have {dish_name} in the fridge ready to enjoy before it expires."
       - 2–3 items: "🍱 Packing lunch today?" / "You have {most_urgent_dish} and {remaining} other meal(s) waiting in the fridge."
       - 4+ items: "🍱 Packing lunch today?" / "Your fridge has {count} meals waiting to be enjoyed. Check Still Good before heading out!"
    6. Idempotency & Frequency Capping:
       - Scoped via push_notifications_log with campaign = 'still_good_lunch_7am' on the current local calendar date.
       - Max 1 reminder per user per local calendar day.
    7. Deep link: /?screen=stillGood&source=push_lunch_7am
    """
    _init_schema()

    print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] Checking Still Good morning fridge lunch pushes (target_hour={target_hour}, dry_run={dry_run}, force_send={force_send})...")

    hour_clause = ""
    params = {}
    if not force_send and target_hour is not None:
        hour_clause = "AND EXTRACT(HOUR FROM NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago')) = %(target_hour)s"
        params["target_hour"] = int(target_hour)

    candidate_query = f"""
        SELECT 
            u.id AS user_id,
            u.name AS user_name,
            u.email AS user_email,
            COALESCE(u.timezone, 'America/Chicago') AS user_timezone,
            EXTRACT(HOUR FROM NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago')) AS current_local_hour,
            h.id AS household_id,
            h.name AS household_name,
            h.subscription_status,
            h.is_premium
        FROM auth_users u
        JOIN auth_household_members hm ON hm.user_id = u.id
        JOIN auth_households h ON h.id = hm.household_id
        WHERE (
            h.subscription_status IN ('premium', 'active')
            OR (
                h.subscription_status = 'trial' 
                AND (h.trial_ends_at IS NULL OR h.trial_ends_at >= NOW())
            )
        )
        {hour_clause}
        AND EXISTS (
            SELECT 1 FROM push_subscriptions ps
            WHERE ps.user_id = u.id
              AND ps.is_active = TRUE
              AND ps.permission_status = 'granted'
        )
        AND EXISTS (
            SELECT 1 FROM still_good_items sgi
            WHERE sgi.household_id = h.id
              AND sgi.status = 'active'
              AND sgi.location = 'fridge'
              AND sgi.item_type != 'produce'
              AND (
                (COALESCE(sgi.remind_cadence, 'daily') != 'at_expiry' AND (sgi.snooze_until IS NULL OR sgi.snooze_until <= DATE(NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago'))))
                OR (sgi.consume_by IS NOT NULL AND sgi.consume_by <= DATE(NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago')))
              )
        )
        AND NOT EXISTS (
            SELECT 1 FROM push_notifications_log pnl
            WHERE pnl.target_type = 'user'
              AND pnl.target_id = u.id
              AND pnl.custom_data->>'campaign' = 'still_good_lunch_7am'
              AND DATE(pnl.created_at AT TIME ZONE COALESCE(u.timezone, 'America/Chicago')) = 
                  DATE(NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago'))
        )
        ORDER BY h.id ASC, u.id ASC
    """

    try:
        candidates = _run(candidate_query, params if params else None)
    except Exception as e:
        print(f"[check_still_good_fridge_lunch_pushes] Query error: {e}", flush=True)
        return {"ok": False, "error": str(e), "dispatched": 0, "candidates": 0}

    print(f"  -> Found {len(candidates)} candidate user(s) for Still Good fridge lunch pushes.")
    results = []
    dispatched_count = 0

    hh_fridge_cache = {}
    dispatched_uids = set()

    for cand in candidates:
        uid = cand.get("user_id")
        hhid = cand.get("household_id")
        if not uid or int(uid) == 0 or not hhid or int(hhid) == 0:
            continue
        uid = int(uid)
        hhid = int(hhid)
        if uid in dispatched_uids:
            continue

        if hhid not in hh_fridge_cache:
            try:
                fridge_items = _run("""
                    SELECT id, name, consume_by, date_added
                    FROM still_good_items
                    WHERE household_id = %s
                      AND status = 'active'
                      AND location = 'fridge'
                      AND item_type != 'produce'
                      AND (
                        (COALESCE(remind_cadence, 'daily') != 'at_expiry' AND (snooze_until IS NULL OR snooze_until <= CURRENT_DATE))
                        OR (consume_by IS NOT NULL AND consume_by <= CURRENT_DATE)
                      )
                    ORDER BY consume_by ASC NULLS LAST, id ASC
                """, (hhid,))
                hh_fridge_cache[hhid] = fridge_items or []
            except Exception as item_err:
                print(f"  [Warning] Failed to fetch fridge items for Household #{hhid}: {item_err}")
                hh_fridge_cache[hhid] = []

        items = hh_fridge_cache.get(hhid, [])
        total_count = len(items)
        if total_count == 0:
            continue

        title = "🍱 Packing lunch today?"
        if total_count == 1:
            dish_name = (items[0].get("name") or "").strip() or "leftovers"
            body = f"You have {dish_name} in the fridge ready to enjoy before it expires."
        elif total_count in (2, 3):
            most_urgent = (items[0].get("name") or "").strip() or "leftovers"
            remaining = total_count - 1
            meal_word = "other meal" if remaining == 1 else "other meals"
            body = f"You have {most_urgent} and {remaining} {meal_word} waiting in the fridge."
        else:  # 4+
            body = f"Your fridge has {total_count} meals waiting to be enjoyed. Check Still Good before heading out!"

        deep_link_url = "/?screen=stillGood&source=push_lunch_7am"
        push_data = {
            "action": "open_screen",
            "screen": "stillGood",
            "campaign": "still_good_lunch_7am",
            "source": "push_lunch_7am",
            "url": deep_link_url,
            "household_id": str(hhid),
            "fridge_count": str(total_count)
        }

        if dry_run:
            print(f"  [DRY RUN] Would dispatch 'still_good_lunch_7am' to User #{uid} ({cand.get('user_email')}): '{title}' / '{body}'")
            results.append({
                "user_id": uid,
                "household_id": hhid,
                "campaign": "still_good_lunch_7am",
                "title": title,
                "body": body,
                "data": push_data,
                "status": "dry_run"
            })
            continue

        try:
            res = send_push_to_user(
                user_id=uid,
                title=title,
                body=body,
                data=push_data
            )
            sent_cnt = res.get("sent", 0)
            mock_mode = res.get("mock", False)
            print(f"  [Dispatch] Sent 'still_good_lunch_7am' push to User #{uid} (sent={sent_cnt}, mock={mock_mode}, res={res})")

            if sent_cnt == 0 and not res.get("error"):
                authmod.log_push_dispatch(
                    target_type="user",
                    target_id=uid,
                    title=title,
                    body=body,
                    url=deep_link_url,
                    custom_data=push_data,
                    tokens_count=0,
                    sent_count=0,
                    failed_count=0,
                    errors=["no_active_tokens"],
                    is_mock=True
                )

            dispatched_count += 1
            dispatched_uids.add(uid)
            results.append({
                "user_id": uid,
                "household_id": hhid,
                "campaign": "still_good_lunch_7am",
                "title": title,
                "body": body,
                "result": res,
                "status": "sent"
            })
        except Exception as dispatch_err:
            print(f"  [Error] Failed to dispatch push to User #{uid}: {dispatch_err}")
            results.append({
                "user_id": uid,
                "household_id": hhid,
                "campaign": "still_good_lunch_7am",
                "error": str(dispatch_err),
                "status": "error"
            })

    return {
        "ok": True,
        "dispatched": dispatched_count,
        "candidates": len(candidates),
        "results": results,
        "dry_run": dry_run
    }


def check_still_good_produce_expiry_pushes(target_hour: int = 10, dry_run: bool = False, force_send: bool = False):
    """
    10:00 AM Local Time Fresh Produce Expiry Push Reminder (Issue #612)

    1. Evaluates candidate users at 10:00 AM local time based on their timezone
       (auth_users.timezone, fallback America/Chicago).
    2. Eligible households: Pro and active Pro Trial (subscription_status IN ('premium', 'active', 'trial')).
       If trial, ensure trial_ends_at is valid and has not expired.
    3. Requires active push subscription (permission_status = 'granted').
    4. Household must have at least 1 active Fresh Produce item (item_type = 'produce', status = 'active')
       whose consume_by date is today or tomorrow (1 day before expiry) in the user's local timezone.
    5. Dynamic copy based on urgency:
       - Expiring today takes precedence:
         * 1 item: "⏳ Fresh Produce: Use Today" / "Your {name} needs to be used today before it spoils."
         * 2 items: "⏳ Fresh Produce: Use Today" / "Your {name1} and {name2} expire today. Plan to use them up!"
         * 3+ items: "⏳ Fresh Produce: Use Today" / "{name1} and {rem} other fresh produce items expire today. Check Still Good!"
       - If items expire both today and tomorrow:
         * "⏳ Fresh Produce: Use Today" / "{name1} expires today, plus {other_count} expiring tomorrow. Check Still Good!"
       - If only expiring tomorrow (1-day before reminder):
         * 1 item: "🥗 Fresh Produce Reminder" / "Your {name} expires tomorrow. Plan to enjoy or use it soon!"
         * 2 items: "🥗 Fresh Produce Reminder" / "Your {name1} and {name2} expire tomorrow. Enjoy them before they spoil!"
         * 3+ items: "🥗 Fresh Produce Reminder" / "You have {count} produce items (including {name1}) expiring tomorrow."
    6. Idempotency & Frequency Capping:
       - Scoped via push_notifications_log with campaign = 'still_good_produce_expiry_10am' on the current local calendar date.
       - Max 1 produce reminder per user per local calendar day.
    7. Deep link: /?screen=stillGood&source=push_produce_10am
    """
    _init_schema()

    print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] Checking Still Good fresh produce expiry pushes (target_hour={target_hour}, dry_run={dry_run}, force_send={force_send})...")

    hour_clause = ""
    params = {}
    if not force_send and target_hour is not None:
        hour_clause = "AND EXTRACT(HOUR FROM NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago')) = %(target_hour)s"
        params["target_hour"] = int(target_hour)

    candidate_query = f"""
        SELECT 
            u.id AS user_id,
            u.name AS user_name,
            u.email AS user_email,
            COALESCE(u.timezone, 'America/Chicago') AS user_timezone,
            EXTRACT(HOUR FROM NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago')) AS current_local_hour,
            (NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago'))::date AS local_date,
            h.id AS household_id,
            h.name AS household_name,
            h.subscription_status,
            h.is_premium
        FROM auth_users u
        JOIN auth_household_members hm ON hm.user_id = u.id
        JOIN auth_households h ON h.id = hm.household_id
        WHERE (
            h.subscription_status IN ('premium', 'active')
            OR (
                h.subscription_status = 'trial' 
                AND (h.trial_ends_at IS NULL OR h.trial_ends_at >= NOW())
            )
        )
        {hour_clause}
        AND EXISTS (
            SELECT 1 FROM push_subscriptions ps
            WHERE ps.user_id = u.id
              AND ps.is_active = TRUE
              AND ps.permission_status = 'granted'
        )
        AND EXISTS (
            SELECT 1 FROM still_good_items sgi
            WHERE sgi.household_id = h.id
              AND sgi.status = 'active'
              AND sgi.item_type = 'produce'
              AND (sgi.location IS NULL OR sgi.location != 'freezer')
              AND sgi.consume_by IS NOT NULL
              AND sgi.consume_by IN (
                  (NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago'))::date,
                  (NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago'))::date + 1
              )
              AND (
                  (COALESCE(sgi.remind_cadence, 'daily') != 'at_expiry' AND (sgi.snooze_until IS NULL OR sgi.snooze_until <= (NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago'))::date))
                  OR (sgi.consume_by <= (NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago'))::date)
              )
        )
        AND NOT EXISTS (
            SELECT 1 FROM push_notifications_log pnl
            WHERE pnl.target_type = 'user'
              AND pnl.target_id = u.id
              AND pnl.custom_data->>'campaign' = 'still_good_produce_expiry_10am'
              AND DATE(pnl.created_at AT TIME ZONE COALESCE(u.timezone, 'America/Chicago')) = 
                  DATE(NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago'))
        )
        ORDER BY h.id ASC, u.id ASC
    """

    try:
        candidates = _run(candidate_query, params if params else None)
    except Exception as e:
        print(f"[check_still_good_produce_expiry_pushes] Query error: {e}", flush=True)
        return {"ok": False, "error": str(e), "dispatched": 0, "candidates": 0}

    print(f"  -> Found {len(candidates)} candidate user(s) for Still Good fresh produce expiry pushes.")
    results = []
    dispatched_count = 0

    hh_produce_cache = {}
    dispatched_uids = set()

    for cand in candidates:
        uid = cand.get("user_id")
        hhid = cand.get("household_id")
        if not uid or int(uid) == 0 or not hhid or int(hhid) == 0:
            continue
        uid = int(uid)
        hhid = int(hhid)
        if uid in dispatched_uids:
            continue

        local_date_str = str(cand.get("local_date") or "")
        cache_key = (hhid, local_date_str)

        if cache_key not in hh_produce_cache:
            try:
                produce_items = _run("""
                    SELECT id, name, location, TO_CHAR(consume_by, 'YYYY-MM-DD') as consume_by
                    FROM still_good_items
                    WHERE household_id = %s
                      AND status = 'active'
                      AND item_type = 'produce'
                      AND (location IS NULL OR location != 'freezer')
                      AND consume_by IS NOT NULL
                      AND consume_by >= %s::date
                      AND consume_by <= (%s::date + INTERVAL '1 day')
                      AND (
                        (COALESCE(remind_cadence, 'daily') != 'at_expiry' AND (snooze_until IS NULL OR snooze_until <= %s::date))
                        OR (consume_by <= %s::date)
                      )
                    ORDER BY consume_by ASC, id ASC
                """, (hhid, local_date_str, local_date_str, local_date_str, local_date_str))
                hh_produce_cache[cache_key] = produce_items or []
            except Exception as item_err:
                print(f"  [Warning] Failed to fetch produce items for Household #{hhid}: {item_err}")
                hh_produce_cache[cache_key] = []

        items = hh_produce_cache.get(cache_key, [])
        if not items:
            continue

        items_today = [i for i in items if (i.get("consume_by") or "") == local_date_str]
        items_tomorrow = [i for i in items if (i.get("consume_by") or "") > local_date_str]

        if items_today and items_tomorrow:
            title = "⏳ Fresh Produce: Use Today"
            first_name = (items_today[0].get("name") or "").strip() or "produce"
            tom_count = len(items_tomorrow)
            tom_text = f"{tom_count} more tomorrow" if tom_count > 1 else "1 more tomorrow"
            if len(items_today) == 1:
                body = f"Your {first_name} expires today, plus {tom_text}. Check Still Good!"
            else:
                body = f"{first_name} and {len(items_today) - 1} other produce expire today, plus {tom_text}."
        elif items_today:
            title = "⏳ Fresh Produce: Use Today"
            first_name = (items_today[0].get("name") or "").strip() or "produce"
            if len(items_today) == 1:
                body = f"Your {first_name} needs to be used today before it spoils."
            elif len(items_today) == 2:
                second_name = (items_today[1].get("name") or "").strip() or "produce"
                body = f"Your {first_name} and {second_name} expire today. Plan to use them up!"
            else:
                rem = len(items_today) - 1
                body = f"{first_name} and {rem} other fresh produce items expire today. Check Still Good!"
        elif items_tomorrow:
            title = "🥗 Fresh Produce Reminder"
            first_name = (items_tomorrow[0].get("name") or "").strip() or "produce"
            if len(items_tomorrow) == 1:
                body = f"Your {first_name} expires tomorrow. Plan to enjoy or use it soon!"
            elif len(items_tomorrow) == 2:
                second_name = (items_tomorrow[1].get("name") or "").strip() or "produce"
                body = f"Your {first_name} and {second_name} expire tomorrow. Enjoy them before they spoil!"
            else:
                body = f"You have {len(items_tomorrow)} produce items (including {first_name}) expiring tomorrow."
        else:
            continue

        deep_link_url = "/?screen=stillGood&source=push_produce_10am"
        push_data = {
            "action": "open_screen",
            "screen": "stillGood",
            "campaign": "still_good_produce_expiry_10am",
            "source": "push_produce_10am",
            "url": deep_link_url,
            "household_id": str(hhid),
            "today_count": str(len(items_today)),
            "tomorrow_count": str(len(items_tomorrow))
        }

        if dry_run:
            print(f"  [DRY RUN] Would dispatch 'still_good_produce_expiry_10am' to User #{uid} ({cand.get('user_email')}): '{title}' / '{body}'")
            results.append({
                "user_id": uid,
                "household_id": hhid,
                "campaign": "still_good_produce_expiry_10am",
                "title": title,
                "body": body,
                "data": push_data,
                "status": "dry_run"
            })
            continue

        try:
            res = send_push_to_user(
                user_id=uid,
                title=title,
                body=body,
                data=push_data
            )
            sent_cnt = res.get("sent", 0)
            mock_mode = res.get("mock", False)
            print(f"  [Dispatch] Sent 'still_good_produce_expiry_10am' push to User #{uid} (sent={sent_cnt}, mock={mock_mode}, res={res})")

            if sent_cnt == 0 and not res.get("error"):
                authmod.log_push_dispatch(
                    target_type="user",
                    target_id=uid,
                    title=title,
                    body=body,
                    url=deep_link_url,
                    custom_data=push_data,
                    tokens_count=0,
                    sent_count=0,
                    failed_count=0,
                    errors=["no_active_tokens"],
                    is_mock=True
                )

            dispatched_count += 1
            dispatched_uids.add(uid)
            results.append({
                "user_id": uid,
                "household_id": hhid,
                "campaign": "still_good_produce_expiry_10am",
                "title": title,
                "body": body,
                "data": push_data,
                "result": res,
                "status": "sent"
            })
        except Exception as dispatch_err:
            print(f"  [Error] Failed to dispatch produce push to User #{uid}: {dispatch_err}")
            results.append({
                "user_id": uid,
                "household_id": hhid,
                "campaign": "still_good_produce_expiry_10am",
                "error": str(dispatch_err),
                "status": "error"
            })

    return {
        "ok": True,
        "dispatched": dispatched_count,
        "candidates": len(candidates),
        "results": results,
        "dry_run": dry_run
    }


def check_still_good_freezer_expiry_pushes(target_hour: int = 9, dry_run: bool = False, force_send: bool = False):
    """
    9:00 AM Local Time Freezer 1-Week Expiry Push Reminder

    1. Evaluates candidate users at 9:00 AM local time based on their timezone
       (auth_users.timezone, fallback America/Chicago).
    2. Eligible households: Pro and active Pro Trial (subscription_status IN ('premium', 'active', 'trial')).
       If trial, ensure trial_ends_at is valid and has not expired.
    3. Requires active push subscription (permission_status = 'granted').
    4. Household must have at least 1 active freezer item (location = 'freezer', status = 'active')
       whose consume_by date is 1 week away (within 7 days: consume_by <= local_date + 7 and consume_by >= local_date).
    5. Dynamic copy:
       - 1 item: "❄️ Freezer Reminder" / "Your {name} in the freezer reaches its best-by date in 1 week. Consider thawing it soon!"
       - 2 items: "❄️ Freezer Reminder" / "Your {name1} and {name2} reach best-by in 1 week. Plan to thaw and enjoy!"
       - 3+ items: "❄️ Freezer Reminder" / "You have {count} freezer meals (including {name1}) reaching best-by in 1 week. Check Still Good to thaw!"
    6. Idempotency & Frequency Capping:
       - Scoped via push_notifications_log with campaign = 'still_good_freezer_expiry_9am' on the current local calendar date.
       - Max 1 reminder per user per local calendar day.
    7. Deep link: /?screen=stillGood&tab=freezer&source=push_freezer_9am
    """
    _init_schema()

    print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] Checking Still Good freezer 1-week expiry pushes (target_hour={target_hour}, dry_run={dry_run}, force_send={force_send})...")

    hour_clause = ""
    params = {}
    if not force_send and target_hour is not None:
        hour_clause = "AND EXTRACT(HOUR FROM NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago')) = %(target_hour)s"
        params["target_hour"] = int(target_hour)

    candidate_query = f"""
        SELECT 
            u.id AS user_id,
            u.name AS user_name,
            u.email AS user_email,
            COALESCE(u.timezone, 'America/Chicago') AS user_timezone,
            EXTRACT(HOUR FROM NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago')) AS current_local_hour,
            (NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago'))::date AS local_date,
            h.id AS household_id,
            h.name AS household_name,
            h.subscription_status,
            h.is_premium
        FROM auth_users u
        JOIN auth_household_members hm ON hm.user_id = u.id
        JOIN auth_households h ON h.id = hm.household_id
        WHERE (
            h.subscription_status IN ('premium', 'active')
            OR (
                h.subscription_status = 'trial' 
                AND (h.trial_ends_at IS NULL OR h.trial_ends_at >= NOW())
            )
        )
        {hour_clause}
        AND EXISTS (
            SELECT 1 FROM push_subscriptions ps
            WHERE ps.user_id = u.id
              AND ps.is_active = TRUE
              AND ps.permission_status = 'granted'
        )
        AND EXISTS (
            SELECT 1 FROM still_good_items sgi
            WHERE sgi.household_id = h.id
              AND sgi.status = 'active'
              AND sgi.location = 'freezer'
              AND sgi.consume_by IS NOT NULL
              AND sgi.consume_by <= ((NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago'))::date + 7)
              AND sgi.consume_by >= (NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago'))::date
        )
        AND NOT EXISTS (
            SELECT 1 FROM push_notifications_log pnl
            WHERE pnl.target_type = 'user'
              AND pnl.target_id = u.id
              AND pnl.custom_data->>'campaign' = 'still_good_freezer_expiry_9am'
              AND DATE(pnl.created_at AT TIME ZONE COALESCE(u.timezone, 'America/Chicago')) = 
                  DATE(NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago'))
        )
        ORDER BY h.id ASC, u.id ASC
    """
    try:
        candidates = _run(candidate_query, params if params else None)
    except Exception as e:
        print(f"[check_still_good_freezer_expiry_pushes] Query error: {e}", flush=True)
        return {"ok": False, "error": str(e), "dispatched": 0, "candidates": 0}

    print(f"  -> Found {len(candidates)} candidate user(s) for Still Good freezer 1-week expiry pushes.")
    results = []
    dispatched_count = 0
    hh_freezer_cache = {}
    dispatched_uids = set()

    for cand in candidates:
        uid = cand.get("user_id")
        hhid = cand.get("household_id")
        if not uid or int(uid) == 0 or not hhid or int(hhid) == 0:
            continue
        uid = int(uid)
        hhid = int(hhid)
        if uid in dispatched_uids:
            continue

        local_date_str = str(cand.get("local_date") or "")
        cache_key = (hhid, local_date_str)

        if cache_key not in hh_freezer_cache:
            try:
                freezer_items = _run("""
                    SELECT id, name, location, TO_CHAR(consume_by, 'YYYY-MM-DD') as consume_by
                    FROM still_good_items
                    WHERE household_id = %s
                      AND status = 'active'
                      AND location = 'freezer'
                      AND consume_by IS NOT NULL
                      AND consume_by >= %s::date
                      AND consume_by <= (%s::date + INTERVAL '7 days')
                    ORDER BY consume_by ASC, id ASC
                """, (hhid, local_date_str, local_date_str))
                hh_freezer_cache[cache_key] = freezer_items or []
            except Exception as item_err:
                print(f"  [Warning] Failed to fetch freezer items for Household #{hhid}: {item_err}")
                hh_freezer_cache[cache_key] = []

        items = hh_freezer_cache.get(cache_key, [])
        if not items:
            continue

        title = "❄️ Freezer Reminder"
        first_name = (items[0].get("name") or "").strip() or "meal"
        if len(items) == 1:
            body = f"Your {first_name} in the freezer reaches its best-by date in 1 week. Consider thawing it soon!"
        elif len(items) == 2:
            second_name = (items[1].get("name") or "").strip() or "meal"
            body = f"Your {first_name} and {second_name} reach best-by in 1 week. Plan to thaw and enjoy!"
        else:
            rem = len(items) - 1
            body = f"You have {len(items)} freezer meals (including {first_name}) reaching best-by in 1 week. Check Still Good to thaw!"

        deep_link_url = "/?screen=stillGood&tab=freezer&source=push_freezer_9am"
        push_data = {
            "action": "open_screen",
            "screen": "stillGood",
            "tab": "freezer",
            "campaign": "still_good_freezer_expiry_9am",
            "source": "push_freezer_9am",
            "url": deep_link_url,
            "household_id": str(hhid),
            "freezer_items_count": str(len(items))
        }

        if dry_run:
            print(f"  [DRY RUN] Would dispatch 'still_good_freezer_expiry_9am' to User #{uid} ({cand.get('user_email')}): '{title}' / '{body}'")
            results.append({
                "user_id": uid,
                "household_id": hhid,
                "campaign": "still_good_freezer_expiry_9am",
                "title": title,
                "body": body,
                "data": push_data,
                "status": "dry_run"
            })
            continue

        try:
            res = send_push_to_user(
                user_id=uid,
                title=title,
                body=body,
                data=push_data
            )
            sent_cnt = res.get("sent", 0)
            mock_mode = res.get("mock", False)
            print(f"  [Dispatch] Sent 'still_good_freezer_expiry_9am' push to User #{uid} (sent={sent_cnt}, mock={mock_mode}, res={res})")

            if sent_cnt == 0 and not res.get("error"):
                authmod.log_push_dispatch(
                    target_type="user",
                    target_id=uid,
                    title=title,
                    body=body,
                    url=deep_link_url,
                    custom_data=push_data,
                    tokens_count=0,
                    sent_count=0,
                    failed_count=0,
                    errors=["no_active_tokens"],
                    is_mock=True
                )

            dispatched_count += 1
            dispatched_uids.add(uid)
            results.append({
                "user_id": uid,
                "household_id": hhid,
                "campaign": "still_good_freezer_expiry_9am",
                "title": title,
                "body": body,
                "data": push_data,
                "result": res,
                "status": "sent"
            })
        except Exception as dispatch_err:
            print(f"  [Error] Failed to dispatch freezer push to User #{uid}: {dispatch_err}")
            results.append({
                "user_id": uid,
                "household_id": hhid,
                "campaign": "still_good_freezer_expiry_9am",
                "error": str(dispatch_err),
                "status": "error"
            })

    return {
        "ok": True,
        "dispatched": dispatched_count,
        "candidates": len(candidates),
        "results": results,
        "dry_run": dry_run
    }


def check_store_plan_push_reminders(threshold_n: int = None, dry_run: bool = False, force_send: bool = False):
    """
    Store Plan Push Reminders (Hourly Evaluation):
    If stores have >= threshold_n items on the active list (configurable via
    STORE_PLAN_REMINDER_THRESHOLD, defaulting to 10) and have NO planned visit date, send
    a consolidated push notification to the household once in a 24-hour period.
    """
    _init_schema()

    if threshold_n is None:
        env_val = os.environ.get("STORE_PLAN_REMINDER_THRESHOLD")
        threshold_n = int(env_val) if env_val else 10

    print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] Checking store plan push reminders (threshold={threshold_n}, dry_run={dry_run}, force_send={force_send})...")

    # Query for stores that have >= threshold_n uncompleted list items and NO plan date
    query = """
        SELECT 
            s.id AS store_id,
            s.name AS store_name,
            s.household_id,
            COUNT(li.id) AS items_count
        FROM stores s
        JOIN auth_households h ON h.id = s.household_id
        JOIN list_items li ON li.store_id = s.id AND li.household_id = s.household_id
        WHERE li.purchased = FALSE
          AND s.planned_visit_date IS NULL
          AND (
              h.is_premium = TRUE 
              OR h.subscription_status IN ('premium', 'active')
              OR (
                  h.subscription_status = 'trial' 
                  AND (h.trial_ends_at IS NULL OR h.trial_ends_at >= NOW())
              )
          )
        GROUP BY s.id, s.name, s.household_id
        HAVING COUNT(li.id) >= %(threshold)s
        ORDER BY s.household_id ASC, items_count DESC
    """
    try:
        candidates = _run(query, {"threshold": threshold_n})
    except Exception as e:
        print(f"[check_store_plan_push_reminders] Query error: {e}", flush=True)
        return {"ok": False, "error": str(e), "dispatched": 0, "candidates": 0}

    print(f"  -> Found {len(candidates)} candidate store(s) with >= {threshold_n} items and no plan date for push.")

    # Group candidate stores by household
    hh_groups = {}
    for cand in candidates:
        hh_id = cand["household_id"]
        if hh_id not in hh_groups:
            hh_groups[hh_id] = []
        hh_groups[hh_id].append(cand)

    dispatched_count = 0
    skipped_24h = 0
    results = []

    for hh_id, stores_list in hh_groups.items():
        # 24-hour deduplication check per household in push_notifications_log
        if not force_send:
            try:
                dedup_check = _one("""
                    SELECT 1 FROM push_notifications_log
                    WHERE ((target_type = 'household' AND target_id = %s) OR (custom_data->>'household_id' = %s))
                      AND (
                          custom_data->>'type' = 'store_plan_reminder'
                          OR custom_data->>'type' = 'general_list_reminder'
                      )
                      AND created_at >= NOW() - INTERVAL '24 hours'
                """, (hh_id, str(hh_id)))
            except Exception as d_err:
                print(f"  [Warning] Deduplication check failed for HH #{hh_id}: {d_err}")
                dedup_check = None

            if dedup_check:
                skipped_24h += 1
                continue

        regular_stores = [s for s in stores_list if s["store_name"].strip().lower() != "general list"]
        general_stores = [s for s in stores_list if s["store_name"].strip().lower() == "general list"]

        if len(regular_stores) >= 2:
            # Case 1: Multiple regular stores -> Combine into one notification
            names = [s["store_name"] for s in regular_stores]
            if len(names) == 2:
                stores_text = f"{names[0]} and {names[1]}"
            else:
                stores_text = f"{names[0]}, {names[1]}, and {len(names) - 2} other stores"
            p_title = "📅 Plan your shopping trips"
            p_body = f"{stores_text} have {threshold_n}+ items. Pick dates to plan your visits!"
            store_ids_csv = ",".join(str(s["store_id"]) for s in regular_stores)
            p_data = {
                "type": "store_plan_reminder",
                "action": "plan_modal",
                "household_id": str(hh_id),
                "store_ids": store_ids_csv,
                "campaign": f"store_plan_reminder_multi_{hh_id}",
                "url": f"/?action=plan_modal&stores={store_ids_csv}"
            }
            store_label = f"Multiple stores ({store_ids_csv})"
            target_store_id = None
        elif len(regular_stores) == 1:
            # Case 2: Exactly 1 regular store
            cand = regular_stores[0]
            target_store_id = cand["store_id"]
            store_name = cand["store_name"]
            items_count = cand["items_count"]
            p_title = f"📅 Plan your trip to {store_name}"
            p_body = f"You have {items_count} items on your {store_name} list. Pick a date to plan your shopping trip!"
            p_data = {
                "type": "store_plan_reminder",
                "action": "open_store",
                "store_id": str(target_store_id),
                "store_name": store_name,
                "household_id": str(hh_id),
                "campaign": f"store_plan_reminder_{target_store_id}",
                "url": f"/?store_id={target_store_id}&action=plan"
            }
            store_label = f"Store #{target_store_id} ({store_name})"
        elif len(general_stores) > 0:
            # Case 3: Only General List qualifies
            cand = general_stores[0]
            target_store_id = cand["store_id"]
            items_count = cand["items_count"]
            p_title = "📋 Organize your General List"
            p_body = f"You have {items_count} items in your General List. Move items to specific stores to plan your shopping trips!"
            p_data = {
                "type": "general_list_reminder",
                "action": "general_list_info",
                "store_id": str(target_store_id),
                "household_id": str(hh_id),
                "campaign": f"general_list_reminder_{hh_id}",
                "url": f"/?action=general_list_info&store_id={target_store_id}"
            }
            store_label = f"General List #{target_store_id}"
        else:
            continue

        if dry_run:
            print(f"  [DRY-RUN] Would send store plan push to HH #{hh_id} for {store_label}: {p_title} | {p_body}")
            dispatched_count += 1
            results.append({
                "household_id": hh_id,
                "store_id": target_store_id,
                "status": "dry_run",
                "title": p_title,
                "body": p_body
            })
        else:
            try:
                res = send_push_to_household(hh_id, p_title, p_body, p_data)
                sent_cnt = res.get("sent", 0)
                mock_mode = res.get("mock", False)
                if sent_cnt > 0 or mock_mode:
                    print(f"  ✔ Sent plan reminder push to HH #{hh_id} for {store_label} (sent={sent_cnt}, mock={mock_mode})")
                    dispatched_count += 1
                    status_str = "sent"
                else:
                    msg = res.get("message") or res.get("error") or "No active tokens for household"
                    print(f"  ℹ Skipped plan reminder push to HH #{hh_id} for {store_label}: {msg} (sent=0)")
                    status_str = "skipped_no_tokens"
                results.append({
                    "household_id": hh_id,
                    "store_id": target_store_id,
                    "status": status_str,
                    "result": res
                })
            except Exception as send_err:
                print(f"  [Error] Failed to send push to HH #{hh_id} for {store_label}: {send_err}")
                results.append({
                    "household_id": hh_id,
                    "store_id": target_store_id,
                    "status": "error",
                    "error": str(send_err)
                })

    return {
        "ok": True,
        "dispatched": dispatched_count,
        "candidates": len(candidates),
        "skipped_24h": skipped_24h,
        "results": results,
        "dry_run": dry_run
    }


def check_post_shopping_smart_stash_pushes(dry_run: bool = False, force_send: bool = False):
    """
    Post-Shopping Smart Stash Crisper Drawer Push Reminder (Issue #632)

    1. Evaluates candidate households/users with unstashed fresh grocery items from shopping trips completed >= 3 hours ago.
    2. Eligible households: Pro and active Pro Trial (subscription_status IN ('premium', 'active', 'trial')).
       If trial, ensure trial_ends_at is valid and has not expired.
    3. Requires active push subscription (permission_status = 'granted').
    4. Household must have at least 1 unstashed perishable candidate from a trip >= 3 hours ago:
       - purchased = TRUE
       - still_good_stashed_at IS NULL
       - ((trip_notified_at IS NOT NULL AND trip_notified_at <= NOW() - INTERVAL '3 hours') OR (purchased_at <= NOW() - INTERVAL '3 hours'))
       - purchased_at >= NOW() - INTERVAL '48 hours'
       - Perishable categories: produce, dairy, meat, seafood, refrigerated, deli, bakery, or uncategorized.
    5. Frequency capping & Idempotency:
       - Scoped via push_notifications_log with campaign = 'still_good_smart_stash_3h'.
       - Max 1 reminder per user per local calendar day.
    6. Deep link: /?screen=stillGood&tab=stash&source=push_smart_stash_3h
    """
    _init_schema()

    print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] Checking Still Good post-shopping smart stash pushes (dry_run={dry_run}, force_send={force_send})...")

    candidate_query = """
        SELECT 
            u.id AS user_id,
            u.name AS user_name,
            u.email AS user_email,
            COALESCE(u.timezone, 'America/Chicago') AS user_timezone,
            h.id AS household_id,
            h.name AS household_name,
            h.subscription_status,
            h.is_premium
        FROM auth_users u
        JOIN auth_household_members hm ON hm.user_id = u.id
        JOIN auth_households h ON h.id = hm.household_id
        WHERE (
            h.subscription_status IN ('premium', 'active')
            OR (
                h.subscription_status = 'trial' 
                AND (h.trial_ends_at IS NULL OR h.trial_ends_at >= NOW())
            )
        )
        AND EXISTS (
            SELECT 1 FROM push_subscriptions ps
            WHERE ps.user_id = u.id
              AND ps.is_active = TRUE
              AND ps.permission_status = 'granted'
        )
        AND EXISTS (
            SELECT 1 FROM list_items li
            WHERE li.household_id = h.id
              AND li.purchased = TRUE
              AND li.still_good_stashed_at IS NULL
              AND (
                (li.trip_notified_at IS NOT NULL AND li.trip_notified_at <= NOW() - INTERVAL '3 hours')
                OR (li.purchased_at <= NOW() - INTERVAL '3 hours')
              )
              AND li.purchased_at >= NOW() - INTERVAL '48 hours'
              AND (
                li.category IS NULL OR li.category = ''
                OR LOWER(li.category) IN ('uncategorized', 'other', 'general')
                OR LOWER(li.category) LIKE '%produce%'
                OR LOWER(li.category) LIKE '%dairy%'
                OR LOWER(li.category) LIKE '%meat%'
                OR LOWER(li.category) LIKE '%seafood%'
                OR LOWER(li.category) LIKE '%refrigerated%'
                OR LOWER(li.category) LIKE '%deli%'
                OR LOWER(li.category) LIKE '%bakery%'
              )
        )
    """

    if not force_send:
        candidate_query += """
        AND NOT EXISTS (
            SELECT 1 FROM push_notifications_log pnl
            WHERE pnl.target_type = 'user'
              AND pnl.target_id = u.id
              AND pnl.custom_data->>'campaign' = 'still_good_smart_stash_3h'
              AND DATE(pnl.created_at AT TIME ZONE COALESCE(u.timezone, 'America/Chicago')) = 
                  DATE(NOW() AT TIME ZONE COALESCE(u.timezone, 'America/Chicago'))
        )
        """

    candidate_query += " ORDER BY h.id ASC, u.id ASC"

    try:
        candidates = _run(candidate_query)
    except Exception as e:
        print(f"[check_post_shopping_smart_stash_pushes] Query error: {e}", flush=True)
        return {"ok": False, "error": str(e), "dispatched": 0, "candidates": 0}

    print(f"  -> Found {len(candidates)} candidate user(s) for Still Good post-shopping smart stash pushes.")
    results = []
    dispatched_count = 0

    hh_items_cache = {}
    dispatched_uids = set()

    for cand in candidates:
        uid = cand.get("user_id")
        hhid = cand.get("household_id")
        if not uid or int(uid) == 0 or not hhid or int(hhid) == 0:
            continue
        uid = int(uid)
        hhid = int(hhid)
        if uid in dispatched_uids:
            continue

        if hhid not in hh_items_cache:
            try:
                unstashed_items = _run("""
                    SELECT id, name, category, purchased_at
                    FROM list_items
                    WHERE household_id = %s
                      AND purchased = TRUE
                      AND still_good_stashed_at IS NULL
                      AND (
                        (trip_notified_at IS NOT NULL AND trip_notified_at <= NOW() - INTERVAL '3 hours')
                        OR (purchased_at <= NOW() - INTERVAL '3 hours')
                      )
                      AND purchased_at >= NOW() - INTERVAL '48 hours'
                    ORDER BY purchased_at DESC
                """, (hhid,))

                perishables = []
                for it in (unstashed_items or []):
                    cat = (it.get("category") or "").strip().lower()
                    if not cat or cat in ('uncategorized', 'other', 'general'):
                        perishables.append(it)
                    elif any(p in cat for p in ['produce', 'dairy', 'meat', 'seafood', 'refrigerated', 'deli', 'bakery']):
                        perishables.append(it)

                hh_items_cache[hhid] = perishables
            except Exception as item_err:
                print(f"  [Warning] Failed to fetch unstashed candidates for Household #{hhid}: {item_err}")
                hh_items_cache[hhid] = []

        items = hh_items_cache.get(hhid, [])
        total_count = len(items)
        if total_count == 0:
            continue

        title = "🥬 Stash your fresh groceries?"
        first_name = (items[0].get("name") or "").strip() or "item"
        if total_count == 1:
            body = f"Keep track of your {first_name} before it expires. Stash it in Still Good with one tap!"
        elif total_count in (2, 3):
            remaining = total_count - 1
            other_word = "other item" if remaining == 1 else "other items"
            body = f"Keep track of {first_name} and {remaining} {other_word} in Still Good to prevent food waste."
        else:
            body = f"You have {total_count} fresh grocery items from your recent trip. Add them to Still Good to track freshness!"

        deep_link_url = "/?screen=stillGood&tab=stash&source=push_smart_stash_3h"
        push_data = {
            "action": "open_screen",
            "screen": "stillGood",
            "campaign": "still_good_smart_stash_3h",
            "source": "push_smart_stash_3h",
            "url": deep_link_url,
            "household_id": str(hhid),
            "candidate_count": str(total_count)
        }

        if dry_run:
            print(f"  [DRY RUN] Would dispatch 'still_good_smart_stash_3h' to User #{uid} ({cand.get('user_email')}): '{title}' / '{body}'")
            results.append({
                "user_id": uid,
                "household_id": hhid,
                "campaign": "still_good_smart_stash_3h",
                "title": title,
                "body": body,
                "data": push_data,
                "status": "dry_run"
            })
            continue

        try:
            res = send_push_to_user(
                user_id=uid,
                title=title,
                body=body,
                data=push_data
            )
            sent_cnt = res.get("sent", 0)
            mock_mode = res.get("mock", False)
            print(f"  [Dispatch] Sent 'still_good_smart_stash_3h' push to User #{uid} (sent={sent_cnt}, mock={mock_mode}, res={res})")

            if sent_cnt == 0 and not res.get("error"):
                authmod.log_push_dispatch(
                    target_type="user",
                    target_id=uid,
                    title=title,
                    body=body,
                    url=deep_link_url,
                    custom_data=push_data,
                    tokens_count=0,
                    sent_count=0,
                    failed_count=0,
                    errors=["no_active_tokens"],
                    is_mock=True
                )

            dispatched_count += 1
            dispatched_uids.add(uid)
            results.append({
                "user_id": uid,
                "household_id": hhid,
                "campaign": "still_good_smart_stash_3h",
                "title": title,
                "body": body,
                "status": "sent" if (sent_cnt > 0 or mock_mode) else "skipped_no_tokens",
                "result": res
            })
        except Exception as dispatch_err:
            print(f"  [Error] Failed to send 'still_good_smart_stash_3h' to User #{uid}: {dispatch_err}")
            results.append({
                "user_id": uid,
                "household_id": hhid,
                "campaign": "still_good_smart_stash_3h",
                "status": "error",
                "error": str(dispatch_err)
            })

    return {
        "ok": True,
        "candidates": len(candidates),
        "dispatched": dispatched_count,
        "results": results
    }

