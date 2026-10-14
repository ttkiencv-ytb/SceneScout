/* SceneScout front end. Plain JS, no build step. */
"use strict";
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const enc = encodeURIComponent;
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const PER = 5, MAXC = 6;
const TABS = [["history", "Lịch sử"], ["stock", "Stock"], ["library", "Đã dùng"], ["manual", "Thủ công"]];

const api = {
  async req(method, url, body) {
    const r = await fetch(url, { method, headers: body ? { "Content-Type": "application/json" } : {}, body: body ? JSON.stringify(body) : undefined });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.detail || `HTTP ${r.status}`);
    return data;
  },
  get: u => api.req("GET", u), post: (u, b) => api.req("POST", u, b), put: (u, b) => api.req("PUT", u, b),
  patch: (u, b) => api.req("PATCH", u, b), del: u => api.req("DELETE", u),
};

const S = { meta: null, profile: null, settings: null, project: null, rows: [], active: 0, queue: [], running: 0, screen: "" };

/* ---------------- small UI helpers ---------------- */
function toast(msg, ms = 2800) {
  const t = $("#toast"); t.textContent = msg; t.style.display = "block";
  clearTimeout(t._h); t._h = setTimeout(() => (t.style.display = "none"), ms);
}
function modal(html, wide = false) {
  $("#dialog").className = "dialog" + (wide ? " wide" : "");
  $("#dialog").innerHTML = html; $("#modal").classList.add("show");
  return $("#dialog");
}
function closeModal() { $("#modal").classList.remove("show"); }
$("#modal").addEventListener("click", e => { if (e.target.id === "modal" || e.target.matches("[data-close]")) closeModal(); });
const isTyping = el => el && ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
const fileToDataURL = f => new Promise((ok, no) => { const r = new FileReader(); r.onload = () => ok(r.result); r.onerror = no; r.readAsDataURL(f); });
const fmtDate = t => new Date(t * 1000).toLocaleString("vi-VN", { dateStyle: "short", timeStyle: "short" });
function header(mode) {
  const ed = mode === "editor";
  $("#chips").classList.toggle("hidden", !ed);
  $("#btnExport").classList.toggle("hidden", !ed);
  $("#btnReanalyze").classList.toggle("hidden", !ed);
  $("#btnProfile").classList.toggle("hidden", !S.profile);
  $("#btnSettings").classList.toggle("hidden", !S.profile);
  if (S.profile) $("#btnProfile").textContent = "👤 " + S.profile.name;
  if (!ed) $("#bar").style.width = "0";
}

async function pollJob(id, title) {
  const d = modal(`<h3>${esc(title)}</h3><p id="jobMsg" class="muted">Đang bắt đầu…</p><div class="card" style="padding:0;height:8px"><div id="jobBar" style="height:8px;width:0;background:var(--amber);border-radius:8px"></div></div>`);
  while (true) {
    await new Promise(r => setTimeout(r, 700));
    const j = await api.get(`/api/jobs/${id}`);
    const pct = j.total ? Math.round(100 * j.done / j.total) : 5;
    $("#jobBar", d).style.width = pct + "%";
    $("#jobMsg", d).textContent = j.stage === "context" ? "AI đang đọc toàn bộ kịch bản…" :
      j.stage === "rows" ? `Đang viết từ khóa: ${j.done}/${j.total} dòng` :
      j.stage === "download" ? `Đang tải ảnh: ${j.done}/${j.total}` :
      j.stage === "render" ? `Đang dựng video: ${j.done}/${j.total} cảnh` :
      j.stage === "finish" ? "Đang ghép video và giọng đọc…" : "Đang xử lý…";
    if (j.status === "done") { closeModal(); return j.result; }
    if (j.status === "error") { closeModal(); throw new Error(j.message); }
  }
}

/* ---------------- profiles ---------------- */
async function showProfiles() {
  S.screen = "profiles"; S.profile = null; header("profiles");
  $("#crumb").textContent = "";
  const list = await api.get("/api/profiles");
  $("#view").innerHTML = `<section class="screen">
    <h2>Ai đang làm việc?</h2><p class="muted">Mỗi người một hồ sơ: dự án, cài đặt và khóa API riêng. Thư viện ảnh đã dùng thì dùng chung.</p>
    <div class="cards">${list.map(p => `<div class="card click" data-id="${p.id}"><div class="name">👤 ${esc(p.name)}</div><div class="muted tiny">Tạo ${fmtDate(p.created)}</div></div>`).join("")}
      <div class="card"><div class="field" style="margin:0"><label>Hồ sơ mới</label><input id="newProfile" placeholder="Tên của bạn"></div>
      <div class="acts" style="margin-top:10px"><button class="btn primary small" id="addProfile">Tạo hồ sơ</button></div></div>
    </div></section>`;
  $$(".card.click").forEach(c => c.onclick = () => chooseProfile(list.find(p => p.id == c.dataset.id)));
  const add = async () => {
    const name = $("#newProfile").value.trim(); if (!name) return;
    try { const r = await api.post("/api/profiles", { name }); chooseProfile({ id: r.id, name }); }
    catch (e) { toast("Tên này đã có. Chọn tên khác."); }
  };
  $("#addProfile").onclick = add;
  $("#newProfile").onkeydown = e => { if (e.key === "Enter") add(); };
}
async function chooseProfile(p) {
  S.profile = p; localStorage.setItem("ss-profile", p.id);
  S.settings = await api.get(`/api/profiles/${p.id}/settings`);
  showHome();
}

