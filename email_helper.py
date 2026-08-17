#!/usr/bin/env python3
"""Amazon SES email helper — migrated from SendGrid."""
import os

# Configuration
# Prefer AWS_SES_FROM if set (e.g. "ListMate <hello@grocerlist.app>"), fallback to individual vars
FROM_EMAIL = os.environ.get("AWS_SES_FROM", os.environ.get("SENDGRID_FROM", "hello@grocerlist.app"))
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

def _send_ses_email(to_email: str, subject: str, body_text: str, body_html: str) -> bool:
    """Send email via Amazon SES."""
    try:
        import boto3
        from botocore.exceptions import ClientError
    except ImportError:
        print("WARNING: boto3 not installed — SES email skipped")
        return False

    access_key = os.environ.get("AWS_ACCESS_KEY_ID")
    secret_key = os.environ.get("AWS_SECRET_ACCESS_KEY")
    
    if not access_key or not secret_key:
        print("WARNING: AWS SES credentials not set — skipping email")
        return False

    client = boto3.client(
        'ses',
        region_name=AWS_REGION,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key
    )

    try:
        response = client.send_email(
            Destination={
                'ToAddresses': [to_email],
            },
            Message={
                'Body': {
                    'Html': {
                        'Charset': "UTF-8",
                        'Data': body_html,
                    },
                    'Text': {
                        'Charset': "UTF-8",
                        'Data': body_text,
                    },
                },
                'Subject': {
                    'Charset': "UTF-8",
                    'Data': subject,
                },
            },
            Source=FROM_EMAIL,
        )
        return True
    except ClientError as e:
        print(f"SES Error: {e.response['Error']['Message']}")
        return False


def send_invite(to_email: str, invite_link: str, household_name: str, inviter_name: str = "someone", marketing_opt_in: bool = False) -> bool:
    """Send a household invite email. Returns True on success."""
    subject = f"{inviter_name} invited you to join {household_name} on ListMate"
    
    marketing_txt = '\n\nThe household owner has opted in to marketing emails. You will default to the same setting for this household, but you can change it in your settings.' if marketing_opt_in else ''
    marketing_html = '<p style="font-size: 11px; color: #888; margin-top: 20px;">The household owner has opted in to marketing emails. You will default to the same setting for this household, but you can change it in your settings.</p>' if marketing_opt_in else ''

    body_text = f"Hi!\n\n{inviter_name} invited you to join \"{household_name}\" on ListMate — a shared grocery list app for your household.\n\nTo accept this invitation, click the link below and sign in with your Google account:\n\n{invite_link}\n\nThis link expires in 7 days.\n\n— The ListMate Team" + marketing_txt
    body_html = f'<div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:20px"><h2 style="color:#2c5a2c">🛒 You\'re invited!</h2><p style="font-size:16px">{inviter_name} invited you to join <strong>{household_name}</strong> on ListMate.</p><p>ListMate helps your household keep shared grocery lists, organized by store.</p><p style="margin:24px 0"><a href="{invite_link}" style="background:#5ebe7e;color:#fff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:bold">Accept Invitation</a></p><p style="font-size:12px;color:#888">This link expires in 7 days.</p>' + marketing_html + '</div>'
    
    return _send_ses_email(to_email, subject, body_text, body_html)


def _get_unsub_link(user_id: int) -> str:
    if not user_id: return ""
    import base64, json
    data = {"uid": user_id}
    token = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    return f"https://grocerlist.app/api/unsubscribe?token={token}"

def send_subscription_notice(to_email: str, user_name: str, is_trial: bool, days_left: int, user_id: int = 0) -> bool:
    """Send subscription ending notice. Returns True on success."""
    term = "trial" if is_trial else "subscription"
    if days_left == 0:
        subject = f"Your ListMate {term} ends today"
        urgency_text = "expires today"
    else:
        subject = f"Your ListMate {term} ends in {days_left} days"
        urgency_text = f"expires in {days_left} days"

    upgrade_link = "https://listmate.app/upgrade?source=email_reminder"

    unsub_link = _get_unsub_link(user_id) if user_id else ""
    unsub_txt = f"\n\nTo unsubscribe from these emails, visit: {unsub_link}" if unsub_link else ""
    unsub_html = f'<p style="font-size: 11px; color: #888; margin-top: 30px; text-align: center;"><a href="{unsub_link}" style="color: #888; text-decoration: underline;">Unsubscribe</a> from marketing emails.</p>' if unsub_link else ""
    
    body_text = f"Hi {user_name},\n\nYour ListMate {term} {urgency_text}.\n\nDon't lose access to your shared grocery lists! Tap the link below to upgrade your household and keep everything syncing seamlessly.\n\n{upgrade_link}\n\n— The ListMate Team" + unsub_txt
    body_html = f'<div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:20px"><h2 style="color:#2c5a2c">⏳ Action Required</h2><p style="font-size:16px">Hi {user_name},</p><p>Your ListMate <strong>{term}</strong> {urgency_text}.</p><p>Don\'t lose access to your shared grocery lists! Tap the button below to upgrade your household and keep everything syncing seamlessly.</p><p style="margin:24px 0"><a href="{upgrade_link}" style="background:#5ebe7e;color:#fff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:bold">Upgrade Now</a></p></div>' + unsub_html
    
    return _send_ses_email(to_email, subject, body_text, body_html)


