import csv
import hashlib
import html
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
HISTORY_CSV = "history.csv"
HISTORY_HTML = "history.html"

# ---------------- Email (required) ----------------
SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASS = os.getenv("SMTP_PASS", "")
EMAIL_TO = os.getenv("EMAIL_TO", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", EMAIL_TO)

# ---------------- Telegram ----------------
TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.getenv("TG_CHAT_ID", "")
TG_LEVELS = os.getenv("TG_LEVELS", "orange,red").lower()

# ---------------- Behavior ----------------
SUPPRESS_MARINE = os.getenv("SUPPRESS_MARINE", "true").lower() in ("1", "true", "yes", "on")

MARINE_KEYWORDS = [
    "baltijas jūra", "baltijas juras", "jūra", "juras", "jūrā", "jūrās",
    "atklātā jūra", "atklata jura", "akvatorija", "akvatōrija", "sea",
]

HISTORY_FIELDS = [
    "timestamp_utc",
    "identifier",
    "event",
    "level",
    "hazard",
    "onset",
    "expires",
    "areas",
    "description",
    "source",
]

LEVEL_TO_BADGE = {
    "yellow": ("Dzeltenais", "yellow"),
    "orange": ("Oranžais", "orange"),
    "red": ("Sarkanais", "red"),
    "green": ("Zaļais", "green"),
    "": ("—", "gray"),
}


# ---------------- Robust IO ----------------

def load_state() -> Dict[str, Any]:
    """
    Always return a valid structure:
      {"seen": {...}, "updated_at": "..."}
    """
    state: Dict[str, Any] = {"seen": {}}
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                # merge/normalize
                state["seen"] = raw.get("seen") if isinstance(raw.get("seen"), dict) else {}
                # keep anything else if you want
        except Exception:
            pass
    return state


def save_state(state: Dict[str, Any]) -> None:
    state["updated_at"] = datetime.utcnow().isoformat() + "Z"
    # Ensure schema
    if "seen" not in state or not isinstance(state["seen"], dict):
        state["seen"] = {}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def ensure_history_csv_header() -> None:
    if os.path.exists(HISTORY_CSV) and os.path.getsize(HISTORY_CSV) > 0:
        return
    with open(HISTORY_CSV, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        w.writeheader()


def append_history(row: Dict[str, str]) -> None:
    ensure_history_csv_header()
    with open(HISTORY_CSV, "a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HISTORY_FIELDS)
        w.writerow({k: row.get(k, "") for k in HISTORY_FIELDS})


def read_history_rows(limit: int = 3000) -> List[Dict[str, str]]:
    ensure_history_csv_header()
    rows: List[Dict[str, str]] = []
    with open(HISTORY_CSV, "r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append({k: row.get(k, "") for k in HISTORY_FIELDS})
    if len(rows) > limit:
        rows = rows[-limit:]
    return rows


# ---------------- Feed fetch with retries ----------------

def fetch_feed_json(url: str) -> Optional[dict]:
    last_err = None
    for attempt in range(1, 6):
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": "lvgmc-warning-bot"})
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(min(2 ** attempt, 16))
    print(f"WARNING: feed fetch failed after retries: {last_err}")
    return None


# ---------------- Alert parsing ----------------

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


# ---------------- Email ----------------

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


# ---------------- Telegram ----------------

def telegram_send(text: str) -> None:
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("Telegram not configured, skipping.")
        return
    try:
        url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
        payload = {"chat_id": TG_CHAT_ID, "text": text, "disable_web_page_preview": True}
        r = requests.post(url, json=payload, timeout=30)
        if r.status_code >= 400:
            print("Telegram error:", r.status_code, r.text)
    except Exception as e:
        print("Telegram exception:", e)


def should_escalate_telegram(level: str) -> bool:
    allowed = {x.strip() for x in TG_LEVELS.split(",") if x.strip()}
    return (level or "").lower() in allowed


# ---------------- Formatting ----------------

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
        f"Spēkā: {onset} → {expires}\n"
        f"Avots: https://bridinajumi.meteo.lv/"
    )


# ---------------- Pretty HTML archive ----------------

def level_badge(level: str) -> Tuple[str, str]:
    lvl = (level or "").lower()
    if lvl in LEVEL_TO_BADGE:
        return LEVEL_TO_BADGE[lvl]
    return ("—", "gray")


def write_history_html() -> None:
    rows = list(reversed(read_history_rows(limit=3000)))  # newest first

    def esc(x: str) -> str:
        return html.escape(x or "")

    tr_list = []
    for i, row in enumerate(rows):
        badge_text, badge_class = level_badge(row.get("level", ""))
        desc = row.get("description", "") or ""
        desc_short = desc[:160] + ("…" if len(desc) > 160 else "")
        desc_id = f"desc_{i}"

        tr_list.append(f"""
<tr data-level="{esc((row.get('level','') or '').lower())}">
  <td class="mono">{esc(row.get("timestamp_utc",""))}</td>
  <td><span class="badge {badge_class}">{esc(badge_text)}</span></td>
  <td class="wrap">{esc(row.get("event",""))}</td>
  <td class="wrap">{esc(row.get("hazard",""))}</td>
  <td class="wrap">{esc(row.get("areas",""))}</td>
  <td class="mono">{esc(row.get("onset",""))} → {esc(row.get("expires",""))}</td>
  <td class="wrap">
    <div class="desc-short">{esc(desc_short)}</div>
    <button class="linkbtn" onclick="toggleDesc('{desc_id}', this)">Rādīt/Slēpt</button>
    <div id="{desc_id}" class="desc-full" style="display:none;">{esc(desc)}</div>
  </td>
  <td class="wrap"><a href="{esc(row.get("source",""))}" target="_blank" rel="noopener">Avots</a></td>
</tr>
""".strip())

    table_html = "\n".join(tr_list) if tr_list else """
<tr><td colspan="8" class="muted">Vēl nav vēstures ierakstu. (Kad parādīsies jauns vai mainīts brīdinājums, tie tiks pierakstīti šeit.)</td></tr>
""".strip()

    html_doc = f"""<!doctype html>
<html lang="lv">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>LVĢMC brīdinājumu arhīvs (bot)</title>
  <style>
    body {{ font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif; margin: 18px; }}
    h1 {{ margin: 0 0 8px 0; font-size: 20px; }}
    .sub {{ color: #666; margin-bottom: 14px; }}
    .controls {{ display: flex; gap: 10px; flex-wrap: wrap; margin: 12px 0 14px 0; }}
    input[type="search"] {{ padding: 10px; min-width: 260px; border: 1px solid #ccc; border-radius: 8px; }}
    select {{ padding: 10px; border: 1px solid #ccc; border-radius: 8px; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th, td {{ border-bottom: 1px solid #eee; padding: 10px; vertical-align: top; }}
    th {{ text-align: left; background: #fafafa; position: sticky; top: 0; z-index: 1; cursor: pointer; }}
    .wrap {{ white-space: normal; }}
    .mono {{ font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace; font-size: 12px; white-space: nowrap; }}
    .badge {{ display:inline-block; padding: 3px 8px; border-radius: 999px; font-size: 12px; font-weight: 600; }}
    .yellow {{ background: #fff3b0; }}
    .orange {{ background: #ffd8a8; }}
    .red {{ background: #ffc9c9; }}
    .green {{ background: #d3f9d8; }}
    .gray {{ background: #e9ecef; }}
    .linkbtn {{ border: none; background: none; color: #1a73e8; padding: 0; cursor: pointer; font-size: 12px; }}
    .desc-full {{ margin-top: 6px; padding: 8px; background: #f8f9fa; border-radius: 8px; }}
    .muted {{ color: #666; }}
    .footer {{ margin-top: 14px; color: #666; font-size: 12px; }}
  </style>
</head>
<body>
  <h1>LVĢMC brīdinājumu arhīvs (bot)</h1>
  <div class="sub">Šī lapa tiek automātiski ģenerēta no <span class="mono">history.csv</span>.</div>

  <div class="controls">
    <input id="q" type="search" placeholder="Meklēt (notikums, teritorija, teksts)..." oninput="applyFilters()"/>
    <select id="lvl" onchange="applyFilters()">
      <option value="">Visi līmeņi</option>
      <option value="yellow">Dzeltenais</option>
      <option value="orange">Oranžais</option>
      <option value="red">Sarkanais</option>
      <option value="green">Zaļais</option>
    </select>
  </div>

  <div class="muted" id="count"></div>

  <table id="t">
    <thead>
      <tr>
        <th onclick="sortTable(0)">Atklāts (UTC)</th>
        <th onclick="sortTable(1)">Krāsa</th>
        <th onclick="sortTable(2)">Notikums</th>
        <th onclick="sortTable(3)">Parādība</th>
        <th onclick="sortTable(4)">Teritorija</th>
        <th onclick="sortTable(5)">Spēkā</th>
        <th>Brīdinājuma teksts</th>
        <th>Avots</th>
      </tr>
    </thead>
    <tbody>
      {table_html}
    </tbody>
  </table>

  <div class="footer">Pēdējā ģenerēšana: {datetime.utcnow().isoformat()}Z</div>

<script>
  function toggleDesc(id, btn) {{
    const el = document.getElementById(id);
    if (!el) return;
    el.style.display = (el.style.display === "none" || el.style.display === "") ? "block" : "none";
  }}

  function applyFilters() {{
    const q = (document.getElementById("q").value || "").toLowerCase();
    const lvl = (document.getElementById("lvl").value || "").toLowerCase();
    const rows = document.querySelectorAll("#t tbody tr");
    let shown = 0;
    for (const r of rows) {{
      const rowLvl = (r.getAttribute("data-level") || "");
      if (lvl && rowLvl !== lvl) {{
        r.style.display = "none";
        continue;
      }}
      const text = r.innerText.toLowerCase();
      const ok = !q || text.includes(q);
      r.style.display = ok ? "" : "none";
      if (ok) shown++;
    }}
    document.getElementById("count").innerText = `Rādīti ieraksti: ${{shown} / ${rows.length}}`;
  }}

  let sortDir = 1;
  function sortTable(col) {{
    const tbody = document.querySelector("#t tbody");
    const rows = Array.from(tbody.querySelectorAll("tr"));
    sortDir = -sortDir;
    rows.sort((a, b) => {{
      const ta = a.children[col].innerText.trim();
      const tb = b.children[col].innerText.trim();
      if (ta < tb) return -1 * sortDir;
      if (ta > tb) return  1 * sortDir;
      return 0;
    }});
    for (const r of rows) tbody.appendChild(r);
    applyFilters();
  }}

  applyFilters();
</script>
</body>
</html>
"""
    with open(HISTORY_HTML, "w", encoding="utf-8") as f:
        f.write(html_doc)


# ---------------- Main ----------------

def main() -> None:
    # Ensure files exist even if there are no changes today
    ensure_history_csv_header()
    write_history_html()

    state = load_state()
    seen: Dict[str, str] = state.get("seen", {})

    data = fetch_feed_json(FEED_URL)
    if data is None:
        # still save state/history so workflow commits can happen
        save_state(state)
        return

    changed_blocks: List[str] = []
    tg_alerts: List[str] = []
    now_utc = datetime.utcnow().isoformat() + "Z"

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

            onset = info.get("onset") or info.get("effective") or ""
            expires = info.get("expires") or ""
            areas = ", ".join(areas_from_info(info))
            desc = (info.get("description") or "").replace("\n", " ").strip()
            web = info.get("web") or "https://bridinajumi.meteo.lv/"

            append_history({
                "timestamp_utc": now_utc,
                "identifier": identifier,
                "event": (info.get("event") or "").replace("\n", " ").strip(),
                "level": (level or "").lower(),
                "hazard": (hazard or "").replace("\n", " ").strip(),
                "onset": (onset or "").replace("\n", " ").strip(),
                "expires": (expires or "").replace("\n", " ").strip(),
                "areas": (areas or "").replace("\n", " ").strip(),
                "description": desc[:2000],
                "source": web,
            })

            seen[identifier] = fp

    if changed_blocks:
        subject, body = format_grouped_email(changed_blocks)
        send_email(subject, body)

    for msg in tg_alerts:
        telegram_send(msg)

    # regenerate HTML with new rows if added
    write_history_html()

    state["seen"] = seen
    save_state(state)

    print(f"Done. Changed warnings emailed: {len(changed_blocks)}. Telegram alerts sent: {len(tg_alerts)}.")
    print(f"History files: {HISTORY_CSV}, {HISTORY_HTML}. State saved: {STATE_FILE}.")


if __name__ == "__main__":
    main()