/* ---------------- home: projects ---------------- */
async function showHome() {
  S.screen = "home"; S.project = null; S.queue = []; header("home");
  $("#crumb").textContent = "· Dự án";
  const all = S.settings.show_all_projects;
  const list = await api.get(`/api/projects?profile=${S.profile.id}&all=${all ? 1 : 0}`);
  const lib = await api.get("/api/library/stats");
  $("#view").innerHTML = `<section class="screen">
    <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
      <h2 style="margin-right:auto">Dự án</h2>
      <label class="muted tiny"><input type="checkbox" id="showAll" ${all ? "checked" : ""}> Hiện dự án của mọi hồ sơ</label>
      <button class="btn" id="btnImport">Nhập file dự án</button>
      <button class="btn primary" id="btnNew">+ Dự án mới</button>
    </div>
    <p class="muted tiny">Thư viện ảnh đã dùng: ${lib.items} tệp, dùng lại được ở mọi dự án.</p>
    ${list.length ? `<div class="cards">${list.map(projectCard).join("")}</div>` :
      `<div class="empty" style="margin-top:18px"><h3>Chưa có dự án nào</h3><p>Bấm “+ Dự án mới” và nạp file SRT của kịch bản.</p></div>`}
  </section>`;
  $("#showAll").onchange = async e => { S.settings = await api.put(`/api/profiles/${S.profile.id}/settings`, { show_all_projects: e.target.checked }); showHome(); };
  $("#btnNew").onclick = newProjectDialog;
  $("#btnImport").onclick = () => pickFile(".json", async f => {
    try { const r = await api.post("/api/projects/import", { profile_id: S.profile.id, content: await f.text() }); toast("Đã nhập dự án"); openProject(r.id); }
    catch (e) { toast("File dự án không hợp lệ: " + e.message, 5000); }
  });
  $$("[data-open]").forEach(b => b.onclick = () => openProject(+b.dataset.open));
  $$("[data-dup]").forEach(b => b.onclick = async () => { await api.post(`/api/projects/${b.dataset.dup}/duplicate`, { profile_id: S.profile.id }); showHome(); });
  $$("[data-pkg]").forEach(b => b.onclick = () => { location.href = `/api/projects/${b.dataset.pkg}/package`; });
  $$("[data-del]").forEach(b => b.onclick = async () => { if (confirm("Xóa dự án này? Ảnh đã xuất và thư viện không bị xóa.")) { await api.del(`/api/projects/${b.dataset.del}`); showHome(); } });
}
function projectCard(p) {
  const pct = p.n_rows ? Math.round(100 * p.n_done / p.n_rows) : 0;
  return `<div class="card"><div class="name">${esc(p.name)}</div>
    <div class="muted tiny">${p.n_rows} dòng · ${esc(p.owner || "")} · sửa ${fmtDate(p.updated)}</div>
    <div class="bar2"><div style="width:${pct}%"></div></div><div class="muted tiny">Đã chọn hoặc đánh dấu ${p.n_done}/${p.n_rows}</div>
    <div class="acts"><button class="btn primary small" data-open="${p.id}">Mở</button><button class="btn small" data-dup="${p.id}">Nhân bản</button>
    <button class="btn small" data-pkg="${p.id}" title="Tải file dự án để chuyển cho người khác">Tải file</button><button class="btn small danger" data-del="${p.id}">Xóa</button></div></div>`;
}
function pickFile(accept, cb) {
  const f = $("#filePick"); f.accept = accept; f.value = "";
  f.onchange = () => f.files[0] && cb(f.files[0]); f.click();
}
function newProjectDialog() {
  const hasAI = (S.settings.ai_chain || []).some(c => c.model);
  const d = modal(`<h3>Dự án mới</h3>
    <div class="field"><label>File kịch bản (SRT khuyên dùng; CSV từ khóa hoặc TXT cũng được)</label><input type="file" id="npFile" accept=".srt,.csv,.txt"></div>
    <div class="field"><label>Tên dự án</label><input id="npName" placeholder="Lấy theo tên file nếu bỏ trống"></div>
    <div class="grid2"><div class="field"><label>Title video (tùy chọn)</label><input id="npTitle"></div>
    <div class="field"><label>Mô tả thumbnail (tùy chọn)</label><input id="npThumb" placeholder="Chủ thể, chữ trên thumbnail"></div></div>
    <div class="field"><label>Cách phân tích kịch bản</label><div class="radio">
      <label><input type="radio" name="npMode" value="quick" ${!hasAI ? "checked" : ""}> Nhanh (offline, miễn phí)</label>
      <label><input type="radio" name="npMode" value="ai" ${hasAI ? "checked" : "disabled"}> AI qua API (tự động)</label>
      <label><input type="radio" name="npMode" value="chat"> Chat AI (dán qua Claude / ChatGPT / Gemini, không cần API)</label></div>
      ${hasAI ? "" : (S.settings.ai_chain || []).length
        ? `<div class="tip">Bạn đã thêm nhà cung cấp AI nhưng <b>chưa chọn Model</b>. Vào Cài đặt → AI, bấm ⟳ để chọn model (hoặc chỉ cần bấm Lưu, SceneScout sẽ tự chọn).</div>`
        : `<div class="tip">Chưa cài AI. Vào <b>Cài đặt → AI</b> để thêm ChatGPT, Claude, Gemini, DeepSeek hoặc một lựa chọn miễn phí.</div>`}</div>
    <div class="end"><button class="btn" data-close>Hủy</button><button class="btn primary" id="npGo">Tạo dự án</button></div>`);
  $("#npGo", d).onclick = async () => {
    const f = $("#npFile", d).files[0]; if (!f) return toast("Chọn file kịch bản trước.");
    const mode = d.querySelector("[name=npMode]:checked")?.value || "quick";
    const body = { profile_id: S.profile.id, filename: f.name, content: await f.text(), name: $("#npName", d).value,
      title: $("#npTitle", d).value, thumbnail: $("#npThumb", d).value, mode: mode === "chat" ? "quick" : mode };
    let created = null;
    try {
      const r = await api.post("/api/projects", body); created = r.id;
      if (r.job) {
        const rep = await pollJob(r.job, mode === "chat" ? "Đang chia dòng" : "Đang phân tích kịch bản");
        await openProject(r.id);
        if (mode === "chat") chatBridge(); else reportAnalysis(rep);
      } else openProject(r.id);
    } catch (e) {
      if (created) await openProject(created);
      modal(`<h3>Chưa phân tích được bằng AI</h3><p>${esc(e.message)}</p><p class="muted tiny">Dự án vẫn được tạo với từ khóa chế độ Nhanh. Sửa xong trong Cài đặt → AI thì bấm “Phân tích lại bằng AI”.</p><div class="end"><button class="btn" data-close>Để sau</button><button class="btn primary" id="goAI">Mở Cài đặt AI</button></div>`);
      $("#goAI")?.addEventListener("click", () => { closeModal(); showSettings(); });
      if (!created) showHome();
    }
  };
}
function reportAnalysis(rep) {
  if (!rep) return;
  if (rep.mode !== "ai") return toast("Đã phân tích bằng chế độ Nhanh (không có mô tả tiếng Việt).", 4000);
  const fb = (rep.fallback_rows || []).length;
  const used = Object.entries(rep.providers || {}).map(([k, n]) => `${esc(S.meta.providers[k]?.label || k)}: ${n} lượt`).join(", ");
  modal(`<h3>AI đã phân tích xong</h3>
    <p>${rep.calls} lượt gọi AI · ${used || "—"}</p>
    ${fb ? `<div class="tip">${fb} dòng AI không trả lời được nên dùng chế độ Nhanh: #${rep.fallback_rows.slice(0, 20).join(", #")}${fb > 20 ? "…" : ""}</div>` : `<p class="muted">Mọi dòng đều có mô tả và từ khóa từ AI.</p>`}
    ${(rep.log || []).length ? `<details style="margin-top:10px"><summary class="muted tiny">Nhật ký kỹ thuật (${rep.log.length})</summary><pre class="tiny" style="white-space:pre-wrap">${esc(rep.log.slice(-8).join("\n"))}</pre></details>` : ""}
    <div class="end"><button class="btn primary" data-close>OK</button></div>`);
}

/* ---------------- editor ---------------- */
async function openProject(id) {
  S.screen = "editor"; header("editor");
  const p = await api.get(`/api/projects/${id}`);
  S.project = p; S.active = 0; S.queue = [];
  S.rows = p.rows.map(r => ({ ...r, sel: r.sel ? JSON.parse(r.sel) : null, cands: r.cands || {}, tab: "history", kind: "image", page: 0, status: {} }));
  $("#crumb").innerHTML = `· <a href="#" id="toHome">Dự án</a> · <b contenteditable="true" id="pName" spellcheck="false">${esc(p.name)}</b>`;
  $("#toHome").onclick = e => { e.preventDefault(); showHome(); };
  $("#pName").onblur = e => api.patch(`/api/projects/${id}`, { name: e.target.textContent.trim() || p.name });
  $("#pName").onkeydown = e => { if (e.key === "Enter") { e.preventDefault(); e.target.blur(); } };
  const quick = ["quick", "pending", ""].includes(p.analysis || "");
  $("#view").innerHTML = `${quick ? `<div class="tip" style="margin:12px 18px 0;display:flex;gap:12px;align-items:center;flex-wrap:wrap">
      <span>Dự án này đang dùng từ khóa của chế độ <b>Nhanh</b>: chưa có mô tả cảnh tiếng Việt và từ khóa chưa hiểu ngữ cảnh.</span>
      <button class="btn small primary" id="toAI">Phân tích lại bằng AI</button><button class="btn small" id="toChat">Dùng chat AI (không cần API)</button></div>` : ""}
    <section class="screen wide" id="rows"></section>`;
  $("#toAI")?.addEventListener("click", () => $("#btnReanalyze").click());
  $("#toChat")?.addEventListener("click", () => chatBridge());
  const host = $("#rows");
  S.rows.forEach((r, i) => host.appendChild(rowEl(r, i)));
  computeChoices(); S.rows.forEach((_, i) => renderStrip(i));
  setActive(0, false); updateCounts();
  S.rows.forEach((r, i) => { if (!r.cands.history) enqueue(i, "history"); });
}

const ckey = r => r.tab === "stock" ? `stock_${r.kind}` : r.tab;
const visible = r => r.cands[ckey(r)] || [];
const pname = () => S.project?.name || "";

function rowEl(r, i) {
  const el = document.createElement("section");
  el.className = "row"; el.id = "r" + i;
  el.innerHTML = `<div class="meta">
      <div class="head"><span class="stt">#${r.stt}</span><span class="tc">${esc(r.start)}${r.end ? " – " + esc(r.end) : ""}</span><span class="flagb"></span></div>
      <div class="lead">${esc(r.loidan)}</div>${r.mota && r.mota !== r.loidan ? `<div class="desc">${esc(r.mota)}</div>` : ""}
      <div class="kwline"><input class="kw" value="${esc(r.keyword)}" title="Từ khóa chính"><input class="kw phu" value="${esc(r.keyword_phu)}" placeholder="từ khóa phụ" title="Từ khóa phụ"></div>
      <div class="acts"><button class="btn small" data-act="search">Tìm lại</button><button class="btn small" data-act="google">Google</button>
        <button class="btn small" data-act="envato">Envato</button><button class="btn small ai" data-act="ai">Cần ảnh AI</button><button class="btn small env" data-act="env">Dùng Envato</button></div>
    </div>
    <div><div class="tabs"></div><div class="strip"></div></div>`;
  el.addEventListener("click", e => {
    if (S.active !== i) setActive(i, false);
    const t = e.target.closest("[data-tab]");
    if (t) return switchTab(i, t.dataset.tab);
    const k = e.target.closest("[data-kind]");
    if (k) { r.kind = k.dataset.kind; r.page = 0; renderStrip(i); if (!r.cands[ckey(r)]) enqueue(i, "stock", true); return; }
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.k != null) return pick(i, +b.dataset.k, false);
    ({ search: () => research(i), google: () => openGoogle(i), envato: () => openEnvato(i), ai: () => toggleFlag(i, "AI"), env: () => toggleFlag(i, "ENVATO"),
       more: () => { r.page = (r.page + 1) % Math.max(1, Math.ceil(visible(r).length / PER)); renderStrip(i); } })[b.dataset.act]?.();
  });
  el.addEventListener("dblclick", e => { const s = e.target.closest(".slot"); if (s) preview(i, +s.dataset.k); });
  const [k1, k2] = $$("input.kw", el);
  const saveKw = () => { r.keyword = k1.value.trim(); r.keyword_phu = k2.value.trim(); patchRow(r, { keyword: r.keyword, keyword_phu: r.keyword_phu }); };
  [k1, k2].forEach(inp => { inp.onchange = saveKw; inp.onkeydown = e => { if (e.key === "Enter") { saveKw(); research(i); inp.blur(); } if (e.key === "Escape") inp.blur(); }; });
  el.addEventListener("dragover", e => { e.preventDefault(); $(".drop", el)?.classList.add("over"); });
  el.addEventListener("dragleave", e => { if (!el.contains(e.relatedTarget)) $(".drop", el)?.classList.remove("over"); });
  el.addEventListener("drop", e => { $(".drop", el)?.classList.remove("over"); handleDrop(e, i); });
  return el;
}

function renderStrip(i) {
  const r = S.rows[i], el = $("#r" + i); if (!el) return;
  el.classList.toggle("flagged", !!r.flag);
  $(".acts .ai", el).classList.toggle("on-ai", r.flag === "AI");
  $(".acts .env", el).classList.toggle("on-env", r.flag === "ENVATO");
  $(".flagb", el).innerHTML = r.flag === "AI" ? '<span class="badge ai">Cần ảnh AI</span>' : r.flag === "ENVATO" ? '<span class="badge env">Envato</span>' : "";
  $(".tabs", el).innerHTML = TABS.map(([k, label]) => {
    const n = k === "stock" ? (r.cands.stock_image?.length || 0) + (r.cands.stock_video?.length || 0) : (r.cands[k]?.length || 0);
    return `<button class="tab ${r.tab === k ? "on" : ""}" data-tab="${k}">${label}${n ? `<span class="n">${n}</span>` : ""}</button>`;
  }).join("") + (r.tab === "stock" ? ` <button class="tab ${r.kind === "image" ? "on" : ""}" data-kind="image">Ảnh</button><button class="tab ${r.kind === "video" ? "on" : ""}" data-kind="video">Video</button>` : "");
  const list = visible(r), start = r.page * PER, view = list.slice(start, start + PER);
  let html = view.map((c, n) => {
    const k = start + n;
    const isSel = r.sel && r.sel.full === c.full, isDef = !r.sel && r._def && r._def.full === c.full;
    const used = (c.used_in || []).filter(x => x !== pname());
    const badge = S.settings.show_used_badge && used.length ? `<span class="used" title="Đã dùng ở: ${esc(used.join(", "))}">đã dùng</span>` : "";
    return `<button class="slot ${isSel ? "sel" : isDef ? "def" : ""}" data-k="${k}" title="${esc(c.title || "")}${c.credit ? " — " + esc(c.credit) : ""}">
      <img loading="lazy" src="${esc(c.thumb)}" alt="" onerror="this.style.opacity=.15"><span class="num">${n + 1}</span>
      ${c.kind === "video" ? `<span class="play">▶ ${c.duration ? c.duration + "s" : ""}</span>` : ""}${badge}<span class="src">${esc(c.source)}</span></button>`;
  }).join("");
  html += `<div class="side">${list.length > PER ? `<button class="more" data-act="more">Khác ${r.page + 1}/${Math.ceil(list.length / PER)}</button>` : ""}<div class="drop">Thả / dán ảnh Google, Envato</div></div>`;
  const st = r.status[ckey(r)];
  if (st === "loading") html += `<div class="state">Đang tìm…</div>`;
  else if (st === "error") html += `<div class="state err">${esc(r.err || "Lỗi khi tìm. Bấm Tìm lại.")}</div>`;
  else if (st === "done" && !list.length) html += `<div class="state">${r.tab === "stock" && !hasStockKeys() ? "Chưa có khóa Pexels / Pixabay / Unsplash. Thêm trong Cài đặt → Nguồn ảnh (miễn phí)." : r.tab === "manual" ? "Kéo ảnh từ Google hoặc Envato vào đây, hoặc Ctrl+V." : "Không có kết quả. Sửa từ khóa rồi Tìm lại, hoặc thử tab khác."}</div>`;
  else if (r.tab === "manual" && !list.length) html += `<div class="state">Bấm Google hoặc Envato, rồi kéo ảnh vào ô bên cạnh hoặc chuột phải → Sao chép hình ảnh → Ctrl+V.</div>`;
  $(".strip", el).innerHTML = html;
}
const hasStockKeys = () => Object.values(S.settings.source_keys || {}).some(Boolean);

function computeChoices() {
  const used = new Set();
  for (const r of S.rows) {
    r._def = null;
    if (r.flag) continue;
    if (r.sel) { used.add(r.sel.full); continue; }
    const pool = [...(r.cands.history || []), ...(r.cands.stock_image || []), ...(r.cands.manual || [])];
    r._def = pool.find(c => !used.has(c.full)) || pool[0] || null;
    if (r._def) used.add(r._def.full);
  }
}
function refreshAll() { computeChoices(); S.rows.forEach((_, i) => renderStrip(i)); updateCounts(); }

function updateCounts() {
  const n = S.rows.length, searched = S.rows.filter(r => r.status.history === "done" || r.cands.history).length;
  $("#cProg").textContent = `Đã tìm ${searched}/${n}`;
  $("#bar").style.width = n ? (100 * searched / n) + "%" : "0";
  $("#cPicked").textContent = "Chọn tay " + S.rows.filter(r => r.sel && !r.flag).length;
  $("#cAI").textContent = "Cần ảnh AI " + S.rows.filter(r => r.flag === "AI").length;
  $("#cEnv").textContent = "Envato " + S.rows.filter(r => r.flag === "ENVATO").length;
}
function setActive(i, scroll = true) {
  if (!S.rows.length) return;
  i = Math.max(0, Math.min(S.rows.length - 1, i));
  $("#r" + S.active)?.classList.remove("active"); S.active = i;
  const el = $("#r" + i); el.classList.add("active");
  if (scroll) el.scrollIntoView({ block: "center", behavior: "smooth" });
}

/* actions */
const patchTimers = {};
function patchRow(r, fields) {
  return api.patch(`/api/projects/${S.project.id}/rows/${r.stt}`, { ...fields, editor: S.profile.id }).catch(() => toast("Không lưu được. Kiểm tra cửa sổ SceneScout còn mở."));
}
function saveCands(r) { clearTimeout(patchTimers[r.stt]); patchTimers[r.stt] = setTimeout(() => patchRow(r, { cands: r.cands }), 800); }
function pick(i, k, advance) {
  const r = S.rows[i], c = visible(r)[k]; if (!c) return;
  r.sel = (r.sel && r.sel.full === c.full && !advance) ? null : c; r.flag = "";
  patchRow(r, { sel: r.sel ? r.sel : "", flag: "" });
  refreshAll(); if (advance) setActive(i + 1);
}
function toggleFlag(i, f) { const r = S.rows[i]; r.flag = r.flag === f ? "" : f; patchRow(r, { flag: r.flag }); refreshAll(); }
function switchTab(i, tab) {
  const r = S.rows[i]; r.tab = tab; r.page = 0; renderStrip(i);
  if (tab !== "manual" && !r.cands[ckey(r)]) enqueue(i, tab, true);
}
function research(i) { const r = S.rows[i]; delete r.cands[ckey(r)]; enqueue(i, r.tab === "manual" ? "history" : r.tab, true); }
const kwOf = r => r.keyword || r.keyword_phu || r.loidan;
function openGoogle(i) { const r = S.rows[i]; switchTab(i, "manual"); window.open("https://www.google.com/search?udm=2&q=" + enc(kwOf(r)), "ss-google"); }
function openEnvato(i) {
  const r = S.rows[i]; switchTab(i, "manual");
  const slug = kwOf(r).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  window.open("https://elements.envato.com/stock-video/" + slug, "ss-envato");
}

/* search queue */
function enqueue(i, tab, front = false) {
  S.queue = S.queue.filter(x => !(x.i === i && x.tab === tab));
  const job = { i, tab, pid: S.project.id }; front ? S.queue.unshift(job) : S.queue.push(job);
  const r = S.rows[i]; r.status[tab === "stock" ? `stock_${r.kind}` : tab] = "loading"; if (r.tab === tab) renderStrip(i);
  pump();
}
function pump() {
  while (S.running < MAXC && S.queue.length) {
    const job = S.queue.shift(); S.running++;
    doSearch(job).finally(() => { S.running--; updateCounts(); pump(); });
  }
}
async function doSearch({ i, tab, pid }) {
  const r = S.rows[i]; if (!r || !S.project || S.project.id !== pid) return;
  const key = tab === "stock" ? `stock_${r.kind}` : tab;
  try {
    const res = await api.get(`/api/search?tab=${tab}&kind=${r.kind}&q=${enc(r.keyword)}&q2=${enc(r.keyword_phu)}&profile=${S.profile.id}`);
    r.cands[key] = res.results || [];
    r.status[key] = "done"; r.err = (res.errors || []).length && !r.cands[key].length ? res.errors.join(" · ") : "";
    if (r.err) r.status[key] = "error";
    saveCands(r);
  } catch (e) { r.status[key] = "error"; r.err = e.message; }
  if (!S.project || S.project.id !== pid) return;
  computeChoices(); renderStrip(i);
}

/* manual drop / paste */
async function addManual(i, src, sourceName) {
  const r = S.rows[i];
  let url = src;
  if (src.startsWith("data:")) {
    try { url = (await api.post("/api/upload", { data: src })).url; } catch (e) { return toast("Không đọc được ảnh vừa thả: " + e.message); }
  }
  const c = { id: "man:" + Date.now(), source: sourceName || "Thủ công", kind: /\.(mp4|webm)(\?|$)/i.test(url) ? "video" : "image", thumb: url, full: url, title: "Thêm tay" };
  r.cands.manual = [c, ...(r.cands.manual || []).filter(x => x.full !== url)];
  r.tab = "manual"; r.page = 0; r.sel = c; r.flag = "";
  patchRow(r, { cands: r.cands, sel: c, flag: "" }); refreshAll();
  toast(`Đã thêm vào dòng #${r.stt}`);
}
async function handleDrop(e, i) {
  e.preventDefault();
  const dt = e.dataTransfer;
  if (dt.files?.length && /^(image|video)\//.test(dt.files[0].type)) return addManual(i, await fileToDataURL(dt.files[0]));
  const uri = (dt.getData("text/uri-list") || "").split("\n").map(s => s.trim()).find(s => s && !s.startsWith("#")) || "";
  const html = dt.getData("text/html") || "";
  const m = html.match(/<img[^>]+src=["']([^"']+)["']/i);
  const g = uri.match(/[?&]imgurl=([^&]+)/);
  let url = g ? decodeURIComponent(g[1]) : m ? m[1].replace(/&amp;/g, "&") : (uri || (dt.getData("text/plain") || "").trim());
  const from = /envato/i.test(uri + html) ? "Envato" : /google|gstatic/i.test(uri + html + url) ? "Google" : "Thủ công";
  if (/^(https?:|data:image)/.test(url)) addManual(i, url, from); else toast("Không đọc được ảnh. Thử chuột phải → Sao chép hình ảnh rồi Ctrl+V.");
}
document.addEventListener("paste", async e => {
  if (S.screen !== "editor" || isTyping(e.target)) return;
  for (const it of e.clipboardData.items) if (/^image\//.test(it.type)) { e.preventDefault(); return addManual(S.active, await fileToDataURL(it.getAsFile())); }
  const t = (e.clipboardData.getData("text") || "").trim();
  if (/^https?:\/\//.test(t)) { e.preventDefault(); addManual(S.active, t); }
});

/* preview */
function preview(i, k) {
  const r = S.rows[i], c = visible(r)[k]; if (!c) return;
  const media = c.kind === "video" ? `<video src="${esc(c.full)}" controls autoplay muted></video>` : `<img src="${esc(c.full)}" alt="">`;
  const d = modal(`<div class="preview">${media}</div><p><b>${esc(c.title || "")}</b><br><span class="muted tiny">${esc(c.source)}${c.credit ? " · " + esc(c.credit) : ""}${c.license ? " · " + esc(c.license) : ""}</span></p>
    <div class="end">${c.page ? `<a class="btn small" href="${esc(c.page)}" target="_blank" rel="noopener">Trang nguồn</a>` : ""}<button class="btn" data-close>Đóng</button><button class="btn primary" id="pvPick">Chọn ${c.kind === "video" ? "video" : "ảnh"} này</button></div>`, true);
  $("#pvPick", d).onclick = () => { closeModal(); pick(i, k, true); };
}

/* export */
async function exportAll(only, timeline = null) {
  const pending = S.queue.length + S.running;
  if (!only && pending && !confirm(`Còn ${pending} dòng đang tìm ảnh. Vẫn xuất ngay?`)) return;
  computeChoices();
  const defaults = {};
  S.rows.forEach(r => { if (!r.sel && !r.flag && r._def) defaults[r.stt] = r._def; });
  try {
    const { job } = await api.post(`/api/projects/${S.project.id}/export`, { profile_id: S.profile.id, defaults, only, timeline });
    const res = await pollJob(job, "Đang tải ảnh về máy");
    const failSet = new Set(res.failed.map(f => f.stt));
    S.rows.forEach((r, i) => $("#r" + i).classList.toggle("fail", failSet.has(r.stt)));
    const links = res.failed.map(f => `<a href="#" data-goto="${S.rows.findIndex(r => r.stt === f.stt)}" title="${esc(f.reason)}">#${f.stt}</a>`).join(" ");
    const d = modal(`<h3>${res.failed.length ? "Xong, còn vài tệp lỗi" : "Đã xuất xong"}</h3>
      <p>${res.ok} tệp đã lưu.${res.flagged ? ` ${res.flagged} dòng AI/Envato` : ""}${res.missing ? `, ${res.missing} dòng chưa có ảnh` : ""} nằm trong <code>rows-AI-Envato-missing.csv</code>. Nguồn và giấy phép ở <code>credits.csv</code>.</p>
      ${timelineSummary(res.timeline)}
      <p class="muted tiny" style="word-break:break-all">${esc(res.outdir)}</p>
      ${res.failed.length ? `<p>Tệp lỗi (bấm để nhảy tới, chọn ảnh khác rồi tải lại): ${links}</p>` : ""}
      <div class="end"><button class="btn small" id="openDir">Mở thư mục</button>${res.failed.length ? `<button class="btn" id="retry">Tải lại tệp lỗi</button>` : ""}<button class="btn primary" data-close>Xong</button></div>`);
    $("#openDir", d).onclick = () => api.post("/api/open-folder", { path: res.outdir });
    $$("[data-goto]", d).forEach(a => a.onclick = e => { e.preventDefault(); closeModal(); setActive(+a.dataset.goto); });
    $("#retry", d)?.addEventListener("click", () => exportAll([...failSet]));
  } catch (e) { toast("Xuất lỗi: " + e.message, 6000); }
}
function timelineSummary(t) {
  if (!t || !Object.keys(t).length) return "";
  const files = [t.mp4 && "<b>scenescout-timeline.mp4</b> (kéo vào CapCut hoặc phần mềm bất kỳ, đặt ở 0:00)",
    t.fcpxml && "<b>scenescout-timeline.fcpxml</b> (DaVinci Resolve: File → Import → Timeline; Final Cut: File → Import → XML)",
    t.premiere && "<b>scenescout-timeline-premiere.xml</b> (Premiere: File → Import)"].filter(Boolean);
  const warn = t.audio_dur && Math.abs(t.audio_dur - t.script_dur) > 3
    ? `<div class="tip">Giọng đọc dài ${Math.round(t.audio_dur)} giây, kịch bản SRT dài ${Math.round(t.script_dur)} giây. Kiểm tra lại có đúng file SRT của bản giọng đọc này không.</div>` : "";
  return `<p>Timeline:</p><ul class="tiny">${files.map(f => `<li>${f}</li>`).join("")}</ul>
    ${t.placeholders ? `<p class="tiny muted">${t.placeholders} cảnh chưa có ảnh được thay bằng khung giữ chỗ có ghi chú, để editor dễ thấy chỗ cần thay.</p>` : ""}${warn}`;
}
function exportDialog() {
  const st = S.settings;
  const d = modal(`<h3>Xuất</h3>
    <p class="muted">Thư mục ảnh đặt tên theo timecode luôn được xuất. Chọn thêm:</p>
    <label style="display:block;margin:8px 0"><input type="checkbox" id="xMp4" ${st.tl_mp4 ? "checked" : ""}> <b>Video MP4 dựng sẵn</b> — mọi ảnh đã nằm đúng thời gian. Kéo vào CapCut, đặt ở 0:00 là khớp.</label>
    <label style="display:block;margin:8px 0"><input type="checkbox" id="xFcp" ${st.tl_fcpxml ? "checked" : ""}> Timeline cho <b>DaVinci Resolve / Final Cut</b> (FCPXML)</label>
    <label style="display:block;margin:8px 0"><input type="checkbox" id="xPr" ${st.tl_premiere ? "checked" : ""}> Timeline cho <b>Premiere Pro</b> (XML)</label>
    <label style="display:block;margin:8px 0"><input type="checkbox" id="xKb" ${st.kenburns ? "checked" : ""}> Hiệu ứng zoom nhẹ cho ảnh tĩnh (tắt thì xuất nhanh hơn)</label>
    <div class="field"><label>Giọng đọc (tùy chọn) — có thì video xuất ra kèm sẵn giọng đọc để xem duyệt</label><input type="file" id="xAudio" accept=".mp3,.wav,.m4a,.aac,.flac,.ogg"></div>
    <p class="muted tiny">Video ${esc(st.video_res)} · ${st.video_fps} khung hình/giây (đổi trong Cài đặt). Dựng video 30 phút mất vài phút đến hơn chục phút tùy máy.</p>
    <div class="end"><button class="btn" data-close>Hủy</button><button class="btn primary" id="xGo">Xuất</button></div>`);
  $("#xGo", d).onclick = async () => {
    const tl = { mp4: $("#xMp4", d).checked, fcpxml: $("#xFcp", d).checked, premiere: $("#xPr", d).checked, kenburns: $("#xKb", d).checked };
    S.settings = await api.put(`/api/profiles/${S.profile.id}/settings`, { tl_mp4: tl.mp4, tl_fcpxml: tl.fcpxml, tl_premiere: tl.premiere, kenburns: tl.kenburns });
    const f = $("#xAudio", d).files[0];
    if (f) {
      $("#xGo", d).textContent = "Đang nạp giọng đọc…"; $("#xGo", d).disabled = true;
      try {
        const r = await fetch("/api/audio", { method: "POST", headers: { "X-Filename": encodeURIComponent(f.name) }, body: f });
        if (!r.ok) throw new Error((await r.json()).detail || r.status);
        tl.audio = (await r.json()).token;
      } catch (e) { $("#xGo", d).disabled = false; $("#xGo", d).textContent = "Xuất"; return toast("Không nạp được file giọng đọc: " + e.message, 6000); }
    }
    closeModal();
    exportAll(null, (tl.mp4 || tl.fcpxml || tl.premiere) ? tl : null);
  };
}
$("#btnExport").onclick = exportDialog;
$("#btnReanalyze").onclick = () => {
  const hasAI = (S.settings.ai_chain || []).some(c => c.model);
  const d = modal(`<h3>Phân tích lại kịch bản</h3><p class="muted">Viết lại mô tả và từ khóa cho mọi dòng. Ảnh đã chọn tay được giữ nguyên.</p>
    <div class="radio"><label><input type="radio" name="ra" value="quick" ${hasAI ? "" : "checked"}> Nhanh</label><label><input type="radio" name="ra" value="ai" ${hasAI ? "checked" : "disabled"}> AI qua API</label><label><input type="radio" name="ra" value="chat"> Chat AI (không cần API)</label></div>
    <label class="muted tiny" style="display:block;margin-top:10px"><input type="checkbox" id="raSearch" checked> Tìm ảnh lại theo từ khóa mới (tab Lịch sử)</label>
    <div class="end"><button class="btn" data-close>Hủy</button><button class="btn primary" id="raGo">Bắt đầu</button></div>`);
  $("#raGo", d).onclick = async () => {
    const mode = d.querySelector("[name=ra]:checked").value, again = $("#raSearch", d).checked;
    if (mode === "chat") { closeModal(); return chatBridge(null, again); }
    try {
      const { job } = await api.post(`/api/projects/${S.project.id}/reanalyze`, { mode, profile_id: S.profile.id });
      const rep = await pollJob(job, "Đang phân tích lại");
      const keep = Object.fromEntries(S.rows.map(r => [r.stt, r]));
      await openProject(S.project.id);
      reportAnalysis(rep);
      if (again) S.rows.forEach((r, i) => { delete r.cands.history; enqueue(i, "history"); });
      else S.rows.forEach(r => { r.cands = keep[r.stt]?.cands || r.cands; });
    } catch (e) { modal(`<h3>Chưa phân tích được</h3><p>${esc(e.message)}</p><p class="muted tiny">Vào Cài đặt → AI, bấm “Thử” ở từng nhà cung cấp để xem cái nào đang lỗi.</p><div class="end"><button class="btn" data-close>Để sau</button><button class="btn primary" id="goAI2">Mở Cài đặt AI</button></div>`); $("#goAI2")?.addEventListener("click", () => { closeModal(); showSettings(); }); }
  };
};

/* ---------------- chat bridge (no API) ---------------- */
async function copyText(t) {
  try { await navigator.clipboard.writeText(t); return true; }
  catch { const ta = document.createElement("textarea"); ta.value = t; document.body.appendChild(ta); ta.select();
    const ok = document.execCommand("copy"); ta.remove(); return ok; }
}
function chatBridge(onlyStts = null, researchAfter = true) {
  const size = Math.max(10, +S.settings.chat_part || 50);
  const all = onlyStts || S.rows.map(r => r.stt);
  const parts = []; for (let k = 0; k < all.length; k += size) parts.push(all.slice(k, k + size));
  const state = { idx: 0, missing: [], done: new Set() };
  const render = () => {
    const part = parts[state.idx], last = state.idx === parts.length - 1;
    const d = modal(`<h3>Phân tích bằng chat AI <span class="muted tiny">(không cần API)</span></h3>
      <p class="muted">Phần <b>${state.idx + 1}/${parts.length}</b> · dòng #${part[0]}–#${part[part.length - 1]} · đã nhận <span id="cbDone">${state.done.size}</span>/${all.length} dòng</p>
      <ol class="tiny" style="padding-left:18px;color:var(--muted)">
        <li>Bấm <b>Sao chép câu lệnh</b>, mở Claude / ChatGPT / Gemini, dán vào ô chat và gửi. Mỗi phần nên dùng một cuộc trò chuyện mới.</li>
        <li>Khi AI trả lời xong, bấm nút sao chép trên khung code của câu trả lời, rồi dán vào ô dưới đây.</li></ol>
      <div class="acts"><button class="btn primary" id="cbCopy">Sao chép câu lệnh</button>
        <a class="btn" href="https://claude.ai/new" target="ss-chat" rel="noopener">Mở Claude</a>
        <a class="btn" href="https://chatgpt.com/" target="ss-chat" rel="noopener">Mở ChatGPT</a>
        <a class="btn" href="https://gemini.google.com/app" target="ss-chat" rel="noopener">Mở Gemini</a></div>
      <div class="field"><label>Dán câu trả lời của AI (JSON; CSV cũng được)</label><textarea id="cbIn" rows="8" placeholder='{"rows": [{"stt": 1, "mota": "...", "keyword": "...", "keyword_phu": "..."}]}'></textarea></div>
      <p id="cbMsg" class="tiny"></p>
      <div class="end"><button class="btn" data-close>Đóng</button>
        ${state.idx > 0 ? `<button class="btn" id="cbPrev">← Phần trước</button>` : ""}
        <button class="btn primary" id="cbImport">Nhập phần này</button>
        <button class="btn" id="cbNext">${last ? "Hoàn tất" : "Phần tiếp →"}</button></div>`, true);
    $("#cbCopy", d).onclick = async () => {
      const { prompt } = await api.post(`/api/projects/${S.project.id}/chat-prompt`, { profile_id: S.profile.id, stts: part });
      toast((await copyText(prompt)) ? "Đã sao chép câu lệnh. Dán vào chat AI." : "Không sao chép được, thử lại.");
    };
    $("#cbPrev", d)?.addEventListener("click", () => { state.idx--; render(); });
    $("#cbImport", d).onclick = async () => {
      const text = $("#cbIn", d).value.trim(); if (!text) return toast("Dán câu trả lời của AI vào ô trước.");
      const res = await api.post(`/api/projects/${S.project.id}/chat-import`, { text, stts: part });
      res.updated.forEach(x => state.done.add(x));
      $("#cbDone", d).textContent = state.done.size;
      const miss = part.filter(x => !state.done.has(x));
      $("#cbMsg", d).innerHTML = res.updated.length
        ? `<span style="color:var(--green)">Đã nhận ${res.updated.length} dòng.</span>${miss.length ? ` Còn thiếu ${miss.length} dòng: #${miss.join(", #")}. Bấm “Sao chép câu lệnh” lần nữa sẽ chỉ hỏi các dòng còn thiếu.` : ""}`
        : `<span style="color:var(--red)">Không đọc được dòng nào. Hãy dán đúng khung code JSON mà AI trả về.</span>`;
      if (miss.length) parts[state.idx] = miss;
      else if (!last) { state.idx++; setTimeout(render, 900); }
    };
    $("#cbNext", d).onclick = async () => {
      if (!last) { state.idx++; return render(); }
      closeModal();
      const missing = all.filter(x => !state.done.has(x));
      await openProject(S.project.id);
      if (researchAfter && state.done.size) S.rows.forEach((r, i) => { if (state.done.has(r.stt)) { delete r.cands.history; enqueue(i, "history"); } });
      toast(missing.length ? `Xong. ${missing.length} dòng chưa có kết quả từ chat AI, đang giữ từ khóa cũ.` : `Xong. ${state.done.size} dòng đã có mô tả và từ khóa từ chat AI.`, 6000);
    };
  };
  render();
}

/* ---------------- settings ---------------- */
$("#btnProfile").onclick = () => { localStorage.removeItem("ss-profile"); showProfiles(); };
$("#btnSettings").onclick = showSettings;
function showSettings() {
  const s = JSON.parse(JSON.stringify(S.settings)), P = S.meta.providers;
  const tierText = { paid: "trả phí", "low-cost": "giá rẻ", "free-tier": "có gói miễn phí", local: "miễn phí, chạy trên máy", custom: "" };
  const opt = (v, cur) => Object.entries(P).map(([k, p]) => `<option value="${k}" ${k === cur ? "selected" : ""}>${esc(p.label)}</option>`).join("");
  const chainHtml = () => s.ai_chain.map((c, n) => `<div class="item" data-n="${n}">
      <div class="order">${n + 1}</div>
      <select data-f="provider">${opt(0, c.provider)}</select>
      <input data-f="key" type="password" placeholder="${P[c.provider]?.nokey ? "Không cần khóa" : "Khóa API"}" value="${esc(c.key || "")}">
      <div style="display:flex;gap:6px"><input data-f="model" list="ml${n}" placeholder="Model" value="${esc(c.model || "")}" style="flex:1;min-width:0"><datalist id="ml${n}">${(P[c.provider]?.suggest || []).map(m => `<option value="${esc(m)}">`).join("")}</datalist>
        <button class="btn small" data-act="models" title="Tải danh sách model">⟳</button></div>
      <div style="display:flex;gap:4px"><button class="btn small" data-act="test">Thử</button><button class="btn small" data-act="up">↑</button><button class="btn small danger" data-act="rm">✕</button></div>
      ${c.provider === "custom" ? `<input data-f="base" placeholder="Địa chỉ API (base URL)" value="${esc(c.base || "")}" style="grid-column:2/-1">` : ""}
      <div class="muted tiny" style="grid-column:2/-1">${esc(tierText[P[c.provider]?.tier] || "")}${P[c.provider]?.key_url ? ` · <a href="${P[c.provider].key_url}" target="_blank" rel="noopener">lấy khóa / tải</a>` : ""}</div></div>`).join("");
  const d = modal(`<h3>Cài đặt — ${esc(S.profile.name)}</h3>
    <h3>AI phân tích kịch bản</h3>
    <div class="tip">Thứ tự là thứ tự ưu tiên. Nếu nhà cung cấp số 1 lỗi hoặc hết lượt, SceneScout tự chuyển sang số 2, rồi số 3. Gợi ý: ChatGPT / Claude / Gemini đứng đầu nếu có tài khoản trả phí; DeepSeek giá rẻ; Groq, OpenRouter (model đuôi <code>:free</code>), Gemini gói miễn phí, hoặc Ollama trên máy làm dự phòng miễn phí. Khóa chỉ lưu trên máy này.</div>
    <div class="chain" id="chain" style="margin-top:10px">${chainHtml()}</div>
    <div class="acts" style="margin-top:10px"><button class="btn small" id="addAI">+ Thêm nhà cung cấp</button></div>
    <div class="grid2"><div class="field"><label>Ngôn ngữ mô tả cảnh</label><select id="sLang"><option ${s.desc_lang === "Vietnamese" ? "selected" : ""} value="Vietnamese">Tiếng Việt</option><option ${s.desc_lang === "English" ? "selected" : ""} value="English">English</option></select></div>
      <div class="field"><label>Mặc định khi tạo dự án</label><select id="sMode"><option value="quick" ${s.analysis_default === "quick" ? "selected" : ""}>Nhanh</option><option value="ai" ${s.analysis_default === "ai" ? "selected" : ""}>AI</option></select></div></div>
    <div class="grid2"><div class="field"><label>Chat AI: số dòng mỗi phần (mỗi lần dán)</label><input id="sPart" type="number" min="10" step="10" value="${s.chat_part || 50}"></div><div></div></div>
    <details style="margin-top:6px"><summary class="muted">Quy tắc viết từ khóa (nâng cao)</summary>
      <p class="muted tiny">Dùng chung cho AI qua API và chat AI. Giữ nguyên <code>{lang}</code> (ngôn ngữ mô tả) và <code>{onscreen}</code> (chữ “Chữ trên màn hình:”). Để trống = quy tắc mặc định.</p>
      <textarea id="sRules" rows="10" style="width:100%">${esc(s.rules || "")}</textarea>
      <div class="acts" style="margin-top:6px"><button class="btn small" id="sRulesDef">Nạp quy tắc mặc định để sửa</button></div></details>
    <h3>Nguồn ảnh stock (khóa miễn phí)</h3>
    <div class="grid2">${Object.entries(S.meta.keyed_sources).map(([k, url]) => `<div class="field"><label>${k[0].toUpperCase() + k.slice(1)} · <a href="${url}" target="_blank" rel="noopener">lấy khóa</a></label><input type="password" data-key="${k}" value="${esc(s.source_keys[k] || "")}"></div>`).join("")}</div>
    <p class="muted tiny">Wikimedia, Library of Congress và Openverse không cần khóa. Envato Elements không có API tìm kiếm công khai, nên nút Envato mở trang web để bạn kéo ảnh về.</p>
    <h3>Chia dòng và xuất</h3>
    <div class="grid2"><div class="field"><label>Độ dài mỗi dòng (giây, sau phút đầu)</label><div style="display:flex;gap:6px"><input id="sMin" type="number" step="0.5" value="${s.row_min}"><input id="sMax" type="number" step="0.5" value="${s.row_max}"></div></div>
      <div class="field"><label>Thư mục xuất (để trống = Tài liệu/SceneScout/exports)</label><input id="sOut" value="${esc(s.export_root || "")}"></div></div>
    <div class="grid2"><div class="field"><label>Video xuất: khung hình/giây (khớp với dự án của editor)</label><select id="sFps">${[24, 25, 30, 60].map(v => `<option ${+s.video_fps === v ? "selected" : ""}>${v}</option>`).join("")}</select></div>
      <div class="field"><label>Độ phân giải video</label><select id="sRes">${["1920x1080", "3840x2160"].map(v => `<option ${s.video_res === v ? "selected" : ""}>${v}</option>`).join("")}</select></div></div>
    <label class="muted tiny" style="display:block"><input type="checkbox" id="sOpen" ${s.open_folder ? "checked" : ""}> Mở thư mục sau khi xuất</label>
    <label class="muted tiny" style="display:block;margin-top:6px"><input type="checkbox" id="sBadge" ${s.show_used_badge ? "checked" : ""}> Gắn nhãn “đã dùng” cho ảnh từng dùng ở video khác</label>
    <div class="end"><button class="btn" data-close>Hủy</button><button class="btn primary" id="sSave">Lưu</button></div>`, true);
  $("#sRulesDef", d).onclick = async () => { $("#sRules", d).value = (await api.get("/api/rules/default")).rules; };
  const readChain = () => $$("#chain .item", d).forEach(it => { const c = s.ai_chain[+it.dataset.n]; $$("[data-f]", it).forEach(inp => c[inp.dataset.f] = inp.value.trim()); });
  const redraw = () => { $("#chain", d).innerHTML = chainHtml(); };
  $("#addAI", d).onclick = () => { readChain(); s.ai_chain.push({ provider: "groq", key: "", model: "" }); redraw(); };
  $("#chain", d).addEventListener("change", e => { if (e.target.dataset.f === "provider") { readChain(); redraw(); } });
  $("#chain", d).addEventListener("click", async e => {
    const b = e.target.closest("[data-act]"); if (!b) return;
    readChain(); const n = +b.closest(".item").dataset.n, c = s.ai_chain[n];
    if (b.dataset.act === "rm") { s.ai_chain.splice(n, 1); return redraw(); }
    if (b.dataset.act === "up" && n > 0) { [s.ai_chain[n - 1], s.ai_chain[n]] = [s.ai_chain[n], s.ai_chain[n - 1]]; return redraw(); }
    if (b.dataset.act === "models") {
      try {
        const { models } = await api.post("/api/ai/models", { ...c, free_only: c.provider === "openrouter" });
        $(`#ml${n}`, d).innerHTML = models.map(m => `<option value="${esc(m)}">`).join("");
        toast(`${models.length} model. Bấm vào ô Model để chọn.`);
      } catch (err) { toast("Không tải được danh sách: " + err.message, 6000); }
    }
    if (b.dataset.act === "test") {
      b.textContent = "…";
      try { await api.post("/api/ai/test", c); b.textContent = "✓"; toast("Kết nối được."); }
      catch (err) { b.textContent = "✗"; toast("Lỗi: " + err.message, 7000); }
    }
  });
  $("#sSave", d).onclick = async () => {
    readChain();
    // A key without a model is the most common setup mistake: pick one automatically.
    for (const c of s.ai_chain) {
      if (c.model || (!c.key && !P[c.provider]?.nokey)) continue;
      try { const r = await api.post("/api/ai/autopick", c); c.model = r.model; toast(`Đã tự chọn model ${r.model} cho ${P[c.provider].label}`, 5000); }
      catch (err) { toast(`${P[c.provider].label}: không lấy được danh sách model (${err.message}). Kiểm tra khóa.`, 7000); }
    }
    const body = { ai_chain: s.ai_chain.filter(c => c.provider), desc_lang: $("#sLang", d).value, analysis_default: $("#sMode", d).value,
      source_keys: Object.fromEntries($$("[data-key]", d).map(i => [i.dataset.key, i.value.trim()])),
      row_min: +$("#sMin", d).value || 4, row_max: +$("#sMax", d).value || 8, export_root: $("#sOut", d).value.trim(),
      open_folder: $("#sOpen", d).checked, show_used_badge: $("#sBadge", d).checked,
      chat_part: +$("#sPart", d).value || 50, rules: $("#sRules", d).value.trim(),
      video_fps: +$("#sFps", d).value || 30, video_res: $("#sRes", d).value };
    S.settings = await api.put(`/api/profiles/${S.profile.id}/settings`, body);
    closeModal(); toast("Đã lưu cài đặt.");
    if (S.screen === "editor") refreshAll();
  };
}

/* ---------------- help & keyboard ---------------- */
$("#btnHelp").onclick = () => modal(`<h3>Phím tắt</h3><table class="kbd">
  <tr><td>1 – 5</td><td>Chọn ảnh, sang dòng sau</td></tr><tr><td>↓ / Enter</td><td>Dòng sau (giữ ảnh mặc định viền vàng nét đứt)</td></tr>
  <tr><td>↑</td><td>Dòng trước</td></tr><tr><td>N</td><td>5 ảnh tiếp theo</td></tr><tr><td>T</td><td>Đổi tab: Lịch sử → Stock → Đã dùng → Thủ công</td></tr>
  <tr><td>Space</td><td>Xem ảnh mặc định / đã chọn cỡ lớn (nháy đúp vào ảnh bất kỳ cũng được)</td></tr>
  <tr><td>G / V</td><td>Mở Google Images / Envato với từ khóa của dòng</td></tr><tr><td>Ctrl + V</td><td>Dán ảnh hoặc link ảnh vào dòng đang chọn</td></tr>
  <tr><td>A / E</td><td>Đánh dấu Cần ảnh AI / Dùng Envato</td></tr><tr><td>R</td><td>Sửa từ khóa (Enter tìm lại, Esc thoát)</td></tr></table>
  <p class="muted tiny">SceneScout ${esc(S.meta?.version || "")} · Mã nguồn mở</p><div class="end"><button class="btn" data-close>Đóng</button></div>`);
document.addEventListener("keydown", e => {
  if (e.key === "Escape") return closeModal();
  if (S.screen !== "editor" || isTyping(e.target) || e.ctrlKey || e.metaKey || e.altKey || $("#modal").classList.contains("show")) return;
  const i = S.active, r = S.rows[i], key = e.key.toLowerCase();
  if (/^[1-5]$/.test(e.key)) { e.preventDefault(); pick(i, r.page * PER + (+e.key - 1), true); }
  else if (key === "arrowdown" || key === "enter") { e.preventDefault(); setActive(i + 1); }
  else if (key === "arrowup") { e.preventDefault(); setActive(i - 1); }
  else if (key === "n") { r.page = (r.page + 1) % Math.max(1, Math.ceil(visible(r).length / PER)); renderStrip(i); }
  else if (key === "t") { const order = TABS.map(t => t[0]); switchTab(i, order[(order.indexOf(r.tab) + 1) % order.length]); }
  else if (key === " ") { e.preventDefault(); const c = r.sel || r._def; const list = visible(r); const k = c ? list.findIndex(x => x.full === c.full) : 0; preview(i, Math.max(0, k)); }
  else if (key === "g") openGoogle(i);
  else if (key === "v") openEnvato(i);
  else if (key === "a") toggleFlag(i, "AI");
  else if (key === "e") toggleFlag(i, "ENVATO");
  else if (key === "r") { e.preventDefault(); $(`#r${i} input.kw`).focus(); }
});

/* ---------------- desktop app window ---------------- */
window.addEventListener("pywebviewready", () => {
  const b = $("#btnBrowser"); b.classList.remove("hidden");
  b.onclick = () => window.open(location.origin + "/", "_blank");  // opens in the normal browser
});

/* ---------------- boot ---------------- */
(async function boot() {
  S.meta = await api.get("/api/meta");
  const last = localStorage.getItem("ss-profile");
  const list = await api.get("/api/profiles");
  const p = list.find(x => String(x.id) === last);
  if (p) chooseProfile(p); else showProfiles();
})();