def send_activation_notice(to_email: str, user_name: str, user_id: int = 0) -> bool:
    """Send Day 3 onboarding/activation notice to inactive users."""
    subject = "Simplify your grocery runs with ListMate"
    app_link = "https://grocerlist.app/open?url=/?source=email_activation"

    unsub_link = _get_unsub_link(user_id) if user_id else ""
    unsub_txt = f"\n\nTo unsubscribe from these emails, visit: {unsub_link}" if unsub_link else ""
    unsub_html = f'<p style="font-size: 11px; color: #888; margin-top: 30px; text-align: center;"><a href="{unsub_link}" style="color: #888; text-decoration: underline;">Unsubscribe</a> from marketing emails.</p>' if unsub_link else ""

    body_text = (
        f"Hi {user_name},\n\n"
        f"We noticed you haven't added any items to ListMate yet!\n\n"
        f"Did you know that sharing a real-time grocery list with your partner or housemates makes shopping effortless and can save your household hundreds of dollars a year in forgotten items, duplicate purchases, and impulse buys?\n\n"
        f"When everyone adds items as they run out, whoever visits the store always has the exact, up-to-date list in their pocket.\n\n"
        f"Tap the link below to add your first items and invite your household:\n\n"
        f"{app_link}\n\n"
        f"— The ListMate Team"
    ) + unsub_txt
    
    body_html = (
        f'<div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:20px">'
        f'<h2 style="color:#2c5a2c">👋 Getting started with ListMate</h2>'
        f'<p style="font-size:16px">Hi {user_name},</p>'
        f'<p>We noticed you haven\'t added any items to ListMate yet!</p>'
        f'<p>Did you know that sharing a real-time grocery list with your partner or housemates makes shopping effortless and can <strong>save your household hundreds of dollars a year</strong> in forgotten items, duplicate purchases, and impulse buys?</p>'
        f'<p>When everyone adds items as they run out, whoever visits the store always has the exact, up-to-date list in their pocket.</p>'
        f'<p style="margin:24px 0"><a href="{app_link}" style="background:#5ebe7e;color:#fff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:bold">Open ListMate & Add First Item</a></p>'
        f'</div>'
    ) + unsub_html
    
    return _send_ses_email(to_email, subject, body_text, body_html)


def send_reengagement_notice(to_email: str, user_name: str, user_id: int = 0) -> bool:
    """Send Day 14 re-engagement notice to dormant users."""
    subject = "It's been a while! Streamline your next grocery trip"
    app_link = "https://grocerlist.app/open?url=/?source=email_reengagement"

    unsub_link = _get_unsub_link(user_id) if user_id else ""
    unsub_txt = f"\n\nTo unsubscribe from these emails, visit: {unsub_link}" if unsub_link else ""
    unsub_html = f'<p style="font-size: 11px; color: #888; margin-top: 30px; text-align: center;"><a href="{unsub_link}" style="color: #888; text-decoration: underline;">Unsubscribe</a> from marketing emails.</p>' if unsub_link else ""

    body_text = (
        f"Hi {user_name},\n\n"
        f"It's been a couple of weeks since your last update on ListMate. We wanted to remind you that your shared grocery lists are waiting for you!\n\n"
        f"Sharing a live, store-organized grocery list with your household is one of the easiest ways to smooth out shopping trips and cut down on impulse buys—saving you both time and money.\n\n"
        f"Check out our latest features, including instant store-based aisle organization, to make your next trip seamless.\n\n"
        f"Tap the link below to plan your next grocery trip:\n\n"
        f"{app_link}\n\n"
        f"— The ListMate Team"
    ) + unsub_txt

    body_html = (
        f'<div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:20px">'
        f'<h2 style="color:#2c5a2c">🛒 It\'s been a while!</h2>'
        f'<p style="font-size:16px">Hi {user_name},</p>'
        f'<p>It\'s been a couple of weeks since your last update on ListMate. We wanted to remind you that your shared grocery lists are waiting for you!</p>'
        f'<p>Sharing a live, store-organized grocery list with your household is one of the easiest ways to smooth out shopping trips and cut down on impulse buys—<strong>saving you both time and money</strong>.</p>'
        f'<p>Check out our latest features, including instant store-based aisle organization, to make your next trip seamless.</p>'
        f'<p style="margin:24px 0"><a href="{app_link}" style="background:#5ebe7e;color:#fff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:bold">Plan Your Next Trip</a></p>'
        f'</div>'
    ) + unsub_html
    
    return _send_ses_email(to_email, subject, body_text, body_html)


