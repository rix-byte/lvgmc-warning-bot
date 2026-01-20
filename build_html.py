import csv
import json
import os
from datetime import datetime, timezone

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
      --bg: #f6f7fb;
      --card: #ffffff;
      --text: #0f172a;
      --muted: #475569;
      --border: #e2e8f0;
      --border2: #edf2f7;
      --shadow: 0 12px 35px rgba(2, 6, 23, 0.10);
      --blue: #2563eb;
      --chip: #f1f5f9;
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
      max-width: 1320px;
      margin: 24px auto 70px;
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
      font-size: 26px;
      letter-spacing: .2px;
    }}

    .sub {{
      color: var(--muted);
      font-size: 13px;
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }}

    .sub a {{
      color: var(--blue);
      text-decoration: none;
      font-weight: 600;
    }}
    .sub a:hover {{ text-decoration: underline; }}

    .card {{
      margin-top: 14px;
      border: 1px solid var(--border);
      border-radius: 16px;
      overflow: hidden;
      background: var(--card);
      box-shadow: var(--shadow);
    }}

    .legend {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      padding: 12px 14px;
      border-bottom: 1px solid var(--border);
      background: #fff;
    }}
    .lg-item {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      color: var(--muted);
    }}
    .lg-dot {{
      width: 12px;
      height: 12px;
      border-radius: 999px;
      border: 1px solid rgba(0,0,0,.15);
    }}
    .dot-yellow {{ background: #f5d90a; }}
    .dot-orange {{ background: #ff8a00; }}
    .dot-red {{ background: #ff3b30; }}

    .toolbar {{
      padding: 12px 14px;
      display: grid;
      gap: 10px;
      grid-template-columns: 1fr;
      border-bottom: 1px solid var(--border);
      position: sticky;
      top: 0;
      z-index: 50;
      background: #ffffffcc;
      backdrop-filter: blur(8px);
    }}

    @media (min-width: 980px) {{
      .toolbar {{
        grid-template-columns: 1.6fr .8fr .9fr .9fr .8fr;
        align-items: center;
      }}
    }}

    input, select {{
      width: 100%;
      padding: 10px 12px;
      border-radius: 12px;
      border: 1px solid var(--border);
      background: #fff;
      color: var(--text);
      outline: none;
    }}

    input::placeholder {{ color: #94a3b8; }}

    .btn {{
      padding: 10px 12px;
      border-radius: 12px;
      border: 1px solid var(--border);
      background: #fff;
      color: var(--text);
      cursor: pointer;
      font-weight: 600;
    }}
    .btn:hover {{ background: #f8fafc; }}

    .btn-primary {{
      border-color: rgba(37, 99, 235, .35);
      color: #1d4ed8;
      background: #eff6ff;
    }}
    .btn-primary:hover {{ background: #dbeafe; }}

    .table-wrap {{
      overflow: auto;
      max-height: 76vh;
      background: #fff;
    }}

    table {{
      width: 100%;
      border-collapse: collapse;
      min-width: 1180px;
    }}

    th, td {{
      padding: 12px 12px;
      border-bottom: 1px solid var(--border2);
      vertical-align: top;
      font-size: 13px;
    }}

    th {{
      position: sticky;
      top: 132px; /* legend (44) + toolbar (~88) */
      z-index: 10;
      background: #fff;
      color: var(--muted);
      font-size: 12px;
      text-align: left;
      letter-spacing: .2px;
      border-bottom: 1px solid var(--border);
    }}

    /* Better row readability */
    tbody tr:hover {{ background: #f8fafc; }}

    td.col-time {{ white-space: nowrap; color: #0f172a; }}

    .badge {{
      display: inline-block;
      padding: 6px 10px;
      border-radius: 999px;
      font-weight: 800;
      font-size: 12px;
      border: 1px solid rgba(0,0,0,.12);
      color: #111;
      background: var(--chip);
    }}
    .YELLOW {{ background: #f5d90a; }}
    .ORANGE {{ background: #ff8a00; }}
    .RED {{ background: #ff3b30; color: #fff; }}

    a {{
      color: var(--blue);
      text-decoration: none;
      font-weight: 600;
    }}
    a:hover {{ text-decoration: underline; }}

    .footer {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      padding: 12px 14px;
      color: var(--muted);
      font-size: 12px;
      border-top: 1px solid var(--border);
      flex-wrap: wrap;
      background: #fff;
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
      background: rgba(2, 6, 23, .55);
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
      background: #ffffff;
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 16px;
      box-shadow: var(--shadow);
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
      color: #0f172a;
    }}

    .modal pre {{
      white-space: pre-wrap;
      word-break: break-word;
      margin: 0;
      font-family: inherit;
      font-size: 13px;
      color: #0f172a;
      line-height: 1.45;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <header>
      <h1>LVGMC brīdinājumu arhīvs (bot)</h1>
      <div class="sub">
        Ģenerēts: <b>{gen}</b>
        <span>•</span>
        <span>Avots: <a href="./history.csv" target="_blank" rel="noreferrer">history.csv</a></span>
        <span>•</span>
        <span id="summary"></span>
      </div>
    </header>

    <div class="card">
      <div class="legend">
        <div class="lg-item"><span class="lg-dot dot-yellow"></span> Dzeltenais — potenciāli bīstams</div>
        <div class="lg-item"><span class="lg-dot dot-orange"></span> Oranžais — bīstams</div>
        <div class="lg-item"><span class="lg-dot dot-red"></span> Sarkanais — ļoti bīstams</div>
      </div>

      <div class="toolbar">
        <input id="q" placeholder="Meklēt (notikums, teritorija, teksts…)" />
        <select id="level">
          <option value="">Visi līmeņi</option>
          <option value="YELLOW">Dzeltenais</option>
          <option value="ORANGE">Oranžais</option>
          <option value="RED">Sarkanais</option>
        </select>
        <select id="hazard"><option value="">Visas parādības</option></select>
        <select id="region"><option value="">Visas teritorijas</option></select>
        <div style="display:flex; gap:10px;">
          <select id="pageSize" style="flex:1;">
            <option value="25">25 / lapa</option>
            <option value="50" selected>50 / lapa</option>
            <option value="100">100 / lapa</option>
            <option value="0">Visi</option>
          </select>
          <button class="btn btn-primary" id="exportBtn" title="Lejupielādēt filtrēto sarakstu CSV">Eksportēt</button>
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
          <button class="btn" id="prev">◀</button>
          <span id="pageInfo">Lapa 1</span>
          <button class="btn" id="next">▶</button>
        </div>
      </div>
    </div>
  </div>

  <!-- Modal -->
  <div class="modal-backdrop" id="modalBg" role="dialog" aria-modal="true">
    <div class="modal">
      <div class="topbar">
        <h3 id="modalTitle">Brīdinājuma teksts</h3>
        <button class="btn" id="modalClose">Aizvērt</button>
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
    region: document.getElementById('region'),
    pageSize: document.getElementById('pageSize'),
    tbody: document.getElementById('tbody'),
    count: document.getElementById('count'),
    prev: document.getElementById('prev'),
    next: document.getElementById('next'),
    pageInfo: document.getElementById('pageInfo'),
    summary: document.getElementById('summary'),
    exportBtn: document.getElementById('exportBtn')
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

  function esc(s) {{
    return String(s || '')
      .replaceAll('&','&amp;')
      .replaceAll('<','&lt;')
      .replaceAll('>','&gt;')
      .replaceAll('"','&quot;');
  }}

  function uniq(arr) {{
    const s = new Set();
    arr.forEach(v => {{ if (v && String(v).trim()) s.add(String(v)); }});
    return Array.from(s).sort((a,b)=>a.localeCompare(b));
  }}

  function initFilters() {{
    uniq(ALL.map(r => r.hazard || '')).forEach(v => {{
      const o = document.createElement('option');
      o.value = v;
      o.textContent = v;
      els.hazard.appendChild(o);
    }});

    uniq(ALL.map(r => r.areas || '')).forEach(v => {{
      const o = document.createElement('option');
      o.value = v;
      o.textContent = v;
      els.region.appendChild(o);
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
    // ISO like: 2026-01-19T12:35:16.781023Z or 2026-01-15T04:00:00+03:00
    if (!s) return '';
    const t = String(s);

    // date + time
    const base = t.replace('T',' ').slice(0,16); // YYYY-MM-DD HH:MM

    if (t.endsWith('Z')) return base + ' UTC';

    const m = t.match(/([+-]\\d\\d:\\d\\d)$/);
    if (m) return base + ' (UTC' + m[1] + ')';

    return base;
  }}

  function fmtPeriod(onset, expires) {{
    const a = fmtTime(onset);
    const b = fmtTime(expires);
    if (!a && !b) return '';
    if (a && b) return a + ' → ' + b;
    return (a || b);
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
    const R = els.region.value.trim();

    return ALL.filter(r => {{
      if (L && String(r.level||'').toUpperCase() !== L) return false;
      if (H && String(r.hazard||'') !== H) return false;
      if (R && String(r.areas||'') !== R) return false;
      if (!textMatch(r, q)) return false;
      return true;
    }});
  }}

  function downloadCSV(rows) {{
    const cols = ['timestamp_utc','level','event','hazard','areas','onset','expires','description','source'];
    const escCSV = (v) => {{
      const s = String(v ?? '');
      if (/[",\\n]/.test(s)) return '"' + s.replaceAll('"','""') + '"';
      return s;
    }};
    const lines = [cols.join(',')].concat(rows.map(r => cols.map(c => escCSV(r[c])).join(',')));
    const blob = new Blob([lines.join('\\n')], {{ type: 'text/csv;charset=utf-8' }});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'filtered_history.csv';
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  }}

  let page = 1;

  function render() {{
    const rows = filtered().sort((a,b)=>(String(b.timestamp_utc||'')).localeCompare(String(a.timestamp_utc||'')));
    const total = rows.length;

    els.summary.textContent = 'Kopā ieraksti: ' + ALL.length + ' • Filtrēti: ' + total;

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
          + '<td><button class="btn" type="button" data-title="' + esc(title) + '" data-text="' + esc(r.description||'') + '">Rādīt</button></td>'
          + '<td>' + src + '</td>'
        + '</tr>'
      );
    }}).join('');

    // Attach listeners after HTML injected
    els.tbody.querySelectorAll('button[data-text]').forEach(btn => {{
      btn.addEventListener('click', () => {{
        openModal(btn.getAttribute('data-title'), btn.getAttribute('data-text'));
      }});
    }});

    els.count.textContent = 'Rādīti ieraksti: ' + shown.length + ' / ' + total;
    els.pageInfo.textContent = 'Lapa ' + page + ' / ' + pages;
    els.prev.disabled = (page <= 1);
    els.next.disabled = (page >= pages);

    // Export uses full filtered list (not just current page)
    els.exportBtn.onclick = () => downloadCSV(rows);
  }}

  function reset() {{ page = 1; render(); }}

  els.q.addEventListener('input', reset);
  els.level.addEventListener('change', reset);
  els.hazard.addEventListener('change', reset);
  els.region.addEventListener('change', reset);
  els.pageSize.addEventListener('change', reset);

  els.prev.addEventListener('click', () => {{ page = Math.max(1, page-1); render(); }});
  els.next.addEventListener('click', () => {{ page = page+1; render(); }});

  initFilters();
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
