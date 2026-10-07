"""
sigid/server.py — Local web UI served on localhost:8080

Run:  python server.py
Then open http://localhost:8080 in your Android browser.
"""

import base64
import json
import os
import subprocess
import sys
import threading

from flask import Flask, jsonify, redirect, render_template_string, request, send_file

from db import get_conn, get_meta, init_db
from matcher import identify
from scraper import full_scrape, incremental_update

app = Flask(__name__)

# ---------------------------------------------------------------------------
# HTML template — single-file UI, mobile-friendly
# ---------------------------------------------------------------------------

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0">
<title>Signal ID</title>
<style>
  :root {
    --bg: #0d1117; --surface: #161b22; --border: #30363d;
    --accent: #58a6ff; --accent2: #3fb950; --warn: #f78166;
    --text: #e6edf3; --muted: #8b949e;
    --radius: 8px;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { background: var(--bg); color: var(--text); font-family: system-ui, sans-serif;
         font-size: 15px; min-height: 100vh; }
  header { background: var(--surface); border-bottom: 1px solid var(--border);
           padding: 12px 16px; display: flex; align-items: center; gap: 10px; }
  header h1 { font-size: 1.1rem; font-weight: 600; }
  header .badge { background: var(--accent); color: #000; font-size: 0.7rem;
                  padding: 2px 7px; border-radius: 99px; font-weight: 700; }
  .container { padding: 16px; max-width: 700px; margin: 0 auto; }
  .card { background: var(--surface); border: 1px solid var(--border);
          border-radius: var(--radius); padding: 16px; margin-bottom: 16px; }
  .card h2 { font-size: 0.85rem; text-transform: uppercase; letter-spacing: .08em;
             color: var(--muted); margin-bottom: 12px; }
  label { display: block; font-size: 0.85rem; color: var(--muted); margin-bottom: 4px; }
  input[type=text], input[type=number], select {
    width: 100%; background: var(--bg); border: 1px solid var(--border);
    color: var(--text); border-radius: var(--radius); padding: 8px 10px;
    font-size: 0.95rem; margin-bottom: 12px; }
  input:focus, select:focus { outline: none; border-color: var(--accent); }
  .row { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
  button { width: 100%; padding: 10px; border-radius: var(--radius); border: none;
           font-size: 0.95rem; font-weight: 600; cursor: pointer; }
  .btn-primary { background: var(--accent); color: #000; }
  .btn-secondary { background: var(--surface); color: var(--text);
                   border: 1px solid var(--border); }
  .btn-warn { background: var(--warn); color: #000; }
  .upload-area { border: 2px dashed var(--border); border-radius: var(--radius);
                 padding: 20px; text-align: center; color: var(--muted);
                 margin-bottom: 12px; cursor: pointer; transition: border-color .2s; }
  .upload-area.has-file { border-color: var(--accent2); color: var(--accent2); }
  #preview { max-width: 100%; border-radius: var(--radius); margin-top: 8px;
             display: none; }
  .toggle-row { display: flex; align-items: center; justify-content: space-between;
                margin-bottom: 12px; }
  .toggle { position: relative; width: 44px; height: 24px; }
  .toggle input { opacity: 0; width: 0; height: 0; }
  .slider { position: absolute; inset: 0; background: var(--border);
            border-radius: 99px; transition: .2s; }
  .slider:before { content: ""; position: absolute; width: 18px; height: 18px;
                   left: 3px; top: 3px; background: white; border-radius: 50%;
                   transition: .2s; }
  input:checked + .slider { background: var(--accent); }
  input:checked + .slider:before { transform: translateX(20px); }
  #results { display: none; }
  .result-item { background: var(--bg); border: 1px solid var(--border);
                 border-radius: var(--radius); padding: 12px; margin-bottom: 10px; }
  .result-item .name { font-weight: 600; font-size: 1rem; }
  .result-item .score { float: right; font-size: 0.8rem; color: var(--muted); }
  .result-item .meta { font-size: 0.82rem; color: var(--muted); margin-top: 4px; }
  .result-item .desc { font-size: 0.88rem; margin-top: 6px; }
  .result-item a { color: var(--accent); text-decoration: none; font-size: 0.85rem; }
  .score-bar { height: 4px; border-radius: 2px; background: var(--border);
               margin-top: 8px; }
  .score-fill { height: 100%; border-radius: 2px; background: var(--accent); }
  .llm-card { background: #0d1f12; border: 1px solid var(--accent2);
              border-radius: var(--radius); padding: 14px; margin-bottom: 16px; }
  .llm-card h3 { color: var(--accent2); font-size: 0.85rem; margin-bottom: 8px; }
  .conf-high { color: var(--accent2); }
  .conf-medium { color: #e3b341; }
  .conf-low { color: var(--warn); }
  .status { font-size: 0.82rem; color: var(--muted); margin-top: 8px;
            padding: 8px; background: var(--bg); border-radius: var(--radius); }
  .spinner { display: none; text-align: center; padding: 20px; color: var(--muted); }
  .db-stats { font-size: 0.82rem; color: var(--muted); }
  .section-gap { margin-top: 8px; }
  @media (max-width: 420px) { .row { grid-template-columns: 1fr; } }
</style>
</head>
<body>

<header>
  <div>📡</div>
  <h1>Signal ID</h1>
  <span class="badge">LOCAL</span>
</header>

<div class="container">

  <!-- Search card -->
  <div class="card">
    <h2>Identify Signal</h2>

    <div class="row">
      <div>
        <label>Frequency (MHz)</label>
        <input type="number" id="freq" placeholder="e.g. 121.5" step="0.001">
      </div>
      <div>
        <label>Modulation</label>
        <select id="mod">
          <option value="">Unknown</option>
          <option>AM</option><option>FM</option><option>SSB</option>
          <option>FSK</option><option>PSK</option><option>OFDM</option>
          <option>CW</option><option>DIGI</option>
        </select>
      </div>
    </div>

    <div class="row">
      <div>
        <label>Bandwidth (kHz)</label>
        <input type="number" id="bw" placeholder="optional" step="0.1">
      </div>
      <div>
        <label>Name search</label>
        <input type="text" id="name" placeholder="e.g. ACARS">
      </div>
    </div>

    <!-- Waterfall upload -->
    <label>Waterfall screenshot (optional)</label>
    <div class="upload-area" id="dropzone" onclick="document.getElementById('fileInput').click()">
      <span id="dropLabel">Tap to upload waterfall screenshot</span>
      <input type="file" id="fileInput" accept="image/*" style="display:none">
      <img id="preview">
    </div>

    <div class="toggle-row">
      <span style="font-size:0.88rem">Use AI identification (needs internet)</span>
      <label class="toggle">
        <input type="checkbox" id="useLLM">
        <span class="slider"></span>
      </label>
    </div>

    <button class="btn-primary" onclick="runSearch()">🔍 Identify</button>
  </div>

  <!-- Results -->
  <div id="spinner" class="spinner">⏳ Analysing…</div>
  <div id="results">
    <div id="llmResult"></div>
    <div id="dbResults"></div>
  </div>

  <!-- DB Management card -->
  <div class="card">
    <h2>Database</h2>
    <div class="db-stats" id="dbStats">Loading…</div>
    <div class="section-gap"></div>
    <div class="row">
      <button class="btn-secondary" onclick="dbAction('update')">↻ Update DB</button>
      <button class="btn-warn" onclick="dbAction('full')">⚠ Full Rescrape</button>
    </div>
    <div class="status" id="dbStatus" style="display:none"></div>
  </div>

</div>

<script>
let imageB64 = null;

// --- File upload ---
const fileInput = document.getElementById('fileInput');
const dropzone  = document.getElementById('dropzone');
const preview   = document.getElementById('preview');
const dropLabel = document.getElementById('dropLabel');

fileInput.addEventListener('change', e => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = ev => {
    imageB64 = ev.target.result.split(',')[1];
    preview.src = ev.target.result;
    preview.style.display = 'block';
    dropLabel.textContent = file.name;
    dropzone.classList.add('has-file');
  };
  reader.readAsDataURL(file);
});

// drag-and-drop
dropzone.addEventListener('dragover', e => { e.preventDefault(); });
dropzone.addEventListener('drop', e => {
  e.preventDefault();
  const file = e.dataTransfer.files[0];
  if (file) { fileInput.files = e.dataTransfer.files; fileInput.dispatchEvent(new Event('change')); }
});

// --- Search ---
async function runSearch() {
  const freq   = document.getElementById('freq').value;
  const mod    = document.getElementById('mod').value;
  const bw     = document.getElementById('bw').value;
  const name   = document.getElementById('name').value;
  const useLLM = document.getElementById('useLLM').checked;

  document.getElementById('results').style.display = 'none';
  document.getElementById('spinner').style.display = 'block';

  const payload = { freq_mhz: freq || null, modulation: mod || null,
                    bandwidth_khz: bw || null, name_fragment: name || null,
                    use_llm: useLLM, image_b64: imageB64 };

  try {
    const resp = await fetch('/api/identify', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload)
    });
    const data = await resp.json();
    renderResults(data);
  } catch(e) {
    document.getElementById('dbResults').innerHTML =
      `<div class="result-item" style="color:var(--warn)">Error: ${e.message}</div>`;
    document.getElementById('results').style.display = 'block';
  }
  document.getElementById('spinner').style.display = 'none';
}

function renderResults(data) {
  // LLM result
  const llmDiv = document.getElementById('llmResult');
  if (data.llm_result && !data.llm_result.error) {
    const r = data.llm_result;
    const confClass = r.confidence === 'high' ? 'conf-high' :
                      r.confidence === 'medium' ? 'conf-medium' : 'conf-low';
    llmDiv.innerHTML = `
      <div class="llm-card">
        <h3>🤖 AI Identification</h3>
        <div class="name">${r.identification || '—'}
          <span class="${confClass}" style="font-size:0.8rem;font-weight:400;margin-left:8px">
            ${r.confidence || ''} confidence</span>
        </div>
        ${r.modulation ? `<div class="meta">Modulation: ${r.modulation}</div>` : ''}
        ${r.reasoning ? `<div class="desc" style="margin-top:8px">${r.reasoning}</div>` : ''}
        ${r.next_steps ? `<div class="desc" style="margin-top:6px;color:var(--muted)">Next: ${r.next_steps}</div>` : ''}
      </div>`;
  } else {
    llmDiv.innerHTML = '';
  }

  // DB matches
  const dbDiv = document.getElementById('dbResults');
  if (!data.db_matches || data.db_matches.length === 0) {
    dbDiv.innerHTML = '<div class="result-item" style="color:var(--muted)">No DB matches found.</div>';
  } else {
    dbDiv.innerHTML = data.db_matches.map(([score, sig]) => `
      <div class="result-item">
        <span class="score">${score}/100</span>
        <div class="name">${sig.name}</div>
        <div class="meta">
          ${sig.freq_lower_mhz != null ? `${sig.freq_lower_mhz}–${sig.freq_upper_mhz} MHz · ` : ''}
          ${sig.modulation || ''} ${sig.bandwidth_hz ? '· ' + sig.bandwidth_hz : ''}
        </div>
        ${sig.description ? `<div class="desc">${sig.description.substring(0,160)}…</div>` : ''}
        <div class="score-bar"><div class="score-fill" style="width:${score}%"></div></div>
        <div style="margin-top:8px">
          ${sig.url ? `<a href="${sig.url}" target="_blank">→ Signal ID Wiki</a>` : ''}
          ${sig.waterfall_local ? ` · <a href="/media/${encodeURIComponent(sig.waterfall_local.split('/').pop())}" target="_blank">Waterfall</a>` : ''}
          ${sig.audio_local ? ` · <a href="/media/${encodeURIComponent(sig.audio_local.split('/').pop())}" target="_blank">Audio</a>` : ''}
        </div>
      </div>`).join('');
  }

  document.getElementById('results').style.display = 'block';
}

// --- DB management ---
async function dbAction(action) {
  const statusEl = document.getElementById('dbStatus');
  statusEl.style.display = 'block';
  statusEl.textContent = action === 'full' ? 'Full rescrape started (this takes a while)…'
                                           : 'Checking for updates…';
  try {
    const resp = await fetch(`/api/db/${action}`, {method:'POST'});
    const data = await resp.json();
    statusEl.textContent = data.message || 'Done.';
    loadStats();
  } catch(e) {
    statusEl.textContent = 'Error: ' + e.message;
  }
}

async function loadStats() {
  try {
    const resp = await fetch('/api/db/stats');
    const data = await resp.json();
    document.getElementById('dbStats').textContent =
      `${data.signal_count} signals · last updated ${data.last_update || 'never'}`;
  } catch {}
}

loadStats();
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/identify", methods=["POST"])
def api_identify():
    body = request.get_json(force=True)
    freq     = body.get("freq_mhz")
    mod      = body.get("modulation")
    bw       = body.get("bandwidth_khz")
    name     = body.get("name_fragment")
    use_llm  = body.get("use_llm", False)
    img_b64  = body.get("image_b64")

    freq = float(freq) if freq else None
    bw   = float(bw)   if bw   else None

    result = identify(
        freq_mhz=freq,
        modulation=mod,
        bandwidth_khz=bw,
        name_fragment=name,
        image_b64=img_b64,
        use_llm=use_llm,
    )

    # make JSON-serialisable
    result["db_matches"] = [
        [score, dict(sig)] for score, sig in result["db_matches"]
    ]
    return jsonify(result)


@app.route("/api/db/stats")
def api_db_stats():
    conn = get_conn()
    count = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    conn.close()
    last = get_meta("last_update")
    return jsonify({"signal_count": count, "last_update": last})


@app.route("/api/db/update", methods=["POST"])
def api_db_update():
    def run():
        incremental_update()
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"message": "Incremental update started in background."})


@app.route("/api/db/full", methods=["POST"])
def api_db_full():
    def run():
        full_scrape()
    threading.Thread(target=run, daemon=True).start()
    return jsonify({"message": "Full rescrape started in background. Check Termux for progress."})


@app.route("/media/<filename>")
def serve_media(filename):
    media_dir = os.path.join(os.path.dirname(__file__), "media")
    return send_file(os.path.join(media_dir, filename))


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    print("Signal ID server running → http://localhost:8080")
    app.run(host="127.0.0.1", port=8080, debug=False)
