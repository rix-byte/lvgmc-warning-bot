import hashlib
import json
import os
import time
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from typing import Any, Dict, List, Optional, Tuple

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

# ---------------- Telegram (required for mobile alerts) ----------------
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")  # numeric string

# ---------------- Behavior toggles ----------------
# Telegram escalation levels (default: orange+red). For testing: yellow,orange,red
TG_LEVELS = os.getenv("TG_LEVELS", "orange,red").lower()

# Suppress sea-only warnings
SUPPRESS_MARINE = os.getenv("SUPPRESS_MARINE", "true").lower() in ("1", "true", "yes", "on")

MARINE_KEYWORDS = [
    "baltijas jūra", "baltijas juras", "jūra", "juras", "jūrā", "jūrās",
    "atklātā jūra", "atklata jura",
    "akvatorija", "akvatōrija",
    "sea",
]

def fetch_feed_json(url: str) -> Optional[dict]:
    last_err = None
    for attempt in range(1, 6):
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": "lvgmc-warning-bot/telegram"})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(min(2 ** attempt, 16))
    print(f"WARNING: feed fetch failed after retries: {last_err}")
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

def pick_lv_info(alert: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for info in alert.get("info", []) or []:
        if info.get("language") == "lv":
            return info
    return None

def parse_level(info: Dict[str, Any]) -> str:
    for p in info.get("parameter", []) or []:
        if p.get("valueName") == "awareness_level":
            parts = [x.strip() for x in (p.get("value") or "").split(";")]
            if len(parts) >= 2:
                return parts[1].lower()
    return ""

def parse_hazard(info: Dict[str, Any]) -> str:
    for p in info.get("parameter", []) or []:
        if p.get("valueName") == "awareness_type":
            parts = [x.strip() for x in (p.get("value") or "").split(";")]
            if len(parts) >= 2:
                return parts[1]
    return ""

def areas_from_info(info: Dict[str, Any]) -> List[str]:
    return [a.get("areaDesc", "").strip() for a in (info.get("area", []) or []) if a.get("areaDesc")]

def is_marine_only(info: Dict[str, Any]) -> bool:
    areas = areas_from_info(info)
    if not areas:
        return False

    def looks_marine(text: str) -> bool:
        t = text.lower()
        return any(k in t for k in MARINE_KEYWORDS)

    return all(looks_marine(a) for a in areas)

def fingerprint_info(info: Dict[str, Any]) -> str:
    payload = json.dumps(info, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

def send_email(subject: str, body: str) -> None:
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS, EMAIL_TO]):
        raise RuntimeError("Missing SMTP_* / EMAIL_* secrets for email.")

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = EMAIL_TO

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.starttls()
        s.login(SMTP_USER, SMTP_PASS)
        s.sendmail(EMAIL_FROM, [EMAIL_TO], msg.as_string())

def telegram_send(text: str) -> None:
    # Non-blocking: log errors but keep run alive so state saves
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("Telegram not configured (missing TG_BOT_TOKEN/TG_CHAT_ID), skipping.")
        return
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TG_CHAT_ID, "text": text, "disable_web_page_preview": True}
        r = requests.post(url, json=payload, timeout=30)
        if r.status_code >= 400:
            print("Telegram error status:", r.status_code)
            print("Telegram error body:", r.text)
    except Exception as e:
        print("Telegram send exception:", e)

def should_escalate_telegram(level: str) -> bool:
    allowed = {x.strip() for x in TG_LEVELS.split(",") if x.strip()}
    return level.lower() in allowed

def format_warning_block(info: Dict[str, Any], level: str, hazard: str) -> str:
    title = info.get("event") or "LVĢMC brīdinājums"
    onset = info.get("onset") or info.get("effective") or "(nav)"
    expires = info.get("expires") or "(nav)"
    areas = ", ".join(areas_from_info(info)) or "(nav norādīts)"
    desc = (info.get("description") or "").strip()
    web = info.get("web") or "https://bridinajumi.meteo.lv/"

    hdr = f"⚠️ {title} [{(level or 'N/A').upper()}{(' — ' + hazard) if hazard else ''}]"
    return "\n".join([
        hdr,
        f"Teritorija: {areas}",
        f"Spēkā: {onset} → {expires}",
        "",
        desc,
        "",
        f"Avots: {web}",
    ]).strip()

def format_grouped_email(changed_blocks: List[str]) -> Tuple[str, str]:
    subject = f"LVĢMC brīdinājumu izmaiņas: {len(changed_blocks)}"
    body = "\n\n---\n\n".join(changed_blocks)
    return subject, body

def format_telegram_alert(info: Dict[str, Any], level: str, hazard: str) -> str:
    title = info.get("event") or "LVĢMC brīdinājums"
    onset = info.get("onset") or info.get("effective") or "-"
    expires = info.get("expires") or "-"
    areas = ", ".join(areas_from_info(info)) or "-"
    return (
        f"⚠️ LVĢMC ALERT ({level.upper() if level else 'N/A'})\n"
        f"{title}\n"
        f"Tips: {hazard or '-'}\n"
        f"Teritorija: {areas}\n"
        f"Spēkā: {onset} → {expires}"
    )

def main() -> None:
    state = load_state()
    seen: Dict[str, str] = state.get("seen", {})

    data = fetch_feed_json(FEED_URL)
    if data is None:
        # feed down: keep state, exit cleanly
        return

    changed_blocks: List[str] = []
    tg_alerts: List[str] = []

    for w in data.get("warnings", []) or []:
        alert = w.get("alert") or {}
        identifier = alert.get("identifier")
        if not identifier:
            continue

        info = pick_lv_info(alert)
        if not info:
            continue

        if SUPPRESS_MARINE and is_marine_only(info):
            continue

        level = parse_level(info)
        hazard = parse_hazard(info)
        fp = fingerprint_info(info)
        prev_fp = seen.get(identifier)

        if prev_fp != fp:
            changed_blocks.append(format_warning_block(info, level, hazard))

            if should_escalate_telegram(level):
                tg_alerts.append(format_telegram_alert(info, level, hazard))

            seen[identifier] = fp

    # One email per run if there are changes
    if changed_blocks:
        subject, body = format_grouped_email(changed_blocks)
        send_email(subject, body)

    # Telegram escalation (non-blocking)
    for msg in tg_alerts:
        telegram_send(msg)

    state["seen"] = seen
    state["updated_at"] = datetime.utcnow().isoformat() + "Z"
    save_state(state)

    print(f"Done. Changed warnings emailed: {len(changed_blocks)}. Telegram alerts sent: {len(tg_alerts)}.")

if __name__ == "__main__":
    main()
