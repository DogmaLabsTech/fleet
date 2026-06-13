"use strict";
const $ = id => document.getElementById(id);
const state = { sessions: [], stopped: [], counts: { live: 0, busy: 0, waiting: 0, idle: 0 },
  selected: null, tabBySession: {}, detail: null, graphNodes: null, graphKey: null, confirmYes: null };

function el(tag, cls, text) { const e = document.createElement(tag); if (cls) e.className = cls; if (text !== undefined) e.textContent = text; return e; }
function fmtAge(s) { if (s < 60) return s + "s"; const m = Math.floor(s / 60); if (m < 60) return m + "m"; return Math.floor(m / 60) + "h" + String(m % 60).padStart(2, "0") + "m"; }
function fmtTs(ts) {
  if (!ts) return "";
  const d = new Date(ts);
  return isNaN(d) ? String(ts).slice(11, 19) : d.toLocaleTimeString("en-GB", { hour12: false });
}
function shortModel(m) { return (m || "?").replace(/^claude-/, ""); }
function areaOf(p) {
  // Group files by their top-level project folder, derived from the path itself.
  p = p || "";
  const m = /[\\/]([^\\/]+)[\\/][^\\/]+[\\/]/.exec(p);
  return m ? m[1] : "other";
}
function toast(msg, ok) { const t = el("div", "toast" + (ok ? "" : " err"), msg); $("toasts").appendChild(t); setTimeout(() => t.remove(), 4500); }
async function post(payload) {
  try { const r = await fetch("/action", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) }); const d = await r.json(); toast(d.message, d.ok); return d; }
  catch (e) { toast("action failed: " + e, false); return { ok: false }; }
}

/* ---------- confirm modal (used by end-session) ---------- */
function askConfirm(text, yesLabel, danger, onYes) {
  $("confirm-text").textContent = text;
  const yes = $("confirm-yes");
  yes.textContent = yesLabel;
  yes.classList.toggle("danger", !!danger);
  state.confirmYes = onYes;
  $("confirm").hidden = false;
}

/* ---------- rail ---------- */
function renderRail() {
  const list = $("session-list");
  list.replaceChildren(...state.sessions.map(s => {
    const c = el("div", "scard " + s.status + (s.session_id === state.selected ? " selected" : ""));
    const r1 = el("div", "row1");
    r1.appendChild(el("span", "dot " + s.status));
    r1.appendChild(el("span", "proj", s.project));
    r1.appendChild(el("span", "age", fmtAge(s.age_s)));
    c.appendChild(r1);
    const now = s.status === "waiting" ? "⚠ " + (s.waiting_for || "waiting on you")
      : s.status === "busy" ? (s.activity || "working…") : (s.title || s.last_prompt || "");
    c.appendChild(el("div", "line2", now));
    c.onclick = () => select(s.session_id);
    return c;
  }));
  const counts = `${state.counts.live} live · ${state.counts.busy} busy` +
    (state.counts.waiting ? ` · ${state.counts.waiting} waiting` : "") + ` · ${state.counts.idle} idle` +
    (state.counts.background ? ` · ${state.counts.background} bg` : "");
  $("counts").textContent = counts;
  document.title = state.counts.busy ? `● ${state.counts.busy} busy — Fleet` : "Fleet";
  $("stopped-list").replaceChildren(...state.stopped.slice(0, 5).map(s =>
    el("div", null, `○ ${s.project} — stopped ${fmtAge(s.age_s)} ago`)));
}

/* ---------- detail ---------- */
function select(sid) { state.selected = sid; state.detail = null; state.graphNodes = null; state.graphKey = null; refreshDetail(); renderRail(); }
function activeTab() { return state.tabBySession[state.selected] || "head"; }

function renderDetailHead(rec) {
  $("detail-empty").style.display = "none"; $("detail-body").hidden = false;
  $("d-dot").className = "dot " + rec.status;
  $("d-project").textContent = rec.project;
  if (rec.cwd) {
    $("d-project").title = rec.cwd;
    $("d-project").onclick = () => post({ action: "open-folder", path: rec.cwd });
  }
  $("d-title").textContent = rec.name || rec.title || "";
  $("d-meta").textContent = `pid ${rec.pid} · ${shortModel(rec.model)} · ${rec.branch || ""} · v${rec.version || "?"} · ${fmtAge(rec.age_s)}`;
  $("d-copy").onclick = () => navigator.clipboard.writeText(rec.session_id)
    .then(() => toast("session id copied", true), () => toast("copy failed", false));
  $("d-kill").onclick = () => {
    const rec2 = rec;
    askConfirm(`End session "${rec2.project} — ${rec2.name || rec2.title || rec2.session_id}"` +
      (rec2.status === "busy" ? " — it is BUSY right now and will lose in-flight work." : "?"),
      "End session", true, async () => { await post({ action: "kill", pid: rec2.pid, started_at: rec2.started_at }); refreshList(); });
  };
}

