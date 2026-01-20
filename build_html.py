import csv, json, os
from datetime import datetime, timezone
from html import escape

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
    body {{ margin:0; font-family:system-ui,-apple-system,Segoe UI,Roboto,Arial; background:#0b1020; color:#e9eeff; }}
    .wrap {{ max-width:1200px; margin:24px auto 60px; padding:0 16px; }}
    h1 {{ margin:0; font-size:22px; }}
    .sub {{ color:#a5b0cf; margin-top:6px; font-size:13px; }}
    .card {{ margin-top:14px; border:1px solid rgba(255,255,255,.12); border-radius:16px; overflow:hidden; background:rgba(16,26,51,.82); }}
    .toolbar {{ padding:12px; display:grid; gap:10px; grid-template-columns: 1fr; border-bottom:1px solid rgba(255,255,255,.12); position:sticky; top:0; background:rgba(11,16,32,.75); backdrop-filter: blur(10px); }}
    @media(min-width:900px){{ .toolbar {{ grid-template-columns: 1.4fr .7fr .7fr .7fr; align-items:center; }} }}
    input,select {{ padding:10px 12px; border-radius:12px; border:1px solid rgba(255,255,255,.12); background:rgba(255,255,255,.05); color:#e9eeff; }}
    .table-wrap {{ overflow:auto; max-height:78vh; }}
    table {{ width:100%; border-collapse:collapse; min-width:1100px; }}
    th,td {{ padding:12px; border-bottom:1px solid rgba(255,255,255,.07); vertical-align:top; font-size:13px; }}
    th {{ position:sticky; top:0; background:rgba(16,26,51,.92); color:#a5b0cf; font-size:12px; text-align:left; }}
    .badge {{ display:inline-block; padding:5px 10px; border-radius:999px; font-weight:800; font-size:12px; border:1px solid rgba(0,0,0,.2); color:#111; }}
    .YELLOW {{ background:#f5d90a; }}
    .ORANGE {{ background:#ff8a00; }}
    .RED {{ background:#ff3b30; color:#fff; }}
    details summary {{ cursor:pointer; color:#bcd4ff; font-weight:700; }}
    .footer {{ display:flex; justify-content:space-between; gap:10px; padding:12px 14px; color:#a5b0cf; font-size:12px; border-top:1px solid rgba(255,255,255,.12); flex-wrap:wrap; }}
    .pager {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; }}
    button {{ padding:8px 10px; border-radius:10px; border:1px solid rgba(255,255,255,.12); background:rgba(255,255,255,.05); color:#e9eeff; cursor:pointer; }}
    button:hover {{ background:rgba(255,255,255,.10); }}
  </style>
</head>
<body>
<div class="wrap">
  <h1>LVGMC brīdinājumu arhīvs (bot)</h1>
  <div class="sub">Ģenerēts: <b>{escape(gen)}</b> • Avots: history.csv</div>

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

  function uniq(arr) {{
    const s = new Set();
    arr.forEach(v => {{ if (v && v.trim()) s.add(v); }});
    return Array.from(s).sort((a,b)=>a.localeCompare(b));
  }}

  function initHazards() {{
    uniq(ALL.map(r => r.hazard || '')).forEach(v => {{
      const o = document.createElement('option');
      o.value = v; o.textContent = v;
      els.hazard.appendChild(o);
    }});
  }}

  function badge(level) {{
    const L = (level || '').toUpperCase();
    let label = L;
    if (L === 'YELLOW') label = 'Dzeltenais';
    else if (L === 'ORANGE') label = 'Oranžais';
    else if (L === 'RED') label = 'Sarkanais';
    return '<span class="badge ' + L + '">' + label + '</span>';
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
      if (L && (r.level||'').toUpperCase() !== L) return false;
      if (H && (r.hazard||'') !== H) return false;
      if (!textMatch(r, q)) return false;
      return true;
    }});
  }}

  function esc(s) {{
    return (s||'').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
  }}

  let page = 1;

  function render() {{
    const rows = filtered().sort((a,b)=>(b.timestamp_utc||'').localeCompare(a.timestamp_utc||''));
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
      const src = r.source ? '<a href="'+esc(r.source)+'" target="_blank" rel="noreferrer">Avots</a>' : '';
      const per = (r.onset||'') + ' → ' + (r.expires||'');
      return (
        '<tr>'
        + '<td>' + esc(r.timestamp_utc||'') + '</td>'
        + '<td>' + badge(r.level||'') + '</td>'
        + '<td>' + esc(r.event||'') + '</td>'
        + '<td>' + esc(r.hazard||'') + '</td>'
        + '<td>' + esc(r.areas||'') + '</td>'
        + '<td>' + esc(per) + '</td>'
        + '<td><details><summary>Rādīt</summary><div class="desc">' + esc(r.description||'') + '</div></details></td>'
        + '<td>' + src + '</td>'
        + '</tr>'
      );
    }}).join('');

    els.count.textContent = 'Rādīti ieraksti: ' + shown.length + ' / ' + total;
    els.pageInfo.textContent = 'Lapa ' + page + ' / ' + pages;
    els.prev.disabled = (page <= 1);
    els.next.disabled = (page >= pages);
  }}

  function reset() {{ page = 1; render(); }}

  ['input','change'].forEach(ev => {{
    els.q.addEventListener(ev, reset);
    els.level.addEventListener(ev, reset);
    els.hazard.addEventListener(ev, reset);
    els.pageSize.addEventListener(ev, reset);
  }});

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
