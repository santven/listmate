"""
pii_sanitizer.py — Privacy & PII Sanitizer for ListMate Feedback & Roadmap.
Strips personal names, emails, phone numbers, personal relationships, and chatty banter,
transforming raw user feedback into clean, anonymized public feature requests and bug reports.
"""

import os
import re
import json
import urllib.request
import urllib.error

# Regex patterns for PII detection
EMAIL_REGEX = re.compile(r'[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+', re.IGNORECASE)
PHONE_REGEX = re.compile(r'(\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}')
URL_REGEX = re.compile(r'https?://[^\s]+', re.IGNORECASE)

# Conversational conversational chatter to strip
CHATTER_PATTERNS = [
    re.compile(r'\b(love\s+it|keep\s+it\s+coming|great\s+job|thanks|thank\s+you|cheers|hi\s+team|hey\s+guys|dear\s+support)\b[\.!\s]*', re.IGNORECASE),
    re.compile(r'\b(my\s+name\s+is|this\s+is)\s+[A-Z][a-z]+[\.!\s]*', re.IGNORECASE),
    re.compile(r'\b(my\s+(wife|husband|partner|friend|daughter|son|mom|dad|roommate|colleague))\s+([A-Z][a-z]+)?', re.IGNORECASE),
]

# Common name patterns like "Preethi loves to...", "and Lavanya wants it too"
# Matches standalone capitalized words followed by verbs like wants, loves, likes, thinks, asked, says, told
NAME_VERB_PATTERNS = [
    re.compile(r'\b([A-Z][a-z]+)\s+(loves?|wants?|likes?|thinks?|asked|says?|told|suggested|mentioned|wished)\b', re.IGNORECASE),
    re.compile(r'\b(and|with|for|to)\s+([A-Z][a-z]+)\s+(wants?|loves?|likes?|too|also)\b', re.IGNORECASE),
]


def _get_gemini_key() -> str:
    for var in ["GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_API_KEY"]:
        k = os.environ.get(var, "").strip()
        if k and not k.startswith("dev-") and not k.startswith("secret-"):
            return k

    for path in ["/opt/shared/.env", ".env", "/app/applet/.env"]:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        for var in ["GEMINI_API_KEY=", "GOOGLE_API_KEY=", "GOOGLE_GENAI_API_KEY="]:
                            if line.strip().startswith(var):
                                k = line.split("=", 1)[1].strip().strip("'").strip('"')
                                if k and not k.startswith("dev-") and not k.startswith("secret-"):
                                    return k
            except Exception:
                pass
    return ""