function fileRow(f, openAs) {
  const r = el("div", "frow");
  r.appendChild(el("span", "cnt", f.count + "×"));
  r.appendChild(el("span", null, f.path));
  if (openAs) r.onclick = () => post({ action: openAs, path: f.path });
  else r.style.cursor = "default";
  return r;
}

function renderHead(d) {
  const body = $("tab-head"); body.replaceChildren();
  const h = d.head;
  const gauge = el("div", "h-section");
  gauge.appendChild(el("h3", null, `context — ${h.ctx_tokens ? Math.round(h.ctx_tokens / 1000) + "k" : "?"} / 200k tokens`));
  const g = el("div", "gauge"); const i = el("i");
  i.style.width = Math.min(100, (h.ctx_tokens || 0) / 2000) + "%"; g.appendChild(i); gauge.appendChild(g);
  body.appendChild(gauge);
  const rules = el("div", "h-section"); rules.appendChild(el("h3", null, "rules in scope (from cwd)"));
  (h.rules || []).forEach(p => rules.appendChild(fileRow({ path: p, count: "" }, "open-file")));
  body.appendChild(rules);
  [["files read", "read"], ["files edited", "edited"], ["files written", "written"], ["searches", "searched"]].forEach(([label, key]) => {
    const rows = (h.files[key] || []);
    if (!rows.length) return;
    const sec = el("div", "h-section");
    sec.appendChild(el("h3", null, `${label} (${rows.length})`));
    const byArea = new Map();
    rows.slice(0, 40).forEach(f => {
      const a = key === "searched" ? "" : areaOf(f.path);
      if (!byArea.has(a)) byArea.set(a, []);
      byArea.get(a).push(f);
    });
    for (const [area, group] of byArea) {
      if (area && byArea.size > 1) sec.appendChild(el("div", "area-label", area));
      group.forEach(f => sec.appendChild(fileRow(f, key === "searched" ? null : "open-file")));
    }
    body.appendChild(sec);
  });
  const tools = el("div", "h-section"); tools.appendChild(el("h3", null, "skills · agents · mcp"));
  (h.skills || []).forEach(s => tools.appendChild(el("span", "chip", s)));
  (h.agents || []).forEach(a => tools.appendChild(el("span", "chip", `agent:${a.type} — ${a.desc}`)));
  (h.mcp || []).forEach(m => tools.appendChild(el("span", "chip", "mcp:" + m)));
  body.appendChild(tools);
  (h.warnings || []).forEach(w => body.appendChild(el("div", "dim", "⚠ " + w)));
}

function renderTimeline(d) {
  const body = $("tab-timeline");
  const pinned = body.scrollHeight - body.scrollTop - body.clientHeight < 60;
  body.replaceChildren(...d.timeline.map(e => {
    const row = el("div", "tl-entry tl-" + e.kind);
    row.appendChild(el("span", "ts", fmtTs(e.ts)));
    row.appendChild(el("span", "badge", e.kind));
    row.appendChild(el("span", "txt", e.text));
    return row;
  }));
  const s = state.detail && state.detail.session;
  if (s && s.status === "busy" && s.activity) {
    const row = el("div", "tl-entry tl-now");
    row.appendChild(el("span", "ts", "now"));
    row.appendChild(el("span", "badge", "now"));
    row.appendChild(el("span", "txt", s.activity));
    body.appendChild(row);
  }
  if (d.timeline_total > d.timeline.length)
    body.prepend(el("div", "dim", `… ${d.timeline_total - d.timeline.length} earlier events`));
  if (pinned) body.scrollTop = body.scrollHeight;
}

