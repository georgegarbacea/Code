"use strict";
const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
let catalog = null, state = {}, status = {}, ws = null, frame = null, lastBeat = 0;
const SWATCHES = ["#ff3b30", "#ff8a3d", "#ffd60a", "#34c759", "#00c7be", "#0a84ff", "#5e5ce6", "#bf5af2", "#ff2d92", "#ffffff"];

function toast(msg) {
  const t = $("#toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.remove("show"), 1800);
}

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, Object.assign({ credentials: "same-origin" }, opt));
  if (r.status === 401) { showLogin(); throw new Error("auth"); }
  return r.json();
}

function send(action, value) {
  if (ws && ws.readyState === 1) ws.send(JSON.stringify({ action, value }));
  else api("/api/cmd", { action, value }).then((r) => { if (r.state) applyState(r.state); }).catch(() => {});
}

// ------------------------------------------------------------------ login
function showLogin() { $("#login").classList.remove("hidden"); setTimeout(() => $("#pin").focus(), 100); }
async function doLogin(pin) {
  const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pin }), credentials: "same-origin" });
  const j = await r.json();
  if (j.ok) { $("#login").classList.add("hidden"); start(); }
  else $("#loginErr").textContent = j.error || "Eroare";
}
$("#loginBtn").onclick = () => doLogin($("#pin").value);
$("#pin").addEventListener("keydown", (e) => { if (e.key === "Enter") doLogin($("#pin").value); });

// ------------------------------------------------------------------ UI build
function card(label, sub, active, onclick, cat) {
  const b = document.createElement("button");
  b.className = "card" + (active ? " active" : "");
  b.innerHTML = `${label}${sub ? `<small>${sub}</small>` : ""}${cat ? `<i class="cat ${cat}"></i>` : ""}`;
  b.onclick = onclick;
  return b;
}

function grad(stops) { return `linear-gradient(135deg, ${stops.join(",")})`; }

function render() {
  if (!catalog) return;
  $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.mode === uiMode()));
  $$(".pane").forEach((p) => p.classList.toggle("active", p.id === "pane-" + uiMode()));
  const pe = $("#palettes"); pe.innerHTML = "";
  const auto = document.createElement("button");
  auto.className = "chip" + (state.palette === "auto" ? " active" : "");
  auto.innerHTML = `<i style="background:conic-gradient(#ff00e6,#00d5ff,#00ffa2,#ff00e6)"></i>Auto`;
  auto.onclick = () => send("palette", "auto"); pe.appendChild(auto);
  catalog.palettes.filter((p) => p.id !== "custom").forEach((p) => {
    const c = document.createElement("button");
    c.className = "chip" + (state.palette === p.id ? " active" : "");
    c.innerHTML = `<i style="background:${grad(p.stops)}"></i>${p.name}`;
    c.onclick = () => send("palette", p.id);
    pe.appendChild(c);
  });
  const fx = $("#effects"); fx.innerHTML = "";
  catalog.music.forEach((e) => fx.appendChild(card(e.name, e.category === "special" ? "Special perete" : "", state.mode === "music" && state.music_effect === e.id,
    () => send("effect", e.id), e.category === "special" ? "special" : "")));
  const pa = $("#party"); pa.innerHTML = "";
  catalog.party.filter((p) => p.id !== "auto_dj").forEach((p) => pa.appendChild(card(p.name, p.desc,
    state.mode === "party" && state.party_preset === p.id, () => send("party_preset", p.id))));
  $("#autodj").classList.toggle("active", state.mode === "party" && state.party_preset === "auto_dj");
  const am = $("#ambient"); am.innerHTML = "";
  catalog.ambient.forEach((e) => am.appendChild(card(e.name, "", state.mode === "ambient" && state.ambient_scene === e.id, () => send("ambient", e.id))));
  const pr = $("#presets"); pr.innerHTML = "";
  (catalog.presets || []).forEach((p) => {
    const c = document.createElement("button"); c.className = "chip"; c.textContent = p.name;
    c.onclick = () => { send("preset", p.id); toast("Presetare: " + p.name); }; pr.appendChild(c);
  });
  $("#presetsWrap").classList.toggle("hidden", !(catalog.presets || []).length);
}

let forcedMode = null;
function uiMode() { const m = forcedMode || state.mode; return m === "studio" ? "music" : m; }

function applyState(s) {
  state = s;
  forcedMode = null;
  $("#power").classList.toggle("on", !!s.led_on);
  setRange("#brightness", s.brightness); $("#briVal").textContent = Math.round(s.brightness * 100) + "%";
  setRange("#intensity", s.intensity); setRange("#duration", s.duration);
  setRange("#temp", s.ambient_temp); $("#tempVal").textContent = s.ambient_temp + " K";
  setRange("#ambInt", s.ambient_intensity);
  $("#strobe").checked = !!s.strobe_enabled;
  if (document.activeElement !== $("#color")) $("#color").value = s.color;
  render();
}
function setRange(sel, v) { const el = $(sel); if (document.activeElement !== el && v !== undefined) el.value = v; }

function applyStatus(st) {
  status = st;
  $("#bpm").textContent = st.bpm > 0 && !st.silent ? Math.round(st.bpm) : "--";
  $("#effName").textContent = st.effect_name || "";
  $("#section").textContent = state.mode === "party" ? [st.style, st.section].filter(Boolean).join(" · ") : "";
  $("#partyStatus").textContent = state.mode === "party" ? `${st.style || ""}  ${st.section ? "· " + st.section : ""}  ${st.beats_left ? "· schimbare în " + st.beats_left + " bătăi" : ""}` : "";
  if (st.beat_count !== lastBeat) {
    lastBeat = st.beat_count; const d = $("#beatDot"); d.classList.add("on"); setTimeout(() => d.classList.remove("on"), 90);
  }
}

