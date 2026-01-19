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


def write_history_html():
    import csv
    import os
    import json
    from html import escape
    from datetime import datetime, timezone

    rows = []
    if os.path.exists("history.csv"):
        with open("history.csv", "r", encoding="utf-8", newline="") as f:
            r = csv.DictReader(f)
            for row in r:
                rows.append(row)

    def norm(s: str) -> str:
        return (s or "").strip()

    js_rows = []
    for x in rows:
        js_rows.append({
            "timestamp_utc": norm(x.get("timestamp_utc", "")),
            "identifier": norm(x.get("identifier", "")),
            "event": norm(x.get("event", "")),
            "level": norm(x.get("level", "")),
            "hazard": norm(x.get("hazard", "")),
            "onset": norm(x.get("onset", "")),
            "expires": norm(x.get("expires", "")),
            "areas": norm(x.get("areas", "")),
            "description": norm(x.get("description", "")),
            "source": norm(x.get("source", "")),
        })

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    html = """<!DOCTYPE html>
<html lang="lv">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>LVGMC brīdinājumu arhīvs (bot)</title>
  <style>
    :root {
      --bg: #0b1020;
      --card: #101a33;
      --muted: #95a3c4;
      --text: #e9eeff;
      --border: rgba(255,255,255,.10);
      --shadow: 0 12px 30px rgba(0,0,0,.35);
      --radius: 16px;

      --yellow: #f5d90a;
      --orange: #ff8a00;
      --red: #ff3b30;
      --green: #2ecc71;
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial;
      background: radial-gradient(1200px 600px at 10% -10%, rgba(106, 88, 255, .35), transparent 60%),
                  radial-gradient(900px 500px at 110% 0%, rgba(0, 209, 255, .22), transparent 55%),
                  var(--bg);
      color: var(--text);
    }

    a { color: #a8c7ff; text-decoration: none; }
    a:hover { text-decoration: underline; }

    .wrap {
      max-width: 1200px;
      margin: 28px auto 64px;
      padding: 0 16px;
    }

    header {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 16px;
      margin-bottom: 14px;
      flex-wrap: wrap;
    }

    .title {
      font-size: 22px;
      font-weight: 800;
      letter-spacing: .2px;
      margin: 0;
    }

    .subtitle {
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 13px;
    }

    .card {
      background: rgba(16, 26, 51, .78);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      overflow: hidden;
    }

    .toolbar {
      position: sticky;
      top: 0;
      z-index: 30;
      backdrop-filter: blur(10px);
      background: rgba(11, 16, 32, .75);
      border-bottom: 1px solid var(--border);
    }

    .toolbar-inner {
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
      padding: 14px;
    }

    @media (min-width: 860px) {
      .toolbar-inner {
        grid-template-columns: 1.4fr .7fr .7fr .9fr auto;
        align-items: center;
      }
    }

    input, select, button {
      width: 100%;
      padding: 10px 12px;
      border-radius: 12px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,.04);
      color: var(--text);
      outline: none;
    }
    select { cursor: pointer; }
    button {
      width: auto;
      cursor: pointer;
      white-space: nowrap;
      background: rgba(255,255,255,.07);
    }
    button:hover { background: rgba(255,255,255,.11); }

    .row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }

    .legend {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      align-items: center;
      color: var(--muted);
      font-size: 12px;
    }

    .dot {
      width: 10px; height: 10px; border-radius: 999px;
      display: inline-block; margin-right: 6px;
    }
    .dot.yellow { background: var(--yellow); }
    .dot.orange { background: var(--orange); }
    .dot.red { background: var(--red); }
    .dot.green { background: var(--green); }

    .table-wrap { overflow: auto; max-height: 75vh; }

    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 980px;
    }

    thead th {
      position: sticky;
      top: 0;
      z-index: 20;
      background: rgba(16, 26, 51, .92);
      border-bottom: 1px solid var(--border);
      text-align: left;
      font-size: 12px;
      color: var(--muted);
      letter-spacing: .3px;
      padding: 12px 12px;
    }

    tbody td {
      border-bottom: 1px solid rgba(255,255,255,.06);
      padding: 12px 12px;
      vertical-align: top;
      font-size: 13px;
      line-height: 1.35;
    }
    tbody tr:hover { background: rgba(255,255,255,.03); }

    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 5px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      border: 1px solid rgba(0,0,0,.15);
      color: #111;
    }
    .badge.yellow { background: var(--yellow); }
    .badge.orange { background: var(--orange); }
    .badge.red { background: var(--red); color: #fff; }
    .badge.green { background: var(--green); }

    .muted { color: var(--muted); font-size: 12px; }

    .pill {
      display: inline-block;
      padding: 4px 8px;
      border: 1px solid var(--border);
      border-radius: 999px;
      color: var(--muted);
      font-size: 12px;
      max-width: 420px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    details { max-width: 520px; }
    summary {
      cursor: pointer;
      color: #cfe0ff;
      font-weight: 700;
      list-style: none;
    }
    summary::-webkit-details-marker { display:none; }
    .desc { margin-top: 8px; color: var(--text); white-space: pre-wrap; }

    .footer {
      display: flex;
      justify-content: space-between;
      gap: 10px;
      padding: 12px 14px;
      color: var(--muted);
      font-size: 12px;
      border-top: 1px solid var(--border);
      background: rgba(16, 26, 51, .65);
      flex-wrap: wrap;
    }

    .pager {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
      justify-content: flex-end;
    }
    .pager button { padding: 8px 10px; border-radius: 10px; }
    .count { white-space: nowrap; }
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <h1 class="title">LVGMC brīdinājumu arhīvs (bot)</h1>
        <p class="subtitle">Ģenerēts: <span id="gen"></span></p>
      </div>
      <div class="row">
        <button onclick="downloadFile('history.csv')">⬇️ CSV</button>
        <button onclick="downloadFile('history.html')">⬇️ HTML</button>
      </div>
    </header>

    <div class="card">
      <div class="toolbar">
        <div class="toolbar-inner">
          <input id="q" placeholder="Meklēt (notikums, teritorija, teksts…)" />

          <select id="level">
            <option value="">Visi līmeņi</option>
            <option value="YELLOW">Dzeltenais</option>
            <option value="ORANGE">Oranžais</option>
            <option value="RED">Sarkanais</option>
          </select>

          <select id="hazard">
            <option value="">Visas parādības</option>
          </select>

          <select id="territory">
            <option value="">Visas teritorijas</option>
          </select>

          <div class="row" style="justify-content:flex-end;">
            <select id="pageSize" style="min-width:140px;">
              <option value="25">25 / lapa</option>
              <option value="50" selected>50 / lapa</option>
              <option value="100">100 / lapa</option>
              <option value="0">Visi</option>
            </select>
          </div>

          <div class="legend">
            <span><span class="dot green"></span>nav nepieciešama piesardzība</span>
            <span><span class="dot yellow"></span>potenciāli bīstams</span>
            <span><span class="dot orange"></span>bīstams</span>
            <span><span class="dot red"></span>ļoti bīstams</span>
          </div>
        </div>
      </div>

      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Atklāts (UTC)</th>
              <th>Krāsa</th>
              <th>Notikums</th>
              <th>Parādība</th>
              <th>Teritorija</th>
              <th>Spēkā</th>
              <th>Brīdinājuma teksts</th>
              <th>Avots</th>
            </tr>
          </thead>
          <tbody id="tbody"></tbody>
        </table>
      </div>

      <div class="footer">
        <div class="count" id="count">Rādīti ieraksti: 0 / 0</div>
        <div class="pager">
          <button id="prev">◀</button>
          <span id="pageInfo" class="muted">Lapa 1</span>
          <button id="next">▶</button>
        </div>
      </div>
    </div>
  </div>

<script>
  const GENERATED = """ + json.dumps(generated) + """;
  const ALL = """ + json.dumps(js_rows, ensure_ascii=False) + """;

  document.getElementById('gen').textContent = GENERATED;

  const els = {
    q: document.getElementById('q'),
    level: document.getElementById('level'),
    hazard: document.getElementById('hazard'),
    territory: document.getElementById('territory'),
    pageSize: document.getElementById('pageSize'),
    tbody: document.getElementById('tbody'),
    count: document.getElementById('count'),
    prev: document.getElementById('prev'),
    next: document.getElementById('next'),
    pageInfo: document.getElementById('pageInfo'),
  };

  function uniq(values) {
    return Array.from(new Set(values)).filter(v => v && v.trim().length > 0)
      .sort((a,b) => a.localeCompare(b));
  }

  function initDropdowns() {
    uniq(ALL.map(r => r.hazard)).forEach(h => {
      const o = document.createElement('option');
      o.value = h;
      o.textContent = h;
      els.hazard.appendChild(o);
    });

    uniq(ALL.map(r => r.areas)).forEach(t => {
      const o = document.createElement('option');
      o.value = t;
      o.textContent = t.length > 60 ? (t.slice(0,60) + '…') : t;
      o.title = t;
      els.territory.appendChild(o);
    });
  }

  function badge(level) {
    const L = (level || '').toUpperCase();
    let cls = 'green', txt = 'Zaļais';
    if (L === 'YELLOW') { cls='yellow'; txt='Dzeltenais'; }
    else if (L === 'ORANGE') { cls='orange'; txt='Oranžais'; }
    else if (L === 'RED') { cls='red'; txt='Sarkanais'; }
    return '<span class="badge ' + cls + '">' + txt + '</span>';
  }

  function contains(hay, needle) {
    return (hay || '').toLowerCase().includes((needle || '').toLowerCase());
  }

  function filterRows() {
    const q = els.q.value.trim().toLowerCase


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
