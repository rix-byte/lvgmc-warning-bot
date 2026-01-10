import hashlib
import json
import os
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from typing import Any, Dict, Optional, Tuple

import requests

FEED_URL = "https://feeds.meteoalarm.org/api/v1/warnings/feeds-latvia/"
STATE_FILE = "state.json"

# ---------------- Email (required) ----------------
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", EMAIL_TO)

# ---------------- SMS via Twilio (optional) ----------------
TWILIO_SID = os.getenv("TWILIO_SID", "")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN", "")
TWILIO_FROM = os.getenv("TWILIO_FROM", "")
TWILIO_TO = os.getenv("TWILIO_TO", "")

# ---------------- Behavior toggles ----------------
# Default: SMS only for RED.
# If you want to TEST without waiting for RED, set a GitHub secret:
#   SMS_LEVELS=red,orange
# After test, remove the secret or set it back to "red".
SMS_LEVELS = os.getenv("SMS_LEVELS", "red").lower()  # e.g. "red" or "red,orange"


def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"seen": {}}


def save_state(state: Dict[str, Any]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def pick_lv_info(alert: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for info in alert.get("info", []) or []:
        if info.get("language") == "lv":
            return info
    return None


def parse_level(info: Dict[str, Any]) -> str:
    for p in info.get("parameter", []) or []:
        if p.get("valueName") == "awareness_level":
            # Example: "2; yellow; Moderate"
            parts = [x.strip() for x in (p.get("value") or "").split(";")]
            if len(parts) >= 2:
                return parts[1].lower()
    return ""


def fingerprint_info(info: Dict[str, Any]) -> str:
    payload = json.dumps(info, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def send_email(subject: str, body: str) -> None:
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS, EMAIL_TO]):
        raise RuntimeError("Missing SMTP_HOST/SMTP_USER/SMTP_PASS/EMAIL_TO secrets.")

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())


def send_sms_twilio(text: str) -> None:
    # If Twilio secrets aren't set, just skip silently.
    if not all([TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, TWILIO_TO]):
        return

    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json"
    r = requests.post(
        url,
        auth=(TWILIO_SID, TWILIO_TOKEN),
        data={"From": TWILIO_FROM, "To": TWILIO_TO, "Body": text[:1600]},
        timeout=30,
    )
    r.raise_for_status()


def format_email(info: Dict[str, Any], level: str) -> str:
    areas = ", ".join(a.get("areaDesc", "") for a in info.get("area", []) if a.get("areaDesc")) or "(nav norādīts)"
    onset = info.get("onset") or info.get("effective") or "(nav)"
    expires = info.get("expires") or "(nav)"
    desc = (info.get("description") or "").strip()
    web = info.get("web") or "https://bridinajumi.meteo.lv/"

    return f"""\
{info.get('event')}

Līmenis: {level.upper() if level else '(nav)'}
Teritorija: {areas}
Spēkā: {onset} → {expires}

{desc}

Avots:
{web}
""".strip()


def format_sms(info: Dict[str, Any], level: str) -> str:
    areas = ", ".join(a.get("areaDesc", "") for a in info.get("area", []) if a.get("areaDesc")) or "(nav norādīts)"
    onset = info.get("onset") or info.get("effective") or ""
    expires = info.get("expires") or ""
    title = info.get("event") or "LVĢMC brīdinājums"
    return f"{level.upper()} ALERT: {title} | {areas} | {onset}–{expires}"


def should_send_sms(level: str) -> bool:
    if not level:
        return False
    allowed = {x.strip() for x in SMS_LEVELS.split(",") if x.strip()}
    return level.lower() in allowed


def main() -> None:
    state = load_state()
    seen: Dict[str, str] = state.get("seen", {})

    data = requests.get(FEED_URL, timeout=30).json()

    sent_emails = 0
    sent_sms = 0

    for w in data.get("warnings", []) or []:
        alert = w.get("alert") or {}
        identifier = alert.get("identifier")
        if not identifier:
            continue

        info = pick_lv_info(alert)
        if not info:
            continue

        level = parse_level(info)
        fp = fingerprint_info(info)
        prev_fp = seen.get(identifier)

        # Notify ONLY if new/changed
        if prev_fp != fp:
            subject = f"LVĢMC brīdinājums: {info.get('event')}"
            body = format_email(info, level)
            send_email(subject, body)
            sent_emails += 1

            if should_send_sms(level):
                send_sms_twilio(format_sms(info, level))
                sent_sms += 1

            seen[identifier] = fp

    state["seen"] = seen
    state["updated_at"] = datetime.utcnow().isoformat() + "Z"
    save_state(state)

    print(f"Done. Emails sent: {sent_emails}, SMS sent: {sent_sms}")


if __name__ == "__main__":
    main()
