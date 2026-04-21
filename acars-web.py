#!/usr/bin/env python3
"""ACARS web dashboard."""

import re
import csv
import os
import psutil
from datetime import date, datetime
from flask import Flask, Response, jsonify, request, send_file

app = Flask(__name__)
psutil.cpu_percent(interval=None)

LOG_DIR = "/home/pi/acars_logs"
STATS_CSV    = os.path.join(LOG_DIR, "acars_stats.csv")
CURRENT_CSV  = os.path.join(LOG_DIR, "acars_stats_current.csv")
AIRCRAFT_CSV = os.path.join(LOG_DIR, "acars_aircraft.csv")

HEADER_RE = re.compile(
    r'^\[#\d+\s+\(F:([\d.]+)\s+L:([-\d.]+)/([-\d.]+)\s+E:(\d+)\)\s+'
    r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2}:\d{2})\.\d+'
)
FIELD_RE = re.compile(r'^(Mode|Label|Aircraft reg|Flight id|No|Sublabel|Reassembly)\s*:\s*(.+)$')
AC_LINE_RE = re.compile(r'^Aircraft reg:\s*(\S+)\s+Flight id:\s*(\S+)')
LAT_RE = re.compile(r'\bLat:\s*([-\d.]+)')
LON_RE = re.compile(r'\bLon:\s*([-\d.]+)')
ALT_RE = re.compile(r'\bAlt:\s*([-\d.]+)')
HEADING_RE = re.compile(r'True heading:\s*([\d.]+)')


def today_log():
    return os.path.join(LOG_DIR, f"acars_{date.today().isoformat()}.txt")


def parse_messages(log_path, byte_offset=0, max_msgs=50):
    if not os.path.exists(log_path):
        return [], 0
    messages, current = [], None
    with open(log_path, "r", errors="replace") as f:
        f.seek(byte_offset)
        new_offset = byte_offset
        for line in f:
            new_offset += len(line.encode("utf-8", errors="replace"))
            line = line.rstrip("\n")
            m = HEADER_RE.match(line)
            if m:
                if current:
                    messages.append(current)
                freq, level, noise, error, d, t = m.groups()
                day, mon, yr = d.split("/")
                current = {"ts": f"{yr}-{mon}-{day}T{t}Z", "freq": freq,
                           "level": level, "noise": noise, "error": int(error), "body": []}
            elif current is not None:
                ac = AC_LINE_RE.match(line)
                if ac:
                    current["aircraft_reg"] = ac.group(1).strip()
                    current["flight_id"] = ac.group(2).strip()
                else:
                    fm = FIELD_RE.match(line)
                    if fm:
                        key, val = fm.groups()
                        current[key.lower().replace(" ", "_")] = val.strip()
                    elif line and not line.startswith("---") and line not in ("ETB", ""):
                        current["body"].append(line)
        if current:
            messages.append(current)
    return messages[-max_msgs:], new_offset


def load_stats():
    rows = []
    if os.path.exists(STATS_CSV):
        with open(STATS_CSV, newline="") as f:
            for row in csv.DictReader(f):
                rows.append(row)
    if os.path.exists(CURRENT_CSV):
        with open(CURRENT_CSV) as f:
            line = f.readline().strip()
        if line:
            parts = line.split(",")
            if len(parts) == 6:
                row = {"timestamp": parts[0], "date": parts[1], "hour": parts[2],
                       "message_count": parts[3], "error_count": parts[4], "error_rate": parts[5]}
                rows = [r for r in rows if not (r["date"] == row["date"] and r["hour"] == row["hour"])]
                rows.append(row)
    rows.sort(key=lambda r: (r.get("date", ""), r.get("hour", "")))
    return rows


