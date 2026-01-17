import hashlib
import json
import os
import time
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional

import requests

FEED_URL = "https://feeds.meteoalarm.org/api/v1/warnings/feeds-latvia/"
STATE_FILE = "state.json"

# ================= Email =================
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", EMAIL_TO)

# ================= Meta WhatsApp =================
META_WA_TOKEN = os.getenv("META_WA_TOKEN", "")
META_WA_PHONE_ID = os.getenv("META_WA_PHONE_ID", "")
META_WA_TEMPLATE_NAME = os.getenv("META_WA_TEMPLATE_NAME", "")
META_WA_LANG = os.getenv("META_WA_LANG", "en_US")
META_WA_TO = os.getenv("META_WA_TO", "")

# ================= Behavior =================
WA_LEVELS = os.getenv("WA_LEVELS", "orange,red").lower()
SUPPRESS_MARINE = os.getenv("SUPPRESS_MARINE", "true").lower() in ("1", "true", "yes")

MARINE_KEYWORDS = [
    "jūra", "juras", "jūrā", "jūrās",
    "baltijas jūra", "baltijas juras",
    "sea", "offshore"
]

# ================= Utilities =================
def fetch_feed() -> Optional[dict]:
    for attempt in range(5):
        try:
            r = requests.get(FEED_URL, timeout=30)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"Feed fetch failed (attempt {attempt+1}): {e}")
            time.sleep(min(2 ** attempt, 15))
    return None

def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"seen": {}}

def save_state(state: Dict[str, Any]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def fingerprint(info: Dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(info, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()

def send_email(subject: str, body: str) -> None:
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS, EMAIL_TO]):
        print("Email not configured, skipping email send.")
        return

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())

def meta_whatsapp_send(level, hazard, area, onset, expires):
    if not all([META_WA_TOKEN, META_WA_PHONE_ID, META_WA_TEMPLATE_NAME, META_WA_TO]):
        print("Meta WhatsApp not fully configured, skipping.")
        return

    to_digits = "".join(c for c in META_WA_TO if c.isdigit())
    url = f"https://graph.facebook.com/v20.0/{META_WA_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {META_WA_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": to_digits,
        "type": "template",
        "template": {
            "name": META_WA_TEMPLATE_NAME,
            "language": {"code": META_WA_LANG},
            "components": [{
                "type": "body",
                "parameters": [
                    {"type": "text", "text": level.upper()},
                    {"type": "text", "text": hazard or "-"},
                    {"type": "text", "text": area or "-"},
                    {"type": "text", "text": onset or "-"},
                    {"type": "text", "text": expires or "-"},
                ]
            }]
        }
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
        if r.status_code >= 400:
            print("Meta WA error:", r.status_code, r.text)
    except Exception as e:
        print("Meta WA exception:", e)

# ================= Main =================
def main():
    state = load_state()
    seen = state.get("seen", {})

    data = fetch_feed()
    if not data:
        print("Feed unavailable, exiting cleanly.")
        save_state(state)
        return

    changed = []
    wa_levels = {l.strip() for l in WA_LEVELS.split(",") if l.strip()}

    for w in data.get("warnings", []):
        alert = w.get("alert", {})
        identifier = alert.get("identifier")
        if not identifier:
            continue

        info = next((i for i in alert.get("info", []) if i.get("language") == "lv"), None)
        if not info:
            continue

        areas = [a.get("areaDesc", "") for a in info.get("area", [])]
        if SUPPRESS_MARINE and areas and all(any(k in a.lower() for k in MARINE_KEYWORDS) for a in areas):
            continue

        level = ""
        hazard = ""
        for p in info.get("parameter", []):
            if p.get("valueName") == "awareness_level":
                level = p.get("value", "").split(";")[-1].lower()
            if p.get("valueName") == "awareness_type":
                hazard = p.get("value", "").split(";")[-1]

        fp = fingerprint(info)
        if seen.get(identifier) == fp:
            continue

        seen[identifier] = fp

        onset = info.get("onset", "-")
        expires = info.get("expires", "-")
        area_txt = ", ".join(areas) or "-"

        changed.append(
            f"⚠️ {info.get('event','Brīdinājums')}\n"
            f"Līmenis: {level.upper()}\n"
            f"Tips: {hazard}\n"
            f"Teritorija: {area_txt}\n"
            f"Spēkā: {onset} → {expires}\n\n"
            f"{info.get('description','')}"
        )

        if level in wa_levels:
            meta_whatsapp_send(level, hazard, area_txt, onset, expires)

    if changed:
        send_email(
            f"LVĢMC brīdinājumu izmaiņas: {len(changed)}",
            "\n\n---\n\n".join(changed)
        )

    state["seen"] = seen
    state["updated_at"] = datetime.utcnow().isoformat() + "Z"
    save_state(state)

    print("Run completed successfully.")

if __name__ == "__main__":
    main()