/* ---------- vault graph (canvas force layout) ---------- */
function renderGraph(g) {
  const canvas = $("graph"), empty = $("vault-empty");
  if (!g.nodes.length) {
    empty.hidden = false;
    empty.replaceChildren(el("div", null, "this session has not touched any vault pages"));
    const b = el("button", null, "open vault in Obsidian");
    b.onclick = () => post({ action: "open-obsidian", rel: "" });
    empty.appendChild(b);
    canvas.getContext("2d").clearRect(0, 0, canvas.width, canvas.height); return;
  }
  empty.hidden = true;
  const W = canvas.width = canvas.clientWidth, H = canvas.height = canvas.clientHeight;
  let fresh = false;
  if (!state.graphNodes || state.graphKey !== JSON.stringify(g.nodes.map(n => n.id))) {
    state.graphKey = JSON.stringify(g.nodes.map(n => n.id));
    state.graphNodes = g.nodes.map((n, i) => ({ ...n,
      x: W / 2 + (n.kind === "session" ? 0 : Math.cos(i * 2.4) * 120),
      y: H / 2 + (n.kind === "session" ? 0 : Math.sin(i * 2.4) * 120), vx: 0, vy: 0 }));
    fresh = true;
  }
  const nodes = state.graphNodes, byId = Object.fromEntries(nodes.map(n => [n.id, n]));
  if (fresh) {
    for (let it = 0; it < 120; it++) {
      for (const a of nodes) for (const b of nodes) {
        if (a === b) continue;
        const dx = a.x - b.x, dy = a.y - b.y, d2 = Math.max(dx * dx + dy * dy, 40);
        const f = 2200 / d2; a.vx += dx / Math.sqrt(d2) * f; a.vy += dy / Math.sqrt(d2) * f;
      }
      for (const e of g.edges) {
        const a = byId[e.from], b = byId[e.to]; if (!a || !b) continue;
        const dx = b.x - a.x, dy = b.y - a.y, d = Math.sqrt(dx * dx + dy * dy) || 1, f = (d - 110) * 0.02;
        a.vx += dx / d * f; a.vy += dy / d * f; b.vx -= dx / d * f; b.vy -= dy / d * f;
      }
      for (const n of nodes) {
        n.vx += (W / 2 - n.x) * 0.002; n.vy += (H / 2 - n.y) * 0.002;
        n.x += n.vx *= 0.82; n.y += n.vy *= 0.82;
        n.x = Math.max(50, Math.min(W - 50, n.x)); n.y = Math.max(30, Math.min(H - 30, n.y));
      }
    }
  }
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, W, H);
  for (const e of g.edges) {
    const a = byId[e.from], b = byId[e.to]; if (!a || !b) continue;
    ctx.strokeStyle = e.kind === "edited" ? "#FF8200" : e.kind === "read" ? "#6b6864" : "#2f2d2b";
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
  }
  ctx.font = "11px 'JetBrains Mono',monospace"; ctx.textAlign = "center";
  for (const n of nodes) {
    const r = n.kind === "session" ? 10 : n.kind === "page" ? 7 : 5;
    ctx.fillStyle = n.kind === "session" ? "#FF8200" : n.touch === "edited" ? "#FF8200" : n.kind === "page" ? "#f4eee5" : "#6b6864";
    ctx.beginPath(); ctx.arc(n.x, n.y, r, 0, Math.PI * 2); ctx.fill();
    ctx.fillStyle = n.kind === "neighbor" ? "#9ca3af" : "#f4eee5";
    ctx.fillText(n.label, n.x, n.y - r - 5);
  }
  canvas.onclick = ev => {
    const rect = canvas.getBoundingClientRect();
    const x = ev.clientX - rect.left, y = ev.clientY - rect.top;
    const hit = nodes.find(n => (n.x - x) ** 2 + (n.y - y) ** 2 < 18 ** 2 && n.kind !== "session");
    if (hit) post({ action: "open-obsidian", rel: hit.id });
  };
  if (g.overflow) { ctx.textAlign = "left"; ctx.fillStyle = "#9ca3af"; ctx.fillText(`+${g.overflow} more pages not shown`, 12, H - 12); }
  if (g.warnings && g.warnings.length) { ctx.textAlign = "left"; ctx.fillStyle = "#9ca3af"; ctx.fillText(`⚠ ${g.warnings.length} unreadable page(s)`, 12, 18); }
}

/* ---------- polling ---------- */
async function refreshList() {
  try {
    const d = await (await fetch("/data")).json();
    state.sessions = d.sessions; state.stopped = d.stopped_recent; state.counts = d.counts;
    renderRail();
    if (state.selected && !d.sessions.concat(d.stopped_recent).some(s => s.session_id === state.selected)) {
      state.selected = null; $("detail-body").hidden = true; $("detail-empty").style.display = "";
    }
  } catch (e) { $("counts").textContent = "collector offline — retrying"; }
}
async function refreshDetail() {
  if (!state.selected) return;
  const sid = state.selected;
  try {
    const r = await fetch("/session/" + sid);
    if (sid !== state.selected || !r.ok) return;
    const d = await r.json();
    if (sid !== state.selected || d.error) return;
    state.detail = d;
    renderDetailHead(d.session);
    const tab = activeTab();
    document.querySelectorAll(".tab").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
    $("tab-head").hidden = tab !== "head"; $("tab-vault").hidden = tab !== "vault"; $("tab-timeline").hidden = tab !== "timeline";
    if (tab === "head") renderHead(d);
    if (tab === "timeline") renderTimeline(d);
    if (tab === "vault") {
      const rv = await fetch("/vault/" + sid);
      if (sid !== state.selected) return;
      if (rv.ok) renderGraph(await rv.json());
    }
  } catch (e) { /* keep last view; list poll shows offline */ }
}
document.querySelectorAll(".tab").forEach(b => b.onclick = () => { state.tabBySession[state.selected] = b.dataset.tab; refreshDetail(); });
$("srv-stop").onclick = () => {
  if (window.confirm("Stop the fleet server? The app/dashboard will go offline."))
    post({ action: "stop-server" });
};
$("confirm-no").onclick = () => { $("confirm").hidden = true; state.confirmYes = null; };
$("confirm-yes").onclick = async () => {
  $("confirm").hidden = true;
  const fn = state.confirmYes; state.confirmYes = null;
  if (fn) await fn();
};
document.addEventListener("keydown", e => { if (e.key === "Escape") { if (!$("confirm").hidden) $("confirm-no").click(); } });

function tick() {
  refreshList();
  refreshDetail();
}
refreshList();
setInterval(tick, 5000);