def clean_text_pii_rule_based(text: str, user_name: str = "", user_email: str = "") -> str:
    """Strip emails, phone numbers, known user names, and PII patterns using regex rules."""
    if not text:
        return ""

    cleaned = text

    # Remove email addresses
    cleaned = EMAIL_REGEX.sub("", cleaned)
    # Remove phone numbers
    cleaned = PHONE_REGEX.sub("", cleaned)
    # Remove URLs
    cleaned = URL_REGEX.sub("", cleaned)

    # Remove user name and its parts if provided
    if user_name:
        for part in user_name.split():
            part = part.strip()
            if len(part) >= 2:
                cleaned = re.sub(rf'\b{re.escape(part)}\b', '', cleaned, flags=re.IGNORECASE)

    if user_email:
        username_part = user_email.split('@')[0]
        if len(username_part) >= 3:
            cleaned = re.sub(rf'\b{re.escape(username_part)}\b', '', cleaned, flags=re.IGNORECASE)

    # Remove relational name patterns
    for pat in CHATTER_PATTERNS:
        cleaned = pat.sub("", cleaned)

    # Replace personal name patterns (e.g. "Preethi loves...", "and Lavanya wants...") with generic phrasing
    cleaned = re.sub(r'\b[A-Z][a-z]+\s+loves?\s+to\s+talk\s+about\s+this\b', 'Users frequently discuss this', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b[A-Z][a-z]+\s+wants?\s+it\s+too\b', 'multiple household members requested this', cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r'\b[A-Z][a-z]+\s+(loves?|wants?|likes?|suggested)\b', r'Household member \1', cleaned)

    # Clean up excess whitespace and dangling punctuation
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    cleaned = re.sub(r'\s+([.,!?])', r'\1', cleaned)
    cleaned = cleaned.strip(" .,!?-")
    return cleaned


def _fallback_rule_based_synthesis(raw_message: str, user_name: str = "", feedback_type: str = "feature") -> dict:
    """Generate clean, anonymized public title & description via rule-based heuristics."""
    cleaned = clean_text_pii_rule_based(raw_message, user_name=user_name)
    
    if not cleaned:
        cleaned = "General feature suggestion and improvement."

    # Extract first sentence or chunk as title
    first_clause = re.split(r'[.!?\n]', cleaned)[0].strip()
    if len(first_clause) > 75:
        first_clause = first_clause[:72] + "..."

    title = first_clause.capitalize()
    if not title:
        title = "Feature Enhancement Request" if feedback_type == "feature" else "Bug Report & Stability Fix"

    # Clean description
    desc = cleaned.capitalize()
    if not desc.endswith('.'):
        desc += '.'

    p_type = "bug" if feedback_type == "bug" or "bug" in raw_message.lower() or "fix" in raw_message.lower() else "feature"

    return {
        "public_title": title,
        "public_description": desc,
        "public_type": p_type
    }


def sanitize_and_synthesize_feedback(
    raw_message: str,
    user_name: str = "",
    user_email: str = "",
    feedback_type: str = "feature"
) -> dict:
    """
    Transform raw user feedback into an anonymized, professional public feature request or bug report.
    Uses Gemini API for intelligent sanitization when available, with strict rule-based fallback.
    """
    raw_text = (raw_message or "").strip()
    if not raw_text:
        return {
            "public_title": "Feature Enhancement",
            "public_description": "User requested improvements and capabilities.",
            "public_type": feedback_type or "feature"
        }

    key = _get_gemini_key()
    if key:
        models_to_try = [
            m.strip() for m in os.environ.get("GEMINI_MODEL_NAME", "gemini-3.1-flash-lite,gemini-flash-latest").split(",") if m.strip()
        ]

        system_instruction = (
            "You are a Product Privacy & Feature Request Sanitizer for a smart grocery and meal planning app called ListMate.\n"
            "Your job is to convert raw customer feedback into an anonymized, concise, professional public-facing roadmap item.\n\n"
            "CRITICAL PRIVACY & PII RULES:\n"
            "1. NEVER output any personal names (e.g. 'Preethi', 'Lavanya', 'Venkat', 'John', etc.) or personal relationships ('my wife', 'my friend').\n"
            "2. NEVER output any email addresses, phone numbers, addresses, usernames, or account IDs.\n"
            "3. Anonymize all personal anecdotes and conversational filler ('Love it. Keep it coming.', 'Hey guys').\n"
            "4. Extract the core functionality, improvement, or bug fix requested.\n"
            "5. Produce ONLY a valid JSON object matching this exact schema:\n"
            "{\n"
            '  "public_title": "Concise, professional feature or bug title (under 70 characters, Title Case, NO PII)",\n'
            '  "public_description": "Clear 1-2 sentence description in professional product terms (NO PII)",\n'
            '  "public_type": "feature" | "bug" | "enhancement"\n'
            "}"
        )

        user_content = f"User Feedback:\n\"{raw_text}\"\nUser Type Category: {feedback_type}"

        body = {
            "contents": [
                {
                    "parts": [
                        {"text": system_instruction + "\n\n" + user_content}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json"
            }
        }

        for model_name in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent"
            headers = {
                "Content-Type": "application/json",
                "x-goog-api-key": key
            }
            try:
                req = urllib.request.Request(
                    url,
                    data=json.dumps(body).encode("utf-8"),
                    headers=headers,
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    resp_data = json.loads(resp.read().decode("utf-8"))
                    text = resp_data["candidates"][0]["content"]["parts"][0]["text"].strip()
                    parsed = json.loads(text)

                    # Post-process with rule-based PII scrubber as secondary safety check
                    p_title = clean_text_pii_rule_based(parsed.get("public_title", ""), user_name=user_name, user_email=user_email)
                    p_desc = clean_text_pii_rule_based(parsed.get("public_description", ""), user_name=user_name, user_email=user_email)
                    p_type = parsed.get("public_type", feedback_type).strip().lower()
                    if p_type not in ["feature", "bug", "enhancement"]:
                        p_type = "feature"

                    if p_title:
                        return {
                            "public_title": p_title,
                            "public_description": p_desc or p_title,
                            "public_type": p_type
                        }
            except Exception as e:
                print(f"[PII SANITIZER] Gemini {model_name} error: {e}", flush=True)

    # Fallback to rule-based synthesis
    return _fallback_rule_based_synthesis(raw_text, user_name=user_name, feedback_type=feedback_type)