def send_combined_notice(to_email: str, user_name: str, events: dict, user_id: int = 0) -> bool:
    """Send a combined notice when multiple daily events occur for the same user."""
    app_link = "https://grocerlist.app/open?url=/?source=email_combined"
    upgrade_link = "https://listmate.app/upgrade?source=email_reminder"

    html_sections = []
    text_sections = []

    if 'expiration' in events:
        days = events['expiration']['days_left']
        is_trial = events['expiration']['is_trial']
        term = "trial" if is_trial else "subscription"
        subject = f"Action Required: Your ListMate {term} ends in {days} days" if days > 0 else f"Action Required: Your ListMate {term} ends today"
        urgency = "expires today" if days == 0 else f"expires in {days} days"

        text_sections.append(f"Your ListMate {term} {urgency}. Upgrade to keep syncing your shared grocery lists:\n{upgrade_link}")
        html_sections.append(f'<h3 style="color:#d32f2f">⏳ {term.capitalize()} {urgency}</h3><p>Upgrade to keep syncing your shared grocery lists seamlessly.</p><p><a href="{upgrade_link}" style="background:#5ebe7e;color:#fff;padding:10px 20px;border-radius:8px;text-decoration:none;font-weight:bold">Upgrade Now</a></p>')
    else:
        subject = "Updates from ListMate"

    if 'activation' in events:
        text_sections.append(
            f"You haven't added any items to ListMate yet!\n"
            f"Did you know sharing a real-time grocery list with your household can save hundreds of dollars each year in impulse and duplicate purchases? Tap here to get started:\n{app_link}"
        )
        html_sections.append(
            f'<h3 style="color:#2c5a2c">👋 Getting Started</h3>'
            f'<p>We noticed you haven\'t added any items yet. Sharing a live list with your partner or housemates makes store trips smoother and prevents impulse buys, saving your household both time and money.</p>'
        )

    if 'reengagement' in events:
        text_sections.append(
            f"It's been a while! We wanted to remind you that your shared lists are waiting for you.\n"
            f"Keep your household synced and cut down on extra store runs and duplicate buys:\n{app_link}"
        )
        html_sections.append(
            f'<h3 style="color:#2c5a2c">🛒 It\'s been a while!</h3>'
            f'<p>We wanted to remind you that your shared lists are waiting for you. Stay synced with your household to avoid duplicate buys and make every grocery run effortless.</p>'
        )

    if not ('expiration' in events):
        html_sections.append(f'<p style="margin:24px 0"><a href="{app_link}" style="background:#5ebe7e;color:#fff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:16px;font-weight:bold">Open ListMate</a></p>')

    unsub_link = _get_unsub_link(user_id) if user_id else ""
    unsub_txt = f"\n\nTo unsubscribe from these emails, visit: {unsub_link}" if unsub_link else ""
    unsub_html = f'<p style="font-size: 11px; color: #888; margin-top: 30px; text-align: center;"><a href="{unsub_link}" style="color: #888; text-decoration: underline;">Unsubscribe</a> from marketing emails.</p>' if unsub_link else ""

    body_text = f"Hi {user_name},\n\n" + "\n\n---\n\n".join(text_sections) + "\n\n— The ListMate Team" + unsub_txt
    body_html = f'<div style="font-family:sans-serif;max-width:500px;margin:0 auto;padding:20px"><p style="font-size:16px">Hi {user_name},</p>' + "".join(html_sections) + unsub_html + "</div>"

    return _send_ses_email(to_email, subject, body_text, body_html)