def load_and_update_aircraft():
    """Read historical CSV, merge with today's log, write updated CSV, return list."""
    # Load historical data
    aircraft = {}  # key: (reg, flight_id)
    if os.path.exists(AIRCRAFT_CSV):
        with open(AIRCRAFT_CSV, newline="") as f:
            for row in csv.DictReader(f):
                key = (row["aircraft_reg"], row["flight_id"])
                aircraft[key] = {
                    "aircraft_reg": row["aircraft_reg"],
                    "flight_id": row["flight_id"],
                    "first_seen": row["first_seen"],
                    "last_seen": row["last_seen"],
                    "message_count": int(row["message_count"]),
                }

    # Parse today's log fully
    log = today_log()
    if os.path.exists(log):
        msgs, _ = parse_messages(log, byte_offset=0, max_msgs=999999)
        for m in msgs:
            reg = m.get("aircraft_reg", "").strip()
            fid = m.get("flight_id", "").strip()
            ts  = m.get("ts", "")
            if not reg or not ts:
                continue
            key = (reg, fid)
            if key not in aircraft:
                aircraft[key] = {"aircraft_reg": reg, "flight_id": fid,
                                 "first_seen": ts, "last_seen": ts, "message_count": 0}
            entry = aircraft[key]
            entry["message_count"] += 1
            if ts > entry["last_seen"]:
                entry["last_seen"] = ts
            if ts < entry["first_seen"]:
                entry["first_seen"] = ts

    # Write updated CSV
    rows = sorted(aircraft.values(), key=lambda r: r["last_seen"], reverse=True)
    with open(AIRCRAFT_CSV, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["aircraft_reg","flight_id","first_seen","last_seen","message_count"])
        writer.writeheader()
        writer.writerows(rows)

    return rows


def load_positions():
    """Return ordered track history per aircraft for today. Drops tracks silent >1 hour."""
    log = today_log()
    if not os.path.exists(log):
        return []
    msgs, _ = parse_messages(log, byte_offset=0, max_msgs=999999)
    tracks = {}
    for m in msgs:
        body = "\n".join(m.get("body", []))
        lat_m = LAT_RE.search(body)
        lon_m = LON_RE.search(body)
        if not lat_m or not lon_m:
            continue
        reg = m.get("aircraft_reg", "")
        fid = m.get("flight_id", "")
        ts  = m.get("ts", "")
        key = (reg, fid)
        fix = {"lat": float(lat_m.group(1)), "lon": float(lon_m.group(1)), "ts": ts}
        alt_m = ALT_RE.search(body)
        if alt_m:
            fix["alt"] = int(float(alt_m.group(1)))
        hdg_m = HEADING_RE.search(body)
        if hdg_m:
            fix["heading"] = round(float(hdg_m.group(1)), 1)
        if key not in tracks:
            tracks[key] = {"aircraft_reg": reg, "flight_id": fid, "fixes": []}
        tracks[key]["fixes"].append(fix)

    now = datetime.utcnow()
    result = []
    for t in tracks.values():
        t["fixes"].sort(key=lambda f: f["ts"])
        last_ts = t["fixes"][-1]["ts"]
        try:
            last_dt = datetime.fromisoformat(last_ts.rstrip("Z"))
            if (now - last_dt).total_seconds() > 86400:
                continue
        except ValueError:
            pass
        t["last_ts"] = last_ts
        result.append(t)
    return result


HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ACARS Dashboard</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  :root {
    --bg:#0d1117; --surface:#161b22; --border:#30363d;
    --text:#e6edf3; --muted:#8b949e;
    --green:#3fb950; --red:#f85149; --yellow:#d29922;
    --blue:#58a6ff; --purple:#bc8cff;
  }
  *{box-sizing:border-box;margin:0;padding:0;}
  body{background:var(--bg);color:var(--text);font-family:'Courier New',monospace;font-size:13px;line-height:1.5;}
  header{background:var(--surface);border-bottom:1px solid var(--border);padding:10px 20px;display:flex;align-items:center;gap:12px;}
  header h1{font-size:16px;letter-spacing:2px;color:var(--blue);}
  .dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 6px var(--green);animation:pulse 2s infinite;flex-shrink:0;}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
  .freqs{color:var(--muted);font-size:11px;}
  .updated{margin-left:auto;color:var(--muted);font-size:11px;white-space:nowrap;}
  .sysbar{background:#0d1117;border-bottom:1px solid var(--border);padding:6px 20px;display:flex;gap:28px;align-items:center;flex-wrap:wrap;}
  .stat{display:flex;align-items:center;gap:8px;font-size:11px;}
  .stat-label{color:var(--muted);letter-spacing:.8px;text-transform:uppercase;}
  .stat-value{color:var(--text);font-weight:bold;min-width:38px;}
  .bar-track{width:80px;height:6px;background:var(--border);border-radius:3px;overflow:hidden;}
  .bar-fill{height:100%;border-radius:3px;transition:width .5s ease,background .5s ease;}
  .load-vals{color:var(--text);letter-spacing:.5px;}

  .layout{display:grid;grid-template-columns:1fr 1fr;grid-template-rows:2fr 2fr 1fr;gap:12px;padding:12px;height:calc(100vh - 90px);}
  .panel{background:var(--surface);border:1px solid var(--border);border-radius:6px;display:flex;flex-direction:column;overflow:hidden;min-height:0;}
  .ph{padding:6px 14px;border-bottom:1px solid var(--border);font-size:10px;letter-spacing:1.2px;color:var(--muted);text-transform:uppercase;display:flex;align-items:center;gap:8px;flex-shrink:0;}
  .ph .cnt{margin-left:auto;background:var(--border);border-radius:10px;padding:1px 7px;font-size:10px;}
  .dl-btn{margin-left:8px;background:none;border:1px solid var(--border);color:var(--muted);border-radius:4px;padding:1px 8px;font-size:10px;font-family:inherit;cursor:pointer;letter-spacing:.6px;text-decoration:none;line-height:1.8;}
  .dl-btn:hover{border-color:var(--blue);color:var(--blue);}
  #waterfall{grid-row:1/4;}
  .msg-list{overflow-y:auto;flex:1;}
  .msg{border-bottom:1px solid #21262d;padding:4px 14px;}
  .msg:hover{background:#1c2128;}
  .mh{display:flex;gap:8px;align-items:baseline;flex-wrap:wrap;}
  .ts{color:var(--muted);font-size:11px;}
  .freq{color:var(--purple);font-size:11px;}
  .flight{color:var(--blue);font-weight:bold;}
  .reg{color:var(--text);}
  .lbl{color:var(--yellow);font-size:11px;}
  .e0 .ts::before{content:"● ";color:var(--green);}
  .e1 .ts::before{content:"● ";color:var(--yellow);}
  .e2 .ts::before{content:"● ";color:var(--red);}
  .mbody{color:var(--muted);font-size:11px;margin-top:2px;white-space:pre-wrap;}
  .chart-wrap{flex:1;padding:8px;position:relative;min-height:0;}
  #map{flex:1;min-height:0;}

  /* Aircraft table */
  .ac-list{overflow-y:auto;flex:1;}
  table{width:100%;border-collapse:collapse;font-size:11px;}
  th{color:var(--muted);font-weight:normal;text-align:left;padding:4px 14px;border-bottom:1px solid var(--border);position:sticky;top:0;background:var(--surface);letter-spacing:.6px;}
  td{padding:3px 14px;border-bottom:1px solid #21262d;}
  tr:hover td{background:#1c2128;}
  td.reg{color:var(--blue);font-weight:bold;}
  td.fid{color:var(--purple);}
  td.seen{color:var(--muted);}
  td.cnt{color:var(--green);text-align:right;}
  th.sortable{cursor:pointer;user-select:none;}
  th.sortable:hover{color:var(--text);}
  th.active-sort{color:var(--blue);}

  @media(max-width:860px){
    .layout{grid-template-columns:1fr;grid-template-rows:50vh auto auto auto;height:auto;}
    #waterfall{grid-row:1;}
  }
</style>
</head>
<body>
<header>
  <div class="dot" id="dot"></div>
  <h1>ACARS</h1>
  <span class="freqs">131.550 · 130.025 · 129.125 · 131.475 MHz</span>
  <span class="updated" id="upd">—</span>
</header>
<div class="sysbar">
  <div class="stat">
    <span class="stat-label">CPU</span>
    <span class="stat-value" id="cpu-val">—</span>
    <div class="bar-track"><div class="bar-fill" id="cpu-bar" style="width:0%"></div></div>
  </div>
  <div class="stat">
    <span class="stat-label">Load</span>
    <span class="load-vals" id="load-val">— · — · —</span>
  </div>
  <div class="stat">
    <span class="stat-label">RAM</span>
    <span class="stat-value" id="ram-val">—</span>
    <div class="bar-track"><div class="bar-fill" id="ram-bar" style="width:0%"></div></div>
    <span style="color:var(--muted);font-size:10px" id="ram-detail"></span>
  </div>
</div>
<div class="layout">
  <div class="panel" id="waterfall">
    <div class="ph">Live Messages <span class="cnt" id="cnt">0</span><a class="dl-btn" id="dl-btn" href="/download/messages" download>&#8681; TXT</a></div>
    <div class="msg-list" id="list"></div>
  </div>
  <div class="panel" style="grid-row:1/3">
    <div class="ph">Position Map <span class="cnt" id="pos-cnt">0</span></div>
    <div id="map"></div>
  </div>
  <div class="panel">
    <div class="ph">Aircraft Seen <span class="cnt" id="ac-cnt">0</span></div>
    <div class="ac-list">
      <table>
        <thead><tr><th>Reg</th><th>Flight</th><th class="sortable" id="th-seen" onclick="sortAc('last_seen')">Last Seen <span id="arr-seen">↓</span></th><th class="sortable" id="th-cnt" onclick="sortAc('message_count')" style="text-align:right">Msgs <span id="arr-cnt"></span></th></tr></thead>
        <tbody id="ac-body"></tbody>
      </table>
    </div>
  </div>
</div>
<script>
const map=L.map('map',{zoomControl:true}).setView([54.45,-122.7],7);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',{
  attribution:'© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  maxZoom:18
}).addTo(map);
const TRACK_COLORS=['#58a6ff','#3fb950','#d29922','#bc8cff','#f85149','#79c0ff','#56d364'];
const posState={};
let colorIdx=0,mapFitted=false;

function acColor(key){
  if(!posState[key]) posState[key]={};
  if(!posState[key].color) posState[key].color=TRACK_COLORS[colorIdx++%TRACK_COLORS.length];
  return posState[key].color;
}

function makeIcon(label,heading,color){
  const arrow=heading!=null
    ?`<div style="text-align:center;transform:rotate(${heading}deg);font-size:16px;color:${color};line-height:1;margin-bottom:2px">▲</div>`
    :'';
  return L.divIcon({
    className:'',
    html:`<div style="display:flex;flex-direction:column;align-items:center">${arrow}<div style="background:${color};color:#0d1117;font-family:'Courier New',monospace;font-size:10px;font-weight:bold;padding:2px 5px;border-radius:3px;white-space:nowrap;border:1px solid ${color}">${esc(label)}</div></div>`,
    iconAnchor:[0,heading!=null?22:10]
  });
}

let offset=0,buf=[];
const MAX=200;

let audioCtx=null;
function ping(){
  try{
    if(!audioCtx)audioCtx=new(window.AudioContext||window.webkitAudioContext)();
    const osc=audioCtx.createOscillator(),gain=audioCtx.createGain();
    osc.connect(gain);gain.connect(audioCtx.destination);
    osc.type='sine';
    osc.frequency.setValueAtTime(880,audioCtx.currentTime);
    osc.frequency.exponentialRampToValueAtTime(660,audioCtx.currentTime+0.12);
    gain.gain.setValueAtTime(0.08,audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.001,audioCtx.currentTime+0.18);
    osc.start(audioCtx.currentTime);osc.stop(audioCtx.currentTime+0.18);
  }catch(e){}
}

function barColor(p){return p<50?'#3fb950':p<80?'#d29922':'#f85149';}
function esc(s){return String(s??'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');}

function relTime(iso){
  const diff=Math.floor((Date.now()-new Date(iso))/1000);
  if(diff<60)return diff+'s ago';
  if(diff<3600)return Math.floor(diff/60)+'m ago';
  if(diff<86400)return Math.floor(diff/3600)+'h ago';
  return Math.floor(diff/86400)+'d ago';
}

function render(m){
  const ec=m.error===0?'e0':m.error===1?'e1':'e2';
  const t=(m.ts??'').split('T')[1]??'';
  const body=m.body?.join('\n')??'';
  return`<div class="msg ${ec}">
  <div class="mh">
    <span class="ts">${esc(t)}</span>
    <span class="freq">${esc(m.freq)} MHz</span>
    ${m.flight_id?`<span class="flight">${esc(m.flight_id)}</span>`:''}
    <span class="reg">${esc(m.aircraft_reg??'—')}</span>
    ${m.label?`<span class="lbl">L:${esc(m.label)}</span>`:''}
    ${m.error>0?`<span style="color:var(--red);font-size:10px">ERR:${m.error}</span>`:''}
  </div>
  ${body?`<div class="mbody">${esc(body)}</div>`:''}
</div>`;
}

async function fetchMsgs(){
  try{
    const r=await fetch(`/api/messages?offset=${offset}`);
    if(!r.ok)return;
    const d=await r.json();
    if(d.messages?.length){
      ping();
      buf=[...d.messages,...buf].slice(0,MAX);
      offset=d.offset;
      document.getElementById('list').innerHTML=buf.map(render).join('');
      document.getElementById('cnt').textContent=buf.length;
    }
    document.getElementById('dot').style.cssText='background:var(--green);box-shadow:0 0 6px var(--green)';
  }catch(e){
    document.getElementById('dot').style.cssText='background:var(--red);box-shadow:0 0 6px var(--red)';
  }
}

async function fetchPositions(){
  try{
    const r=await fetch('/api/positions');
    if(!r.ok)return;
    const tracks=await r.json();
    document.getElementById('pos-cnt').textContent=tracks.length;
    const seen=new Set();
    for(const t of tracks){
      const key=(t.aircraft_reg||'?')+'/'+(t.flight_id||'?');
      seen.add(key);
      const color=acColor(key);
      const fixes=t.fixes||[];
      if(!fixes.length)continue;
      const last=fixes[fixes.length-1];
      const latlngs=fixes.map(f=>[f.lat,f.lon]);
      const label=`${t.flight_id||''}${t.flight_id&&t.aircraft_reg?' · ':''}${t.aircraft_reg||''}`;
      const heading=last.heading??null;
      const popup=`<b>${esc(t.flight_id||'—')}</b><br>${esc(t.aircraft_reg||'—')}`
        +(last.alt!=null?'<br>Alt: '+last.alt+' ft':'')
        +(heading!=null?'<br>Hdg: '+heading+'°':'');
      // Track polyline
      if(posState[key]?.polyline){
        posState[key].polyline.setLatLngs(latlngs);
      } else {
        posState[key]=posState[key]||{};
        posState[key].color=color;
        posState[key].polyline=L.polyline(latlngs,{color,weight:2,opacity:0.7,dashArray:'5 5'}).addTo(map);
      }
      // Position marker with bearing arrow
      const icon=makeIcon(label,heading,color);
      if(posState[key]?.marker){
        posState[key].marker.setLatLng([last.lat,last.lon]);
        posState[key].marker.setIcon(icon);
        posState[key].marker.setPopupContent(popup);
      } else {
        posState[key].marker=L.marker([last.lat,last.lon],{icon}).addTo(map).bindPopup(popup);
      }
    }
    // Remove aircraft the server has pruned (>1 hr silent)
    for(const key of Object.keys(posState)){
      if(!seen.has(key)){
        if(posState[key].marker)map.removeLayer(posState[key].marker);
        if(posState[key].polyline)map.removeLayer(posState[key].polyline);
        delete posState[key];
      }
    }
    // Auto-fit only on first load with data
    if(tracks.length&&!mapFitted){
      const allLats=tracks.flatMap(t=>t.fixes.map(f=>f.lat));
      const allLons=tracks.flatMap(t=>t.fixes.map(f=>f.lon));
      map.fitBounds([
        [Math.min(...allLats)-0.5,Math.min(...allLons)-0.5],
        [Math.max(...allLats)+0.5,Math.max(...allLons)+0.5]
      ],{maxZoom:10});
      mapFitted=true;
    }
  }catch(e){}
}

let acRows=[], acSort={col:'last_seen',dir:-1};

function sortAc(col){
  if(acSort.col===col) acSort.dir*=-1;
  else { acSort.col=col; acSort.dir=col==='message_count'?-1:-1; }
  renderAircraft();
}

function renderAircraft(){
  const {col,dir}=acSort;
  const sorted=[...acRows].sort((a,b)=>{
    if(col==='message_count') return dir*(Number(a.message_count)-Number(b.message_count));
    return dir*(a.last_seen<b.last_seen?-1:a.last_seen>b.last_seen?1:0);
  });
  // Update header arrows
  document.getElementById('arr-seen').textContent=col==='last_seen'?(dir===-1?'↓':'↑'):'';
  document.getElementById('arr-cnt').textContent=col==='message_count'?(dir===-1?'↓':'↑'):'';
  document.getElementById('th-seen').className='sortable'+(col==='last_seen'?' active-sort':'');
  document.getElementById('th-cnt').className='sortable'+(col==='message_count'?' active-sort':'');
  document.getElementById('ac-body').innerHTML=sorted.map(a=>`<tr>
    <td class="reg">${esc(a.aircraft_reg||'—')}</td>
    <td class="fid">${esc(a.flight_id||'—')}</td>
    <td class="seen">${esc(relTime(a.last_seen))}</td>
    <td class="cnt">${esc(a.message_count)}</td>
  </tr>`).join('');
}

async function fetchAircraft(){
  try{
    const r=await fetch('/api/aircraft');
    if(!r.ok)return;
    acRows=await r.json();
    document.getElementById('ac-cnt').textContent=acRows.length;
    renderAircraft();
  }catch(e){}
}

async function fetchSystem(){
  try{
    const r=await fetch('/api/system');
    if(!r.ok)return;
    const d=await r.json();
    document.getElementById('cpu-val').textContent=d.cpu_pct.toFixed(1)+'%';
    const cb=document.getElementById('cpu-bar');
    cb.style.width=d.cpu_pct+'%';cb.style.background=barColor(d.cpu_pct);
    document.getElementById('load-val').textContent=`${d.load[0].toFixed(2)} · ${d.load[1].toFixed(2)} · ${d.load[2].toFixed(2)}`;
    document.getElementById('ram-val').textContent=d.ram_pct.toFixed(1)+'%';
    const rb=document.getElementById('ram-bar');
    rb.style.width=d.ram_pct+'%';rb.style.background=barColor(d.ram_pct);
    document.getElementById('ram-detail').textContent=`${d.ram_used_mb}/${d.ram_total_mb} MB`;
  }catch(e){}
}

function tick(){
  document.getElementById('upd').textContent='Updated '+new Date().toLocaleTimeString();
  fetchMsgs();
  fetchSystem();
}

fetchMsgs();fetchPositions();fetchAircraft();fetchSystem();
setInterval(tick,5000);
setInterval(fetchPositions,30000);
setInterval(fetchAircraft,30000);
</script>
</body>
</html>
"""


@app.get("/")
def index():
    return Response(HTML, mimetype="text/html")

@app.get("/api/messages")
def api_messages():
    offset = request.args.get("offset", 0, type=int)
    messages, new_offset = parse_messages(today_log(), byte_offset=offset, max_msgs=50)
    return jsonify({"messages": messages, "offset": new_offset})

@app.get("/api/stats")
def api_stats():
    return jsonify(load_stats())

@app.get("/api/aircraft")
def api_aircraft():
    return jsonify(load_and_update_aircraft())

@app.get("/api/positions")
def api_positions():
    return jsonify(load_positions())

@app.get("/api/system")
def api_system():
    mem = psutil.virtual_memory()
    return jsonify({
        "cpu_pct": psutil.cpu_percent(interval=None),
        "load": list(psutil.getloadavg()),
        "ram_pct": mem.percent,
        "ram_used_mb": round(mem.used / 1024 / 1024),
        "ram_total_mb": round(mem.total / 1024 / 1024),
    })


@app.get("/download/messages")
def download_messages():
    log = today_log()
    if not os.path.exists(log):
        return Response("No log file for today yet.", mimetype="text/plain")
    filename = f"acars_{date.today().isoformat()}.txt"
    return send_file(log, mimetype="text/plain", as_attachment=True, download_name=filename)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080, debug=False)
