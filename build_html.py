import csv
import json
import os
from datetime import datetime, timezone
from html import escape as hesc

HISTORY_CSV = "history.csv"
OUT_HTML = os.path.join("docs", "index.html")


def read_rows():
    if not os.path.exists(HISTORY_CSV):
        return []
    with open(HISTORY_CSV, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main():
    rows = read_rows()
    gen = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    data_json = json.dumps(rows, ensure_ascii=False)

    os.makedirs("docs", exist_ok=True)

    html = f"""<!doctype html>
<html lang="lv">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>LVGMC brīdinājumu arhīvs</title>
  <style>
    :root {{
      --bg: #0b1020;
      --panel: rgba(16,26,51,.82);
      --panel2: rgba(11,16,32,.75);
      --border: rgba(255,255,255,.12);
      --border2: rgba(255,255,255,.07);
      --text: #e9eeff;
      --muted: #a5b0cf;
      --accent: #bcd4ff;
    }}

    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      line-height: 1.35;
    }}

    .wrap {{
      max-width: 1280px;
      margin: 24px auto 60px;
      padding: 0 16px;
    }}

    header {{
      display: flex;
      flex-direction: column;
      gap: 6px;
      margin-bottom: 14px;
    }}

    h1 {{
      margin: 0;
      font-size: 24px;
      letter-spacing: .2px;
    }}

    .sub {{
      color: var(--muted);
      font-size: 13px;
    }}

    .card {{
      margin-top: 14px;
      border: 1px solid var(--border);
      border-radius: 16px;
      overflow: hidden;
      background: var(--panel);
      box-shadow: 0 20px 60px rgba(0,0,0,.25);
    }}

    .toolbar {{
      padding: 12px;
      display: grid;
      gap: 10px;
      grid-template-columns: 1fr;
      border-bottom: 1px solid var(--border);
      position: sticky;
      top: 0;
      z-index: 50;
      background: var(--panel2);
      backdrop-filter: blur(10px);
    }}

    @media (min-width: 900px) {{
      .toolbar {{
        grid-template-columns: 1.6fr .8fr .8fr .7fr;
        align-items: center;
      }}
    }}

    input, select {{
      width: 100%;
      padding: 10px 12px;
      border-radius: 12px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,.05);
      color: var(--text);
      outline: none;
    }}

    input::placeholder {{ color: rgba(233,238,255,.55); }}

    .table-wrap {{
      overflow: auto;
      max-height: 78vh;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 1150px;
    }}

    th, td {{
      padding: 12px;
      border-bottom: 1px solid var(--border2);
      vertical-align: top;
      font-size: 13px;
    }}

    th {{
      position: sticky;
      top: 56px; /* sits below toolbar */
      z-index: 10;
      background: rgba(16,26,51,.92);
      color: var(--muted);
      font-size: 12px;
      text-align: left;
      letter-spacing: .2px;
    }}

    /* Make first column slightly narrower */
    td.col-time {{ white-space: nowrap; }}

    .badge {{
      display: inline-block;
      padding: 5px 10px;
      border-radius: 999px;
      font-weight: 800;
      font-size: 12px;
      border: 1px solid rgba(0,0,0,.25);
      color: #111;
    }}
    .YELLOW {{ background: #f5d90a; }}
    .ORANGE {{ background: #ff8a00; }}
    .RED {{ background: #ff3b30; color: #fff; }}

    a {{
      color: #9bb8ff;
      text-decoration: none;
    }}
    a:hover {{ text-decoration: underline; }}

    button {{
      padding: 8px 10px;
      border-radius: 10px;
      border: 1px solid var(--border);
      background: rgba(255,255,255,.05);
      color: var(--text);
      cursor: pointer;
    }}
    button:hover {{ background: rgba(255,255,255,.10); }}
    button:disabled {{ opacity: .45; cursor: default; }}

    .footer {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      padding: 12px 14px;
      color: var(--muted);
      font-size: 12px;
      border-top: 1px solid var(--border);
      flex-wrap: wrap;
      background: rgba(11,16,32,.55);
    }}

    .pager {{
      display: flex;
      gap: 8px;
      align-items: center;
      flex-wrap: wrap;
    }}

    /* Modal */
    .modal-backdrop {{
      position: fixed;
      inset: 0;
      background: rgba(0,0,0,.6);
      display: none;
      align-items: center;
      justify-content: center;
      padding: 18px;
      z-index: 9999;
    }}

    .modal {{
      width: min(900px, 96vw);
      max-height: 85vh;
      overflow: auto;
      background: #0f1933;
      border: 1px solid rgba(255,255,255,.14);
      border-radius: 16px;
      padding: 16px;
      box-shadow: 0 20px 70px rgba(0,0,0,.45);
    }}

    .modal .topbar {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
      margin-bottom: 10px;
    }}

    .modal h3 {{
      margin: 0;
      font-size: 16px;
      color: var(--accent);
    }}

    .modal pre {{
      white-space: pre-wrap;
      word-break: break-word;
      margin: 0;
      font-family: inherit;
      font-size: 13px;
      color: var(--text);
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>LVGMC brīdinājumu arhīvs (bot)</h1>
      <div class="sub">Ģenerēts: <b>{hesc(gen)}</b> • Avots: history.csv</div>
    </header>

    <div class="card">
      <div class="toolbar">
        <input id="q" placeholder="Meklēt (notikums, teritorija, teksts…)" />
        <select id="level">
          <option value="">Visi līmeņi</option>
          <option value="YELLOW">Dzeltenais</option>
          <option value="ORANGE">Oranžais</option>
          <option value="RED">Sarkanais</option>
        </select>
        <select id="hazard"><option value="">Visas parādības</option></select>
        <select id="pageSize">
          <option value="25">25 / lapa</option>
          <option value="50" selected>50 / lapa</option>
          <option value="100">100 / lapa</option>
          <option value="0">Visi</option>
        </select>
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
              <th>Teksts</th>
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

  <!-- Modal -->
  <div class="modal-backdrop" id="modalBg" role="dialog" aria-modal="true">
    <div class="modal">
      <div class="topbar">
        <h3 id="modalTitle">Brīdinājuma teksts</h3>
        <button id="modalClose">Aizvērt</button>
      </div>
      <pre id="modalBody"></pre>
    </div>
  </div>

<script>
  const ALL = {data_json};

  const els = {{
    q: document.getElementById('q'),
    level: document.getElementById('level'),
    hazard: document.getElementById('hazard'),
    pageSize: document.getElementById('pageSize'),
    tbody: document.getElementById('tbody'),
    count: document.getElementById('count'),
    prev: document.getElementById('prev'),
    next: document.getElementById('next'),
    pageInfo: document.getElementById('pageInfo'),
  }};

  // modal refs
  const modalBg = document.getElementById('modalBg');
  const modalClose = document.getElementById('modalClose');
  const modalTitle = document.getElementById('modalTitle');
  const modalBody = document.getElementById('modalBody');

  function openModal(title, text) {{
    modalTitle.textContent = title || 'Brīdinājuma teksts';
    modalBody.textContent = text || '';
    modalBg.style.display = 'flex';
  }}
  function closeModal() {{
    modalBg.style.display = 'none';
  }}
  modalClose.addEventListener('click', closeModal);
  modalBg.addEventListener('click', (e) => {{ if (e.target === modalBg) closeModal(); }});
  document.addEventListener('keydown', (e) => {{ if (e.key === 'Escape') closeModal(); }});

  function uniq(arr) {{
    const s = new Set();
    arr.forEach(v => {{ if (v && String(v).trim()) s.add(String(v)); }});
    return Array.from(s).sort((a,b)=>a.localeCompare(b));
  }}

  function initHazards() {{
    uniq(ALL.map(r => r.hazard || '')).forEach(v => {{
      const o = document.createElement('option');
      o.value = v;
      o.textContent = v;
      els.hazard.appendChild(o);
    }});
  }}

  function badge(level) {{
    const L = String(level || '').toUpperCase();
    let label = L;
    if (L === 'YELLOW') label = 'Dzeltenais';
    else if (L === 'ORANGE') label = 'Oranžais';
    else if (L === 'RED') label = 'Sarkanais';
    return '<span class="badge ' + L + '">' + label + '</span>';
  }}

  function fmtTime(s) {{
    // Inputs like:
    // 2026-01-19T12:35:16.781023Z
    // 2026-01-15T04:00:00+03:00
    if (!s) return '';
    const t = String(s);
    let out = t.replace('T', ' ');
    out = out.slice(0, 16); // YYYY-MM-DD HH:MM
    if (t.endsWith('Z')) {{
      out += ' UTC';
    }} else {{
      const m = t.match(/([+-]\\d\\d:\\d\\d)$/);
      if (m) out += ' UTC' + m[1];
    }}
    return out;
  }}

  function fmtPeriod(onset, expires) {{
    const a = fmtTime(onset);
    const b = fmtTime(expires);
    if (!a && !b) return '';
    if (a && b) return a + ' → ' + b;
    return (a || b);
  }}

  function esc(s) {{
    return String(s || '')
      .replaceAll('&','&amp;')
      .replaceAll('<','&lt;')
      .replaceAll('>','&gt;')
      .replaceAll('"','&quot;');
  }}

  function textMatch(r, q) {{
    if (!q) return true;
    const hay = ((r.event||'')+' '+(r.hazard||'')+' '+(r.areas||'')+' '+(r.description||'')).toLowerCase();
    return hay.includes(q.toLowerCase());
  }}

  function filtered() {{
    const q = els.q.value.trim();
    const L = els.level.value.trim();
    const H = els.hazard.value.trim();
    return ALL.filter(r => {{
      if (L && String(r.level||'').toUpperCase() !== L) return false;
      if (H && String(r.hazard||'') !== H) return false;
      if (!textMatch(r, q)) return false;
      return true;
    }});
  }}

  let page = 1;

  function render() {{
    const rows = filtered().sort((a,b)=>(String(b.timestamp_utc||'')).localeCompare(String(a.timestamp_utc||'')));
    const total = rows.length;

    const ps = parseInt(els.pageSize.value, 10);
    let pages = 1, start = 0, end = total;
    if (ps > 0) {{
      pages = Math.max(1, Math.ceil(total / ps));
      page = Math.min(page, pages);
      start = (page - 1) * ps;
      end = Math.min(total, start + ps);
    }} else {{
      page = 1; pages = 1;
    }}

    const shown = rows.slice(start, end);

    els.tbody.innerHTML = shown.map(r => {{
      const discovered = fmtTime(r.timestamp_utc || '');
      const per = fmtPeriod(r.onset, r.expires);
      const title = (String(r.level||'') + ' — ' + String(r.event||'')).trim();
      const src = r.source ? '<a href="' + esc(r.source) + '" target="_blank" rel="noreferrer">Avots</a>' : '';

      return (
        '<tr>'
          + '<td class="col-time">' + esc(discovered) + '</td>'
          + '<td>' + badge(r.level||'') + '</td>'
          + '<td>' + esc(r.event||'') + '</td>'
          + '<td>' + esc(r.hazard||'') + '</td>'
          + '<td>' + esc(r.areas||'') + '</td>'
          + '<td class="col-time">' + esc(per) + '</td>'
          + '<td>'
              + '<button type="button" class="btnText" data-title="' + esc(title) + '" data-text="' + esc(r.description||'') + '">Rādīt</button>'
            + '</td>'
          + '<td>' + src + '</td>'
        + '</tr>'
      );
    }}).join('');

    // Attach listeners after HTML injected
    document.querySelectorAll('.btnText').forEach(btn => {{
      btn.addEventListener('click', () => {{
        openModal(btn.getAttribute('data-title'), btn.getAttribute('data-text'));
      }});
    }});

    els.count.textContent = 'Rādīti ieraksti: ' + shown.length + ' / ' + total;
    els.pageInfo.textContent = 'Lapa ' + page + ' / ' + pages;
    els.prev.disabled = (page <= 1);
    els.next.disabled = (page >= pages);
  }}

  function reset() {{ page = 1; render(); }}

  els.q.addEventListener('input', reset);
  els.level.addEventListener('change', reset);
  els.hazard.addEventListener('change', reset);
  els.pageSize.addEventListener('change', reset);

  els.prev.addEventListener('click', () => {{ page = Math.max(1, page-1); render(); }});
  els.next.addEventListener('click', () => {{ page = page+1; render(); }});

  initHazards();
  render();
</script>
</body>
</html>
"""

    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"Wrote {OUT_HTML} (rows: {len(rows)})")


if __name__ == "__main__":
    main()