def send_feedback_resolved_email(
    to_email: str,
    user_name: str,
    feedback_title: str,
    feedback_id: int,
    build_number: str,
    resolution_note: str = "",
    request_url: str = "",
    user_id: int = 0
) -> bool:
    """Send a celebratory notification to the user when their feedback/feature request has been addressed in a specific build."""
    name_str = (user_name or "there").split(" ")[0].capitalize()
    clean_title = (feedback_title or "Your feedback").strip()
    build_label = f"Build #{build_number}" if build_number and not str(build_number).lower().startswith("build") else (build_number or "latest build")
    
    if not request_url:
        request_url = f"https://grocerlist.app/open?url=/requests/{feedback_id}"

    subject = f"Your ListMate feedback has been resolved in {build_label}! 🎉"

    res_note_txt = f"\n\nNote from our team:\n{resolution_note}" if resolution_note else ""
    res_note_html = f'<div style="background:#f8faf6;border-left:4px solid #5ebe7e;padding:12px 16px;margin:16px 0;border-radius:4px;"><strong style="color:#2c5a2c;display:block;margin-bottom:4px;">Note from the team:</strong><span style="color:#333;font-size:14px;line-height:1.5;">{resolution_note}</span></div>' if resolution_note else ""

    unsub_link = _get_unsub_link(user_id) if user_id else ""
    unsub_txt = f"\n\nTo unsubscribe from these emails, visit: {unsub_link}" if unsub_link else ""
    unsub_html = f'<p style="font-size: 11px; color: #888; margin-top: 20px; text-align: center;"><a href="{unsub_link}" style="color: #888; text-decoration: underline;">Unsubscribe</a> from feedback updates.</p>' if unsub_link else ""

    body_text = (
        f"Hi {name_str},\n\n"
        f"Great news! You previously gave us feedback:\n"
        f"\"{clean_title}\"\n\n"
        f"We're excited to let you know this has been addressed in {build_label}!"
        f"{res_note_txt}\n\n"
        f"You can view the resolution details and roadmap update here:\n"
        f"{request_url}\n\n"
        f"Thank you for helping us make ListMate better!\n\n"
        f"— The ListMate Team"
    ) + unsub_txt

    body_html = (
        f'<div style="font-family:-apple-system,BlinkMacSystemFont,\'Segoe UI\',Roboto,sans-serif;max-width:520px;margin:0 auto;padding:24px 20px;background:#ffffff;border-radius:12px;border:1px solid #e2e8f0;">'
        f'<div style="text-align:center;margin-bottom:20px;">'
        f'<span style="display:inline-block;background:#eaf8ef;color:#2c5a2c;font-size:12px;font-weight:700;padding:6px 14px;border-radius:20px;letter-spacing:0.5px;text-transform:uppercase;">🎉 You Asked, We Built It</span>'
        f'<h2 style="color:#2c5a2c;margin:12px 0 6px 0;font-size:22px;font-weight:700;">Addressed in {build_label}!</h2>'
        f'</div>'
        f'<p style="font-size:15px;color:#333;line-height:1.5;">Hi {name_str},</p>'
        f'<p style="font-size:15px;color:#333;line-height:1.5;">You previously shared feedback with us:</p>'
        f'<div style="background:#f1f5f9;border-radius:8px;padding:12px 16px;margin:12px 0;font-style:italic;color:#475569;font-size:14px;line-height:1.4;">'
        f'"{clean_title}"'
        f'</div>'
        f'<p style="font-size:15px;color:#333;line-height:1.5;">We wanted to close the loop and let you know that your suggestion has officially shipped in <strong>{build_label}</strong>.</p>'
        f'{res_note_html}'
        f'<div style="text-align:center;margin:28px 0 20px 0;">'
        f'<a href="{request_url}" style="background:#5ebe7e;color:#ffffff;padding:14px 28px;border-radius:10px;text-decoration:none;font-size:15px;font-weight:700;display:inline-block;box-shadow:0 2px 6px rgba(94,190,126,0.3);">View Resolution & Details →</a>'
        f'</div>'
        f'<div style="text-align:center;margin-top:16px;">'
        f'<a href="https://grocerlist.app/open?url=/" style="color:#5ebe7e;text-decoration:none;font-size:13px;font-weight:600;">Open ListMate App</a>'
        f'</div>'
        f'<hr style="border:none;border-top:1px solid #edf2f7;margin:24px 0 16px 0;">'
        f'<p style="font-size:12px;color:#94a3b8;text-align:center;margin:0;">Thank you for being part of the ListMate community and helping us improve.</p>'
        + unsub_html +
        f'</div>'
    )
    
    return _send_ses_email(to_email, subject, body_text, body_html)

