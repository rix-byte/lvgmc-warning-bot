import os
import json
import csv
import time
from datetime import datetime, timezone
import requests
import smtplib
from email.message import EmailMessage


FEED_URL = "https://feeds.meteoalarm.org/api/v1/warnings/feeds-latvia/"

STATE_FILE = "state.json"
HISTORY_CSV = "history.csv"


# ---------------- helpers ----------------

def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"seen": {}, "last_run": ""}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def ensure_csv():
    if os.path.exists(HISTORY_CSV):
        return
    with open(HISTORY_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "timestamp_utc",
            "identifier",
            "level",
            "hazard",
            "event",
            "areas",
            "onset",
            "expires",
            "description",
            "source"
        ])

def append_csv(rows):
    ensure_csv()
    with open(HISTORY_CSV, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for r in rows:
            w.writerow([
                r["timestamp_utc"],
                r["identifier"],
                r["level"],
                r["hazard"],
                r["event"],
                r["areas"],
                r["onset"],
                r["expires"],
                r["description"],
                r["source"]
            ])


# ---------------- notifications ----------------

def send_email(subject, body):
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    pwd = os.getenv("SMTP_PASS")
    to = os.getenv("EMAIL_TO")
    frm = os.getenv("EMAIL_FROM", user)

    if not all([host, port, user, pwd, to, frm]):
        print("Email not configured, skipping.")
        return

    msg = EmailMessage()
    msg["From"] = frm
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)

    with smtplib.SMTP(host, port) as s:
        s.starttls()
        s.login(user, pwd)
        s.send_message(msg)

def telegram_send(text):
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")
    if not token or not chat_id:
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    requests.post(url, json={
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True
    }, timeout=20)


# ---------------- feed ----------------

def fetch_feed():
    r = requests.get(FEED_URL, timeout=30)
    r.raise_for_status()
    return r.json()

def is_marine(text):
    t = text.lower()
    for w in ["jūra", "līcis", "marine", "sea", "coast"]:
        if w in t:
            return True
    return False

def normalize(feed):
    out = []
    items = feed.get("warnings") or feed.get("data") or []
    for i in items:
        level = (i.get("level") or i.get("color") or "").upper()
        identifier = i.get("identifier") or f"{level}-{i.get('event','')}-{i.get('area','')}"
        hazard = i.get("event", "")
        areas = i.get("area", "")
        desc = i.get("description", "")
        if os.getenv("SUPPRESS_MARINE", "1") == "1":
            if is_marine(hazard + " " + areas):
                continue

        out.append({
            "timestamp_utc": utc_now(),
            "identifier": identifier,
            "level": level,
            "hazard": hazard,
            "event": hazard,
            "areas": areas,
            "onset": i.get("onset", ""),
            "expires": i.get("expires", ""),
            "description": desc,
            "source": FEED_URL
        })
    return out


# ---------------- main ----------------

def main():
    state = load_state()
    seen = state.get("seen", {})

    feed = fetch_feed()
    warnings = normalize(feed)

    changed = []
    history_add = []

    for w in warnings:
        fp = json.dumps(w, ensure_ascii=False, sort_keys=True)
        if seen.get(w["identifier"]) != fp:
            seen[w["identifier"]] = fp
            changed.append(w)
            history_add.append(w)

    if history_add:
        append_csv(history_add)

    if changed:
        lines = []
        for w in changed:
            lines.append(f"[{w['level']}] {w['event']} — {w['areas']}")
        send_email("LVGMC brīdinājumu izmaiņas", "\n".join(lines))

        levels = set(x.strip() for x in os.getenv("TG_LEVELS","ORANGE,RED").split(","))
        for w in changed:
            if w["level"] in levels:
                telegram_send(f"⚠️ {w['level']} — {w['event']}\n{w['areas']}")

    state["seen"] = seen
    state["last_run"] = utc_now()
    save_state(state)

    print(f"OK: {len(changed)} changes")

if __name__ == "__main__":
    main()
