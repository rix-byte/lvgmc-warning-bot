import hashlib
import json
import os
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

# ---------------- Meta WhatsApp Cloud API (required for WA escalation) ----------------
META_WA_TOKEN = os.getenv("META_WA_TOKEN", "")
META_WA_PHONE_ID = os.getenv("META_WA_PHONE_ID", "")
META_WA_TEMPLATE_NAME = os.getenv("META_WA_TEMPLATE_NAME", "weather_alert")
META_WA_TO = os.getenv("META_WA_TO", "")  # +371...

# ---------------- Behavior toggles ----------------
# Escalate WhatsApp for these levels (default: orange+red)
WA_LEVELS = os.getenv("WA_LEVELS", "yellow,orange,red").lower()

# Suppress sea-only warnings
SUPPRESS_MARINE = os.getenv("SUPPRESS_MARINE", "true").lower() in ("1", "true", "yes", "on")

MARINE_KEYWORDS = [
    "baltijas jūra", "baltijas juras", "jūra", "juras", "jūrā", "jūrās",
    "atklātā jūra", "atklata jura",
    "akvatorija", "akvatōrija",
    "sea",
]

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
            parts = [x.strip() for x in (p.get("value") or "").split(";")]
            if len(parts) >= 2:
                return parts[1].lower()  # yellow/orange/red
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
    """
    Suppress only if ALL area descriptions look marine/sea.
    This avoids hiding land warnings that mention coast.
    """
    areas = areas_from_info(info)
    if not areas:
        return False

    def looks_marine(text: str) -> bool:
        t = text.lower()
        return any(k in t for k in MARINE_KEYWORDS)

    flags = [looks_marine(a) for a in areas]
    return all(flags)

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

def should_escalate_whatsapp(level: str) -> bool:
    if not level:
        return False
    allowed = {x.strip() for x in WA_LEVELS.split(",") if x.strip()}
    return level.lower() in allowed

def meta_whatsapp_send_template(level: str, hazard: str, area: str, onset: str, expires: str) -> None:
    """
    Sends WhatsApp template message via Meta Cloud API.
    Template body must have variables:
      {{1}} level, {{2}} hazard, {{3}} area, {{4}} onset, {{5}} expires
    """
    if not all([META_WA_TOKEN, META_WA_PHONE_ID, META_WA_TEMPLATE_NAME, META_WA_TO]):
        raise RuntimeError("Missing META_WA_* secrets needed for WhatsApp escalation.")

    url = f"https://graph.facebook.com/v20.0/{META_WA_PHONE_ID}/messages"
    headers = {
        "Authorization": f"Bearer {META_WA_TOKEN}",
        "Content-Type": "application/json",
    }

    payload = {
        "messaging_product": "whatsapp",
        "to": META_WA_TO.lstrip("+"),  # Meta expects digits only in many examples; works reliably this way
        "type": "template",
        "template": {
            "name": META_WA_TEMPLATE_NAME,
            "language": {"code": "en_US"},
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": (level or "").upper()},
                        {"type": "text", "text": hazard or "-"},
                        {"type": "text", "text": area or "-"},
                        {"type": "text", "text": onset or "-"},
                        {"type": "text", "text": expires or "-"},
                    ],
                }
            ],
        },
    }

    r = requests.post(url, headers=headers, json=payload, timeout=30)
    r.raise_for_status()

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

def main() -> None:
    state = load_state()
    seen: Dict[str, str] = state.get("seen", {})

    data = requests.get(FEED_URL, timeout=30).json()

    changed_blocks: List[str] = []
    wa_escalations: List[Tuple[str, str, str, str, str]] = []  # level, hazard, area, onset, expires

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

            if should_escalate_whatsapp(level):
                areas = ", ".join(areas_from_info(info)) or "-"
                onset = info.get("onset") or info.get("effective") or "-"
                expires = info.get("expires") or "-"
                wa_escalations.append((level, hazard or "-", areas, onset, expires))

            seen[identifier] = fp

    # ONE email per run if there are changes
    if changed_blocks:
        subject, body = format_grouped_email(changed_blocks)
        send_email(subject, body)

    # WhatsApp escalation for ORANGE/RED (or as configured)
    for level, hazard, area, onset, expires in wa_escalations:
        meta_whatsapp_send_template(level, hazard, area, onset, expires)

    state["seen"] = seen
    state["updated_at"] = datetime.utcnow().isoformat() + "Z"
    save_state(state)

    print(f"Done. Changed warnings emailed: {len(changed_blocks)}. WhatsApp escalations sent: {len(wa_escalations)}.")

if __name__ == "__main__":
    main()
