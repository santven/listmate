import os
import json
import logging
from typing import List, Dict, Any, Optional

import shared.auth as authmod

logger = logging.getLogger(__name__)

# Cache for initialized Firebase App
_firebase_initialized = False


def _get_firebase_app():
    """Lazily initialize the Firebase Admin SDK if service credentials are present.
    Supports either:
    1. FIREBASE_SERVICE_ACCOUNT_JSON (raw JSON string or filepath)
    2. GOOGLE_APPLICATION_CREDENTIALS (filepath)
    """
    global _firebase_initialized
    if _firebase_initialized:
        return True

    try:
        import firebase_admin
        from firebase_admin import credentials

        # Check if already initialized in another module
        if firebase_admin._apps:
            _firebase_initialized = True
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
            _firebase_initialized = True
            logger.info("[PushHelper] Firebase Admin initialized with FIREBASE_SERVICE_ACCOUNT_JSON.")
            return True
        elif google_app_cred and os.path.exists(google_app_cred):
            cred = credentials.Certificate(google_app_cred)
            firebase_admin.initialize_app(cred)
            _firebase_initialized = True
            logger.info("[PushHelper] Firebase Admin initialized with GOOGLE_APPLICATION_CREDENTIALS.")
            return True
        else:
            logger.warning("[PushHelper] No Firebase Admin credentials found in environment. Push dispatch will run in mock/log mode.")
            return False
    except Exception as e:
        logger.error(f"[PushHelper] Failed to initialize Firebase Admin: {e}")
        return False


def _send_fcm_multicast(tokens: List[str], title: str, body: str, data: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Send multicast notification via Firebase Cloud Messaging with dead token collection."""
    if not tokens:
        return {"sent": 0, "failed": 0, "unregistered": []}

    # Format custom data as strings
    clean_data = {}
    if data:
        for k, v in data.items():
            clean_data[str(k)] = str(v)

    app_ready = _get_firebase_app()
    if not app_ready:
        # Mock/development fallback: log delivery payload safely
        print(f"[PushHelper:MockDispatch] Would push to {len(tokens)} token(s) | Title: '{title}' | Body: '{body}' | Data: {clean_data}")
        return {"sent": len(tokens), "failed": 0, "unregistered": [], "mock": True}

    try:
        from firebase_admin import messaging

        notification = messaging.Notification(
            title=title,
            body=body,
        )

        # Build Android config
        android_config = None
        try:
            if hasattr(messaging, 'AndroidConfig') and hasattr(messaging, 'AndroidNotification'):
                android_config = messaging.AndroidConfig(
                    priority='high',
                    notification=messaging.AndroidNotification(
                        sound='default',
                        click_action=clean_data.get('url', '/'),
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

        multicast_kwargs = {
            "tokens": tokens,
            "notification": notification,
            "data": clean_data,
        }
        if android_config:
            multicast_kwargs["android"] = android_config
        if apns_config:
            multicast_kwargs["apns"] = apns_config

        message = messaging.MulticastMessage(**multicast_kwargs)

        response = messaging.send_each_for_multicast(message)

        dead_tokens = []
        errors = []
        success_count = response.success_count
        failure_count = response.failure_count

        for idx, resp in enumerate(response.responses):
            token = tokens[idx]
            if not resp.success:
                err = resp.exception
                err_str = str(err)
                err_code = getattr(err, 'code', 'UNKNOWN')
                print(f"[PushHelper:Failure] Token {token[:12]}... ErrorCode={err_code} Exception={err_str}", flush=True)
                logger.error(f"[PushHelper:Failure] Token {token[:12]}... ErrorCode={err_code} Exception={err_str}")
                errors.append(f"{err_code}: {err_str}")

                # Check for dead/unregistered tokens
                if err and hasattr(err, 'code') and err.code in ('UNREGISTERED', 'INVALID_ARGUMENT'):
                    dead_tokens.append(token)
                elif 'registration-token-not-registered' in err_str.lower():
                    dead_tokens.append(token)
            else:
                msg_id = getattr(resp, 'message_id', 'ok')
                print(f"[PushHelper:Success] Token {token[:12]}... MessageId={msg_id}", flush=True)

        if dead_tokens:
            print(f"[PushHelper] Pruning {len(dead_tokens)} inactive/unregistered token(s).", flush=True)
            logger.info(f"[PushHelper] Pruning {len(dead_tokens)} inactive/unregistered token(s).")
            authmod.mark_tokens_inactive(dead_tokens)

        return {
            "sent": success_count,
            "failed": failure_count,
            "unregistered": dead_tokens,
            "errors": errors,
            "mock": False,
        }
    except Exception as e:
        print(f"[PushHelper:Exception] Multicast dispatch error: {e}", flush=True)
        logger.error(f"[PushHelper] Multicast dispatch error: {e}")
        return {"sent": 0, "failed": len(tokens), "error": str(e), "errors": [str(e)], "unregistered": []}


def send_push_to_user(user_id: int, title: str, body: str, data: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Send push notification to all active devices registered by a specific user.
    Handles '0 vs None' integer bounds safely.
    """
    if not user_id or user_id == 0:
        return {"sent": 0, "failed": 0, "error": "Invalid user_id"}

    token_rows = authmod.get_active_tokens_for_user(user_id)
    if not token_rows:
        return {"sent": 0, "failed": 0, "message": "No active tokens for user"}

    tokens = [r["token"] for r in token_rows if r.get("token")]
    return _send_fcm_multicast(tokens, title, body, data)


def send_push_to_household(household_id: int, title: str, body: str, data: Optional[Dict[str, str]] = None, exclude_user_id: Optional[int] = None) -> Dict[str, Any]:
    """Send push notification to all active members of a household (e.g. partner sync or list updates).
    Can exclude the actor's user_id so they don't get alerted for their own edits.
    """
    if not household_id or household_id == 0:
        return {"sent": 0, "failed": 0, "error": "Invalid household_id"}

    ex_uid = None if (exclude_user_id is None or exclude_user_id == 0) else int(exclude_user_id)
    token_rows = authmod.get_active_tokens_for_household(household_id, exclude_user_id=ex_uid)
    if not token_rows:
        return {"sent": 0, "failed": 0, "message": "No active tokens for household"}

    tokens = [r["token"] for r in token_rows if r.get("token")]
    return _send_fcm_multicast(tokens, title, body, data)


def send_push_broadcast(title: str, body: str, data: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Send push notification to all registered active devices across the application."""
    try:
        authmod._init_schema()
        rows = authmod._run("SELECT token FROM push_subscriptions WHERE is_active = TRUE")
        tokens = [r["token"] for r in rows if r.get("token")]
        if not tokens:
            return {"sent": 0, "failed": 0, "message": "No active tokens"}
        return _send_fcm_multicast(tokens, title, body, data)
    except Exception as e:
        logger.error(f"[PushHelper] Broadcast error: {e}")
        return {"sent": 0, "failed": 0, "error": str(e)}
