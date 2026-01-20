import os
import json
import csv
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Tuple
import requests
import smtplib
from email.message import EmailMessage
from html import escape


FEED_URL = "https://feeds.meteoalarm.org/api/v1/warnings/feeds-latvia/"

STATE_FILE = "state.json"
HISTORY_CSV = "history.csv"
HISTORY_HTML = "history.html"


# ----------------------------
# Helpers
# ----------------------------

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def safe_get(d: Dict[str, Any], path: List[str], default=None):
    cur = d
    for p in path:
        if isinstance(cur, dict) and p in cur:
            cur = cur[p]
        else:
            return default
    return cur

def norm(s: Any) -> str:
    if s is None:
        return ""
    return str(s).strip()

def load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "seen": {},      # key -> fingerprint
        "last_run_utc": ""
    }

def save_state(state: Dict[str, Any]) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def ensure_history_csv() -> None:
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
            "source",
        ])

def append_history(rows: List[Dict[str, str]]) -> None:
    """Append rows to history.csv (caller ensures dedup if needed)."""
    ensure_history_csv()
    with open(HISTORY_CSV, "a", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        for r in rows:
            w.writerow([
                r.get("timestamp_utc", ""),
                r.get("identifier", ""),
                r.get("level", ""),
                r.get("hazard", ""),
                r.get("event", ""),
                r.get("areas", ""),
                r.get("onset", ""),
                r.get("expires", ""),
                r.get("description", ""),
                r.get("source", ""),
            ])

def load_history_keys() -> set:
    """Used for dedup history rows across runs."""
    keys = set()
    if not os.path.exists(HISTORY_CSV):
        return keys
    with open(HISTORY_CSV, "r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            k = (
                norm(row.get("identifier")),
                norm(row.get("level")),
                norm(row.get("hazard")),
                norm(row.get("areas")),
                norm(row.get("onset")),
                norm(row.get("expires")),
            )
            keys.add(k)
    return keys


# ----------------------------
# Feed parsing (Meteoalarm JSON)
# ----------------------------

def fetch_feed_with_retries(url: str, retries: int = 3, timeout: int = 30) -> Dict[str, Any]:
    last_err = None
    for i in range(retries):
        try:
            r = requests.get(url, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            time.sleep(2 * (i + 1))
    raise last_err

def is_marine_warning(hazard: str, event: str, areas: str) -> bool:
    text = f"{hazard} {event} {areas}".lower()
    marine_terms = [
        "marine", "sea", "gulf", "līcis", "jūra", "piekrast", "coast",
        "waves", "wave", "swell", "gusts at sea", "at sea"
    ]
    return any(t in text for t in marine_terms)

def level_from_color(color: str) -> str:
    c = (color or "").strip().lower()
    if c == "red":
        return "RED"
    if c == "orange":
        return "ORANGE"
    if c == "yellow":
        return "YELLOW"
    if c == "green":
        return "GREEN"
    # sometimes empty
    return c.upper() if c else ""

def extract_warnings(feed: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Normalize feed into list of warnings.
    We try to be robust to schema variation.
    """
    warnings = []

    # The Meteoalarm feed often contains a list under "warnings" or "data"
    candidates = []
    for key in ["warnings", "data", "alerts", "items"]:
        v = feed.get(key)
        if isinstance(v, list):
            candidates = v
            break

    # if nothing found, attempt nested
    if not candidates:
        v = safe_get(feed, ["result", "warnings"])
        if isinstance(v, list):
            candidates = v

    for item in candidates:
        if not isinstance(item, dict):
            continue

        # common fields we try
        identifier = norm(item.get("identifier") or item.get("id") or safe_get(item, ["alert", "identifier"]))
        color = norm(item.get("color") or item.get("level") or safe_get(item, ["alert", "level"]))
        level = level_from_color(color) if color.lower() in ("green", "yellow", "orange", "red") else norm(color).upper()

        hazard = norm(item.get("hazard") or item.get("event") or safe_get(item, ["alert", "event"]))
        event = norm(item.get("headline") or item.get("title") or item.get("event") or hazard)

        areas = norm(item.get("area") or item.get("areas") or item.get("region") or safe_get(item, ["alert", "area"]))
        onset = norm(item.get("onset") or item.get("start") or safe_get(item, ["alert", "onset"]))
        expires = norm(item.get("expires") or item.get("end") or safe_get(item, ["alert", "expires"]))
        description = norm(item.get("description") or item.get("text") or safe_get(item, ["alert", "description"]))
        source = norm(item.get("url") or item.get("source") or safe_get(item, ["alert", "web"]) or FEED_URL)

        # if area is list sometimes
        if isinstance(item.get("areas"), list):
            areas = ", ".join([norm(x) for x in item["areas"] if norm(x)])

        # if no identifier, synthesize one
        if not identifier:
            identifier = f"{level}:{hazard}:{areas}:{onset}:{expires}"

        warnings.append({
            "timestamp_utc": utc_now_iso(),
            "identifier": identifier,
            "level": level,
            "hazard": hazard,
            "event": event,
            "areas": areas,
            "onset": onset,
            "expires": expires,
            "description": description,
            "source": source,
        })

    return warnings


# ----------------------------
# Notifications
# ----------------------------

def send_email(subject: str, body: str) -> None:
    host = os.getenv("SMTP_HOST", "")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER", "")
    pwd = os.getenv("SMTP_PASS", "")
    email_to = os.getenv("EMAIL_TO", "")
    email_from = os.getenv("EMAIL_FROM", user)

    if not (host and port and user and pwd and email_to and email_from):
        print("Email not configured (missing SMTP_* or EMAIL_*). Skipping email.")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to
    msg.set_content(body)

    with smtplib.SMTP(host, port) as s:
        s.starttls()
        s.login(user, pwd)
        s.send_message(msg)

def telegram_send(text: str) -> None:
    token = os.getenv("TG_BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN") or ""
    chat_id = os.getenv("TG_CHAT_ID") or os.getenv("TELEGRAM_CHAT_ID") or ""
    if not token or not chat_id:
        print("Telegram not configured (TG_BOT_TOKEN/TG_CHAT_ID missing). Skipping Telegram.")
        return

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": True
    }
    r = requests.post(url, json=payload, timeout=20)
    if r.status_code >= 300:
        print("Telegram error:", r.status_code, r.text)

def format_grouped_email(changed: List[Dict[str, str]]) -> Tuple[str, str]:
    # group by level
    order = {"RED": 0, "ORANGE": 1, "YELLOW": 2, "GREEN": 3, "": 9}
    changed_sorted = sorted(changed, key=lambda x: (order.get(x["level"], 9), x["hazard"], x["areas"]))

    lines = []
    lines.append("LVGMC/Meteoalarm brīdinājumi — jauni vai atjaunināti\n")
    for w in changed_sorted:
        lines.append(f"[{w['level']}] {w['event']}".strip())
        if w["areas"]:
            lines.append(f"Teritorija: {w['areas']}")
        if w["onset"] or w["expires"]:
            lines.append(f"Spēkā: {w['onset']} → {w['expires']}".strip())
        if w["description"]:
            lines.append(w["description"])
        if w["source"]:
            lines.append(f"Avots: {w['source']}")
        lines.append("-" * 50)

    subject = f"LVGMC brīdinājumi: {len(changed)} izmaiņas"
    body = "\n".join(lines)
    return subject, body

def format_telegram_one(w: Dict[str, str]) -> str:
    return (
        f"⚠️ {w['level']} — {w['event']}\n"
        f"📍 {w['areas']}\n"
        f"⏱ {w['onset']} → {w['expires']}\n"
        f"{w['source']}"
    ).strip()


# ----------------------------
# HTML archive (nice UI)
# ----------------------------

def read_history_rows() -> List[Dict[str, str]]:
    rows = []
    if not os.path.exists(HISTORY_CSV):
        return rows
    with open(HISTORY_CSV, "r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            rows.append({k: norm(v) for k, v in row.items()})
    return rows

def write_history_html() -> None:
    rows = read_history_rows()
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # Use JSON to pass all rows to browser
    data_json = json.dumps(rows, ensure_ascii=False)

    html = f"""<!doctype html>
<html lang="lv">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>LVGMC brīdinājumu arhīvs</title>
  <style>
    :root {{
      --bg: #0b1020;
      --card: rgba(16, 26, 51, .82);
      --border: rgba(255,255,255,.12);
      --text: #e9eeff;
      --muted: #a5b0cf;
      --shadow: 0 14px 40px rgba(0,0,0,.35);
      --radius: 16px;

      --yellow: #f5d90a;
      --orange: #ff8a00;
      --red: #ff3b30;
      --green: #2ecc71;
    }}

    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial;
      background:
        radial-gradient(1200px 600px at 10% -10%, rgba(106, 88, 255, .35), transparent 60%),
        radial-gradient(900px 500px at 110% 0%, rgba(0, 209, 255, .20), transparent 55%),
        var(--bg);
      color: var(--text);
    }}

    .wrap {{
      max-width: 1280px;
      margin: 26px auto 64px;
      padding: 0 16px;
    }}

    header {{
      display: flex;
      justify-content: space-between;
      gap: 14px;
      align-items: flex-start;
      flex-wrap: wrap;
      margin-bottom: 14px;
    }}

    h1 {{
      margin: 0;
      font-size: 22px;
      font-weight: 800;
    }}
    .sub {{
      margin-top: 6px;
      color: var(--muted);
      font-size: 13px;
    }}

    .card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      overflow: hidden;
    }}

    .toolbar {{
      position: sticky;
      top: 0;
      z-index: 20;
      background: rgba(11, 16, 32, .72);
      backdrop-filter: blur(10px);
      border-bottom: 1px solid var(--border);
    }}

    .toolbar-inner {{
      display: grid;
      grid-template-columns: 1fr;
      gap: 10px;
      padding: 14px;
    }}
    @media (min-width: 920px) {{
      .toolbar-inner {{
        grid-template-columns: 1.4fr .7fr .7fr .7fr auto;
        align-items: center;
      }}
    }}

    input, select, button {{
      padding: 10px 12px;
      border-radius: 12px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,.05);
      color: var(--text);
      outline: none;
    }}
    button {{
      cursor: pointer;
      white-space: nowrap;
      width: auto;
    }}
    button:hover {{ background: rgba(255,255,255,.10); }}

    .legend {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 12px;
      margin-top: 4px;
    }}
    .dot {{ width: 10px; height: 10px; border-radius: 999px; display:inline-block; margin-right: 6px; }}
    .dot.green {{ background: var(--green); }}
    .dot.yellow {{ background: var(--yellow); }}
    .dot.orange {{ background: var(--orange); }}
    .dot.red {{ background: var(--red); }}

    .table-wrap {{
      overflow: auto;
      max-height: 78vh;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 1100px;
    }}

    thead th {{
      position: sticky;
      top: 0;
      background: rgba(16, 26, 51, .92);
      border-bottom: 1px solid var(--border);
      padding: 12px;
      text-align: left;
      font-size: 12px;
      color: var(--muted);
      letter-spacing: .2px;
    }}

    tbody td {{
      padding: 12px;
      border-bottom: 1px solid rgba(255,255,255,.06);
      vertical-align: top;
      font-size: 13px;
      line-height: 1.35;
    }}
    tbody tr:hover {{ background: rgba(255,255,255,.03); }}

    .badge {{
      display: inline-flex;
      align-items: center;
      padding: 5px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 800;
      border: 1px solid rgba(0,0,0,.2);
      color: #111;
    }}
    .badge.GREEN {{ background: var(--green); }}
    .badge.YELLOW {{ background: var(--yellow); }}
    .badge.ORANGE {{ background: var(--orange); }}
    .badge.RED {{ background: var(--red); color: #fff; }}

    details summary {{
      cursor: pointer;
      color: #bcd4ff;
      font-weight: 700;
    }}
    .desc {{
      margin-top: 8px;
      white-space: pre-wrap;
      color: var(--text);
    }}

    .footer {{
      display:flex;
      justify-content: space-between;
      align-items:center;
      gap: 10px;
      padding: 12px 14px;
      border-top: 1px solid var(--border);
      color: var(--muted);
      font-size: 12px;
      flex-wrap: wrap;
    }}
    .pager {{
      display:flex;
      gap: 8px;
      align-items:center;
      flex-wrap: wrap;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <div>
        <h1>LVGMC brīdinājumu arhīvs (bot)</h1>
        <div class="sub">Ģenerēts: <b>{escape(generated)}</b> • Dati no history.csv</div>
      </div>
      <div style="display:flex; gap:10px; align-items:center;">
        <button onclick="download('history.csv')">⬇️ CSV</button>
        <button onclick="download('history.html')">⬇️ HTML</button>
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

          <select id="pageSize">
            <option value="25">25 / lapa</option>
            <option value="50" selected>50 / lapa</option>
            <option value="100">100 / lapa</option>
            <option value="0">Visi</option>
          </select>

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
        <div id="count">Rādīti ieraksti: 0 / 0</div>
        <div class="pager">
          <button id="prev">◀</button>
          <span id="pageInfo">Lapa 1</span>
          <button id="next">▶</button>
        </div>
      </div>
    </div>
  </div>

<script>
  const ALL = {data_json};

  const els = {{
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
  }};

  function uniq(arr) {{
    return Array.from(new Set(arr.filter(v => v && v.trim().length > 0))).sort((a,b)=>a.localeCompare(b));
  }}

  function initFilters() {{
    uniq(ALL.map(r => r.hazard)).forEach(v => {{
      const o = document.createElement('option');
      o.value = v;
      o.textContent = v;
      els.hazard.appendChild(o);
    }});

    uniq(ALL.map(r => r.areas)).forEach(v => {{
      const o = document.createElement('option');
      o.value = v;
      o.textContent = v.length > 80 ? v.slice(0,80)+'…' : v;
      o.title = v;
      els.territory.appendChild(o);
    }});
  }}

  function matchText(r, q) {{
    if (!q) return true;
    const hay = (r.event+' '+r.hazard+' '+r.areas+' '+r.description).toLowerCase();
    return hay.includes(q.toLowerCase());
  }}

  function matchesFilters(r) {{
    const q = els.q.value.trim();
    const L = els.level.value.trim();
    const H = els.hazard.value.trim();
    const T = els.territory.value.trim();

    if (L && (r.level||'').toUpperCase() !== L) return false;
    if (H && (r.hazard||'') !== H) return false;
    if (T && (r.areas||'') !== T) return false;
    if (!matchText(r, q)) return false;
    return true;
  }}

  function badge(level) {{
    const L = (level||'').toUpperCase();
    const label = L === 'YELLOW' ? 'Dzeltenais' : (L === 'ORANGE' ? 'Oranžais' : (L === 'RED' ? 'Sarkanais' : ''));
    return `<span class="badge ${L}">${label || L}</span>`;
  }}

  let page = 1;

  function render() {{
    const filtered = ALL.filter(matchesFilters);

    // newest first
    filtered.sort((a,b) => (b.timestamp_utc||'').localeCompare(a.timestamp_utc||''));

    const ps = parseInt(els.pageSize.value, 10);
    const total = filtered.length;

    let start = 0, end = total, pages = 1;
    if (ps > 0) {{
      pages = Math.max(1, Math.ceil(total / ps));
      page = Math.min(page, pages);
      start = (page - 1) * ps;
      end = Math.min(total, start + ps);
    }} else {{
      page = 1;
      pages = 1;
    }}

    const shown = filtered.slice(start, end);

    els.tbody.innerHTML = shown.map(r => `
      <tr>
        <td>${r.timestamp_utc || ''}</td>
        <td>${badge(r.level)}</td>
        <td>${r.event || ''}</td>
        <td>${r.hazard || ''}</td>
        <td>${r.areas || ''}</td>
        <td>${(r.onset||'') + ' → ' + (r.expires||'')}</td>
        <td>
          <details>
            <summary>Rādīt</summary>
            <div class="desc">${(r.description||'').replaceAll('<','&lt;').replaceAll('>','&gt;')}</div>
          </details>
        </td>
        <td>${r.source ? `<a href="${r.source}" target="_blank" rel="noreferrer">Avots</a>` : ''}</td>
      </tr>
    `).join('');

    els.count.textContent = `Rādīti ieraksti: ${shown.length} / ${total}`;
    els.pageInfo.textContent = `Lapa ${page} / ${pages}`;

    els.prev.disabled = (page <= 1);
    els.next.disabled = (page >= pages);
  }}

  function resetAndRender() {{
    page = 1;
    render();
  }}

  ['input','change'].forEach(ev => {{
    els.q.addEventListener(ev, resetAndRender);
    els.level.addEventListener(ev, resetAndRender);
    els.hazard.addEventListener(ev, resetAndRender);
    els.territory.addEventListener(ev, resetAndRender);
    els.pageSize.addEventListener(ev, resetAndRender);
  }});

  els.prev.addEventListener('click', () => {{ page = Math.max(1, page-1); render(); }});
  els.next.addEventListener('click', () => {{ page = page+1; render(); }});

  function download(file) {{
    const a = document.createElement('a');
    a.href = file;
    a.download = file;
    document.body.appendChild(a);
    a.click();
    a.remove();
  }}
  window.download = download;

  initFilters();
  render();
</script>
</body>
</html>
"""

    with open(HISTORY_HTML, "w", encoding="utf-8") as f:
        f.write(html)


# ----------------------------
# Main
# ----------------------------

def fingerprint(w: Dict[str, str]) -> str:
    # used to detect changes
    return json.dumps({
        "level": w.get("level", ""),
        "hazard": w.get("hazard", ""),
        "event": w.get("event", ""),
        "areas": w.get("areas", ""),
        "onset": w.get("onset", ""),
        "expires": w.get("expires", ""),
        "description": w.get("description", ""),
        "source": w.get("source", ""),
    }, ensure_ascii=False, sort_keys=True)

def main():
    suppress_marine = (os.getenv("SUPPRESS_MARINE", "1").strip() != "0")

    # Telegram levels to notify (default ORANGE+RED)
    tg_levels_raw = os.getenv("TG_LEVELS", "ORANGE,RED")
    tg_levels = set([x.strip().upper() for x in tg_levels_raw.split(",") if x.strip()])

    state = load_state()
    seen = state.get("seen", {}) if isinstance(state.get("seen"), dict) else {}

    feed = fetch_feed_with_retries(FEED_URL, retries=3, timeout=30)
    warnings = extract_warnings(feed)

    # suppress marine
    filtered = []
    for w in warnings:
        if suppress_marine and is_marine_warning(w["hazard"], w["event"], w["areas"]):
            continue
        filtered.append(w)

    changed = []
    history_add = []
    history_keys = load_history_keys()

    for w in filtered:
        key = w["identifier"]
        fp = fingerprint(w)

        if seen.get(key) != fp:
            changed.append(w)
            seen[key] = fp

        hk = (w["identifier"], w["level"], w["hazard"], w["areas"], w["onset"], w["expires"])
        if hk not in history_keys:
            history_keys.add(hk)
            history_add.append(w)

    # Write history CSV + HTML always (even if no changes)
    if history_add:
        append_history(history_add)

    write_history_html()

    # Notify ONLY on changes
    if changed:
        subject, body = format_grouped_email(changed)
        send_email(subject, body)

        # Telegram for certain levels
        for w in changed:
            if w["level"].upper() in tg_levels:
                telegram_send(format_telegram_one(w))

    state["seen"] = seen
    state["last_run_utc"] = utc_now_iso()
    save_state(state)

    print(f"Total warnings: {len(warnings)}; after filters: {len(filtered)}; changed: {len(changed)}; history_added: {len(history_add)}")

if __name__ == "__main__":
    main()