// ------------------------------------------------------------------ live wall
const cv = $("#wall"), cx = cv.getContext("2d");
function drawWall() {
  requestAnimationFrame(drawWall);
  const W = cv.width = cv.clientWidth * devicePixelRatio, H = cv.height = cv.clientHeight * devicePixelRatio;
  cx.fillStyle = "#08090d"; cx.fillRect(0, 0, W, H);
  // fireplace
  const fw = W * 0.24, fh = H * 0.2, fx0 = (W - fw) / 2, fy0 = H * 0.62;
  cx.fillStyle = "#121318"; cx.fillRect(fx0 - 6, fy0 - 6, fw + 12, fh + 12);
  const fg = cx.createLinearGradient(0, fy0, 0, fy0 + fh); fg.addColorStop(0, "#1a0c05"); fg.addColorStop(1, "#ff6a1a55");
  cx.fillStyle = fg; cx.fillRect(fx0, fy0, fw, fh);
  if (!frame) return;
  const { cols, rows, data } = frame;
  const top = H * 0.1, bot = H * 0.9, ph = bot - top;
  const spacing = W * 0.055, gap = W * 0.33;
  const xs = [];
  for (let i = 0; i < 6; i++) xs.push(W / 2 - gap / 2 - (5 - i) * spacing);
  for (let i = 0; i < 6; i++) xs.push(W / 2 + gap / 2 + i * spacing);
  cx.globalCompositeOperation = "lighter";
  for (let c = 0; c < cols; c++) {
    const x = xs[c];
    for (let r = 0; r < rows; r++) {
      const o = (c * rows + r) * 3;
      const R = data[o], G = data[o + 1], B = data[o + 2];
      if (R + G + B < 6) continue;
      const y = bot - (r + 1) * ph / rows;
      cx.fillStyle = `rgba(${R},${G},${B},0.16)`;
      cx.fillRect(x - spacing * 0.42, y - 2, spacing * 0.84, ph / rows + 4);
      cx.fillStyle = `rgb(${R},${G},${B})`;
      cx.fillRect(x - 2.5 * devicePixelRatio, y, 5 * devicePixelRatio, ph / rows + 0.6);
    }
  }
  cx.globalCompositeOperation = "source-over";
}

// ------------------------------------------------------------------ socket
function connect() {
  ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
  ws.binaryType = "arraybuffer";
  ws.onopen = () => { $("#conn").textContent = "conectat"; };
  ws.onclose = (e) => {
    $("#conn").textContent = "reconectare…";
    if (e.code === 4401) { showLogin(); return; }
    setTimeout(connect, 1500);
  };
  ws.onmessage = (ev) => {
    if (typeof ev.data === "string") {
      const m = JSON.parse(ev.data);
      if (m.type === "state") applyState(m.state);
      else if (m.type === "status") applyStatus(m.status);
    } else {
      const u = new Uint8Array(ev.data);
      frame = { cols: u[0], rows: u[1], data: u.subarray(2) };
    }
  };
}

// ------------------------------------------------------------------ controls
$$(".tab").forEach((t) => t.onclick = () => { forcedMode = t.dataset.mode; send("mode", t.dataset.mode); render(); });
$("#power").onclick = () => send("led", !state.led_on);
$("#autodj").onclick = () => send("auto_dj", true);
function throttled(fn, ms) { let t = 0, pend = null; return (v) => { pend = v; const now = Date.now();
  if (now - t > ms) { t = now; fn(pend); } else { clearTimeout(throttled._x); throttled._x = setTimeout(() => fn(pend), ms); } }; }
const bind = (sel, action, label) => { const el = $(sel); const f = throttled((v) => send(action, parseFloat(v)), 80);
  el.addEventListener("input", () => { f(el.value); if (label) label(el.value); }); };
bind("#brightness", "brightness", (v) => $("#briVal").textContent = Math.round(v * 100) + "%");
bind("#intensity", "intensity"); bind("#duration", "duration");
bind("#temp", "ambient_temp", (v) => $("#tempVal").textContent = v + " K"); bind("#ambInt", "ambient_intensity");
$("#color").addEventListener("input", throttled((v) => send("color", v), 120));
$("#color").addEventListener("change", () => send("color", $("#color").value));
SWATCHES.forEach((c) => { const b = document.createElement("button"); b.style.background = c;
  b.onclick = () => { $("#color").value = c; send("color", c); }; $("#swatches").appendChild(b); });
$("#strobe").addEventListener("change", (e) => {
  if (e.target.checked) {
    const ok = confirm("⚠ AVERTISMENT\n\nEfectele stroboscopice pot declanșa crize la persoanele cu epilepsie fotosensibilă și pot deranja animalele de companie.\n\nActivezi stroboscopul?");
    if (!ok) { e.target.checked = false; return; }
  }
  send("strobe", e.target.checked);
});

async function start() {
  try {
    catalog = await api("/api/catalog");
    const s = await api("/api/state"); applyState(s.state); applyStatus(s.status);
    connect();
  } catch (e) { /* login shown */ }
}

(async function init() {
  drawWall();
  const qp = new URLSearchParams(location.search);
  const sess = await fetch("/api/session", { credentials: "same-origin" }).then((r) => r.json()).catch(() => ({ ok: false }));
  if (sess.ok) { start(); return; }
  if (qp.get("pin")) { history.replaceState(null, "", "/"); await doLogin(qp.get("pin")); return; }
  showLogin();
})();
