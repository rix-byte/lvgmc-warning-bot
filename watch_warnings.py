import hashlib
import json
import os
from datetime import datetime
import requests
import smtplib
from email.mime.text import MIMEText

FEED_URL = "https://feeds.meteoalarm.org/api/v1/warnings/feeds-latvia/"
STATE_FILE = "state.json"

# ---- Email ----
SMTP_HOST = os.getenv("SMTP_HOST")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASS = os.getenv("SMTP_PASS")
EMAIL_TO = os.getenv("EMAIL_TO")
EMAIL_FROM = os.getenv("EMAIL_FROM", EMAIL_TO)

# ---- SMS (Twilio, only if RED) ----
TWILIO_SID = os.getenv("TWILIO_SID")
TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
TWILIO_FROM = os.getenv("TWILIO_FROM")
TWILIO_TO = os.getenv("TWILIO_TO")

def load_state():
    if os.path.exists(STATE_FILE):
        return json.load(open(STATE_FILE, "r", encoding="utf-8"))
    return {"seen": {}}

def save_state(state):
    json.dump(state, open(STATE_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=2)

def pick_lv_info(alert):
    for info in alert.get("info", []):
        if info.get("language") == "lv":
            return info
    return None

def parse_level(info):
    for p in info.get("parameter", []):
        if p["valueName"] == "awareness_level":
            return p["value"].split(";")[1].strip().lower()
    return ""

def fingerprint(info):
    return hashlib.sha256(
        json.dumps(info, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()

def send_email(subject, body):
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())

def send_sms(text):
    if not all([TWILIO_SID, TWILIO_TOKEN, TWILIO_FROM, TWILIO_TO]):
        return

    url = f"https://api.twilio.com/2010-04-01/Accounts/{TWILIO_SID}/Messages.json"
    requests.post(
        url,
        auth=(TWILIO_SID, TWILIO_TOKEN),
        data={"From": TWILIO_FROM, "To": TWILIO_TO, "Body": text[:1600]},
        timeout=30,
    ).raise_for_status()

def format_email(info, level):
    areas = ", ".join(a["areaDesc"] for a in info.get("area", []))
    return f"""
{info.get("event")}

Līmenis: {level.upper()}
Teritorija: {areas}
Spēkā: {info.get("onset")} → {info.get("expires")}

{info.get("description")}

Avots:
{info.get("web")}
""".strip()

def format_sms(info):
    areas = ", ".join(a["areaDesc"] for a in info.get("area", []))
    return f"RED ALERT: {info.get('event')} | {areas} | {info.get('onset')}–{info.get('expires')}"

def main():
    state = load_state()
    seen = state["seen"]

    data = requests.get(FEED_URL, timeout=30).json()

    for w in data.get("warnings", []):
        alert = w["alert"]
        info = pick_lv_info(alert)
        if not info:
            continue

        fid = fingerprint(info)
        prev = seen.get(alert["identifier"])

        if prev != fid:
            level = parse_level(info)
            email_body = format_email(info, level)

            send_email(
                f"LVĢMC brīdinājums: {info.get('event')}",
                email_body,
            )

            if level in ("red", "orange"):
    send_sms(format_sms(info))

            seen[alert["identifier"]] = fid

    state["seen"] = seen
    state["updated_at"] = datetime.utcnow().isoformat() + "Z"
    save_state(state)

if __name__ == "__main__":
    main()
