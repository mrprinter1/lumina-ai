const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

async function api(path, opts = {}) {
  const isForm = opts.body instanceof FormData;
  const r = await fetch(path, { ...opts, headers: isForm ? {} : { "Content-Type": "application/json" } });
  if (!r.ok) {
    const detail = (await r.json().catch(() => ({}))).detail;
    throw new Error(typeof detail === "string" ? detail : r.statusText);
  }
  return r.json();
}
const json = (method, body) => ({ method, body: JSON.stringify(body || {}) });

const SHAPES = {
  round: '<circle cx="12" cy="12" r="8"/>',
  oval: '<ellipse cx="12" cy="12" rx="6" ry="9"/>',
  emerald: '<path d="M8 3h8l3 3v12l-3 3H8l-3-3V6z"/><path d="M9 6h6v12H9z"/>',
  cushion: '<rect x="4" y="4" width="16" height="16" rx="5"/>',
  pear: '<path d="M12 3c4 5 7 8 7 12a7 7 0 0 1-14 0c0-4 3-7 7-12z"/>',
  princess: '<rect x="4" y="4" width="16" height="16"/><path d="M4 4l16 16M20 4L4 20"/>',
  marquise: '<path d="M12 2c5 5 5 15 0 20-5-5-5-15 0-20z"/>',
  radiant: '<path d="M7 4h10l3 3v10l-3 3H7l-3-3V7z"/>',
};
const shapeIcon = (id) =>
  `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" aria-hidden="true">${SHAPES[id] || ""}</svg>`;

let meta, settings, current = null, pollTimer = null, step = "design", stageView = "image", currentView = null;
const selections = {};
const busy = (d) => d && (d.status === "queued" || d.status === "working");
const money = (v, cur) => (v || v === 0) && v !== null ? `${Math.round(v).toLocaleString("he-IL")} ${cur}` : "—";
const fileUrl = (d, name) => `/files/${d.id}/${name}?v=${d.updated_at || 0}`;
const labelOf = (cat, id) => (meta.options[cat].items.find((i) => i.id === id) || {}).he || id;
const stageLabel = (id) => (meta.stages.find(([k]) => k === id) || [id, id])[1];

function notice(text, isError = false) {
  const el = $("#notice");
  el.textContent = text || "";
  el.classList.toggle("error", isError);
}

/* ---------- routing ---------- */
function route() {
  const [view, id] = (location.hash.slice(1) || "studio").split("/");
  const v = ["studio", "orders", "settings"].includes(view) ? view : "studio";
  $$(".view").forEach((el) => (el.hidden = el.id !== "view-" + v));
  $$(".topbar nav a").forEach((a) => {
    if (a.dataset.view === v) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  if (v !== currentView) {
    FX.scrollTop();
    const h = $(`#view-${v} h1[data-split]`);
    if (h && v !== "studio") FX.split(h, { duration: 1.3 });
    if (v === "settings") FX.rise($$("#settingsForm fieldset"), { delay: 0.2, stagger: 0.08 });
    currentView = v;
  }
  if (v === "orders") loadOrders(true);
  if (v === "settings") fillSettings();
  if (v === "studio" && id && (!current || current.id !== id)) openDesign(id);
}
window.addEventListener("hashchange", route);

/* ---------- options ---------- */
function renderOptions() {
  const box = $("#optionGroups");
  box.innerHTML = "";
  for (const [key, group] of Object.entries(meta.options)) {
    selections[key] ??= meta.defaults[key];
    const g = document.createElement("div");
    g.className = "group" + (key === "shape" ? " shapes" : "");
    g.innerHTML = `<h3>${group.label}</h3><div class="opts" role="group" aria-label="${group.label}"></div>`;
    for (const item of group.items) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "opt";
      b.dataset.spot = "";
      b.dataset.key = key;
      b.dataset.id = item.id;
      b.innerHTML = (key === "shape" ? shapeIcon(item.id) : "") + `<span>${item.he}</span>`;
      b.onclick = () => { selections[key] = item.id; syncOptions(); FX.sparkAt(b, { count: 7, reach: 22 }); };
      g.querySelector(".opts").appendChild(b);
    }
    box.appendChild(g);
  }
  syncOptions();
}
function syncOptions() {
  $$(".opt").forEach((b) => b.setAttribute("aria-pressed", String(selections[b.dataset.key] === b.dataset.id)));
}

function caption(sel) {
  return `${labelOf("metal", sel.metal)} ${sel.karat}, ${labelOf("shape", sel.shape)} ${labelOf("carat", sel.carat)}, ${labelOf("setting", sel.setting)}`;
}

/* ---------- studio ---------- */
function setStep(s, { animate = true } = {}) {
  const changed = s !== step;
  step = s;
  $$("#steps button").forEach((b) => b.toggleAttribute("aria-current", false));
  $(`#steps [data-step="${s}"]`).setAttribute("aria-current", "step");
  $$(".step").forEach((el) => (el.hidden = el.id !== "step-" + s));
  const el = $("#step-" + s);
  if (animate && changed) {
    FX.split(el.querySelector(".step-title"));
    FX.rise([...el.children].filter((c) => !c.classList.contains("step-title") && !c.hidden), { delay: 0.15 });
  }
}
$$("#steps button").forEach((b) => (b.onclick = () => setStep(b.dataset.step)));

function setStageView(v) {
  stageView = v;
  $$("#stageSwitch button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.show === v)));
  if (current) renderStage(current);
}
$$("#stageSwitch button").forEach((b) => (b.onclick = () => setStageView(b.dataset.show)));

function renderStage(d) {
  const hasImage = !!(d && d.image);
  const hasModel = !!(d && d.spec);
  $("#stageEmpty").hidden = hasImage || busy(d);
  $("#stageSwitch").hidden = !(d && (d.stoneless_image || hasModel));
  $$("#stageSwitch button").forEach((b) => {
    b.hidden = (b.dataset.show === "stoneless" && !d?.stoneless_image) || (b.dataset.show === "model" && !hasModel);
  });
  if (stageView === "model" && !hasModel) stageView = "image";
  if (stageView === "stoneless" && !d?.stoneless_image) stageView = "image";
  const showModel = stageView === "model" && hasModel;
  $("#viewer").hidden = !showModel;
  $("#stagePrint").hidden = !hasImage || showModel;
  if (showModel) {
    const src = fileUrl(d, d.spec.view_glb);
    if ($("#viewer").getAttribute("src") !== src) $("#viewer").setAttribute("src", src);
  } else if (hasImage) {
    const name = stageView === "stoneless" ? d.stoneless_image : d.image;
    const src = fileUrl(d, name);
    const img = $("#stageImage");
    if (img.dataset.file !== name + d.id) {
      img.dataset.file = name + d.id;
      img.onload = () => FX.unveil($("#stagePrint"));
    }
    if (img.getAttribute("src") !== src) img.src = src;
  }
  $("#stageWorking").hidden = !busy(d);
  $("#stage").classList.toggle("working", busy(d) && (hasImage || hasModel));
  $("#stageStep").textContent = busy(d) ? (d.step || "עובד") + "…" : "";
  $("#stageCaption").textContent = d ? caption(d.selections) : "";
}

function render(d) {
  current = d;
  if (d && location.hash !== "#studio/" + d.id) history.replaceState(null, "", "#studio/" + d.id);
  renderStage(d);
  const approved = !!(d && d.approval);

  // step availability
  $(`#steps [data-step="price"]`).disabled = !(d && d.image);
  $(`#steps [data-step="approve"]`).disabled = !(d && d.image);

  // step 1
  $("#generate").textContent = d && d.image && !approved ? "הדמיה חדשה" : "יצירת הדמיה";
  $("#generate").disabled = busy(d) || approved;
  $("#newDesign").hidden = !d;
  $("#optionGroups").inert = approved;

  // step 2
  const q = d ? d.quote : null;
  $("#produce").hidden = !d || !!d.spec;
  $("#produce").disabled = !d || !d.image || busy(d);
  $("#priceIntro").hidden = !d || !!d.spec;
  $("#priceBlock").hidden = !(d && d.spec);
  if (d && d.spec) {
    const cur = q.currency;
    const rows = [
      ["משקל זהב משוער", q.weight_g ? `${q.weight_g} גרם` : "—"],
      [`זהב ${q.alloy.split(" ")[0]}`, q.gold_cost ? money(q.gold_cost, cur) : "צריך להגדיר מחיר גרם"],
      ["אבן", money(q.stone_price, cur)],
      ["עבודה", money(q.labor_cost, cur)],
    ];
    if (q.margin_percent) rows.push(["רווח", `${q.margin_percent}%`]);
    $("#ledger").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
    if (q.final_price) FX.countUp($("#totalPrice"), q.final_price, (v) => money(v, cur));
    else { $("#totalPrice")._value = 0; $("#totalPrice").textContent = "—"; }
    $("#downloadStl").href = `/files/${d.id}/ring.stl`;
    $("#specLink").href = `/designs/${d.id}/spec`;
    $("#warnings").innerHTML = d.spec.warnings.map((w) => `<li>${w.replace(/</g, "&lt;")}</li>`).join("");
    if (document.activeElement !== $("#stonePrice")) $("#stonePrice").value = d.order.stone_price || "";
    if (document.activeElement !== $("#priceOverride")) $("#priceOverride").value = d.order.price_override ?? "";
  }
  $("#uploadGlb").disabled = !d || busy(d);

  // step 3
  $("#approvalDone").hidden = !approved;
  $("#approvalOpen").hidden = approved;
  $("#shareAgain").hidden = !(d && d.share_token);
  if (approved) {
    const a = d.approval;
    const when = new Date(a.at * 1000).toLocaleString("he-IL", { dateStyle: "short", timeStyle: "short" });
    const how = a.channel === "link" ? "דרך הקישור" : "בחנות";
    $("#approvalDone").innerHTML = `<b>העיצוב אושר</b>${escapeHtml(a.name)}, ${when}, ${how}` +
      (a.price ? `. מחיר באישור: ${money(a.price, a.currency)}` : "");
  }
  $("#signHere").disabled = !d || !d.image || busy(d);
  $("#shareLink").disabled = !d || !d.image;
  if (d) {
    $("#orderStage").value = d.order.stage;
    if (document.activeElement !== $("#deposit")) $("#deposit").value = d.order.deposit || "";
    if (document.activeElement !== $("#notes")) $("#notes").value = d.order.notes || "";
  }

  if (!d) notice("");
  else if (d.status === "error") notice("משהו נכשל: " + d.error, true);
  else if (busy(d)) notice("");
  else if (d.image && !d.spec && step === "design") notice("ההדמיה מוכנה. אפשר להמשיך למחיר ולקובץ.");
  else notice("");

  clearTimeout(pollTimer);
  if (busy(d)) pollTimer = setTimeout(async () => {
    try { render(await api(`/api/designs/${d.id}`)); } catch (e) { notice(e.message, true); }
  }, 2000);
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function fillForm(d) {
  Object.assign(selections, d.selections);
  syncOptions();
  $("#clientName").value = d.client.name || "";
  $("#clientPhone").value = d.client.phone || "";
  $("#ringSize").value = d.ring_size;
  $("#freeText").value = d.free_text || "";
}

async function openDesign(id) {
  try {
    const d = await api(`/api/designs/${id}`);
    fillForm(d);
    stageView = "image";
    setStep(d.approval ? "approve" : d.spec ? "price" : "design");
    render(d);
  } catch (e) {
    notice("העיצוב לא נמצא", true);
  }
}

async function run(fn) {
  try { render(await fn()); } catch (e) { notice(e.message, true); }
}

const formBody = () => ({
  selections: { ...selections },
  free_text: $("#freeText").value,
  ring_size: Number($("#ringSize").value),
});

$("#generate").onclick = () => {
  if (!Number($("#ringSize").value)) return notice("צריך למלא מידת טבעת.", true);
  stageView = "image";
  if (current && !current.approval) {
    return run(() => api(`/api/designs/${current.id}/regenerate`, json("POST", formBody())));
  }
  run(() => api("/api/designs", json("POST", {
    ...formBody(), client: { name: $("#clientName").value, phone: $("#clientPhone").value },
  })));
};
$("#newDesign").onclick = () => {
  current = null;
  clearTimeout(pollTimer);
  Object.assign(selections, meta.defaults);
  syncOptions();
  ["#clientName", "#clientPhone", "#freeText"].forEach((s) => ($(s).value = ""));
  history.replaceState(null, "", "#studio");
  setStep("design");
  render(null);
};
$("#produce").onclick = () => current && run(() => api(`/api/designs/${current.id}/produce`, json("POST")));

async function patchOrder(body) {
  if (!current) return;
  try { render(await api(`/api/designs/${current.id}/order`, json("PATCH", body))); } catch (e) { notice(e.message, true); }
}
const clientChange = () => patchOrder({ client: { name: $("#clientName").value, phone: $("#clientPhone").value } });
$("#clientName").addEventListener("change", clientChange);
$("#clientPhone").addEventListener("change", clientChange);
$("#stonePrice").addEventListener("change", (e) => patchOrder({ stone_price: Number(e.target.value) || 0 }));
$("#priceOverride").addEventListener("change", (e) =>
  patchOrder(e.target.value === "" ? { clear_price_override: true } : { price_override: Number(e.target.value) }));
$("#deposit").addEventListener("change", (e) => patchOrder({ deposit: Number(e.target.value) || 0 }));
$("#notes").addEventListener("change", (e) => patchOrder({ notes: e.target.value }));
$("#orderStage").addEventListener("change", (e) => patchOrder({ stage: e.target.value }));

$("#uploadGlb").onclick = () => {
  const f = $("#glbFile").files[0];
  if (!current) return notice("קודם צריך ליצור עיצוב.", true);
  if (!f) return notice("צריך לבחור קובץ GLB.", true);
  const fd = new FormData();
  fd.append("file", f);
  run(() => api(`/api/designs/${current.id}/upload-glb`, { method: "POST", body: fd }));
};

/* ---------- approval & sharing ---------- */
const pad = SignaturePad($("#signPad"));
$("#clearSign").onclick = () => pad.clear();
$("#signCancel").onclick = () => $("#signDialog").close();
$("#signHere").onclick = () => {
  const q = current.quote;
  $("#signSummary").textContent = caption(current.selections) + (q.final_price ? `. מחיר: ${money(q.final_price, q.currency)}` : "");
  $("#signForm").name.value = current.client.name || "";
  $("#signError").textContent = "";
  pad.clear();
  FX.openDialog($("#signDialog"));
};
$("#signForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (pad.isEmpty()) return ($("#signError").textContent = "צריך לחתום במסגרת.");
  try {
    const d = await api(`/api/designs/${current.id}/approve`, json("POST", { name: e.target.name.value, signature: pad.toDataURL() }));
    $("#signDialog").close();
    render(d);
    FX.celebrate($("#stage"));
    FX.rise($("#approvalDone"), { y: 10 });
  } catch (err) {
    $("#signError").textContent = err.message;
  }
});

async function openShare() {
  try {
    const r = await api(`/api/designs/${current.id}/share`, json("POST"));
    $("#shareUrl").value = r.url;
    $("#shareText").value = r.text;
    $("#shareWhatsapp").href = r.whatsapp;
    $("#openLink").href = r.url;
    $("#shareLocal").hidden = !r.is_local;
    FX.openDialog($("#shareDialog"));
    render(r.design);
  } catch (e) { notice(e.message, true); }
}
$("#shareLink").onclick = openShare;
$("#shareAgain").onclick = openShare;
$("#copyLink").onclick = async () => {
  try { await navigator.clipboard.writeText($("#shareUrl").value); $("#copyLink").textContent = "הקישור הועתק"; }
  catch { $("#shareUrl").select(); }
  setTimeout(() => ($("#copyLink").textContent = "העתקת הקישור"), 1800);
};

/* ---------- orders ---------- */
async function loadOrders(entering = false) {
  const list = await api("/api/designs");
  const filter = $("#stageFilter").value;
  const rows = list.filter((d) => !filter || d.order.stage === filter);
  const box = $("#orderList");
  if (!rows.length) {
    box.innerHTML = `<p class="empty">${list.length ? "אין הזמנות בשלב הזה." : "עוד אין הזמנות. עיצוב ראשון מתחיל בסטודיו."}</p>`;
    return;
  }
  box.innerHTML = "";
  for (const d of rows) {
    const b = document.createElement("button");
    b.className = "order-row";
    b.dataset.spot = "";
    const when = new Date(d.created_at * 1000).toLocaleDateString("he-IL");
    b.innerHTML =
      (d.image ? `<img src="/files/${d.id}/${d.image}" alt="">` : '<span class="ph"></span>') +
      `<span><span class="who">${escapeHtml(d.client.name || "ללא שם")}</span><br><span class="meta">${caption(d.selections)}, ${when}</span></span>` +
      `<span class="stage-tag s-${d.order.stage}">${stageLabel(d.order.stage)}</span>` +
      `<span class="amount">${d.quote.final_price ? money(d.quote.final_price, d.quote.currency) : ""}</span>`;
    b.onclick = () => (location.hash = "#studio/" + d.id);
    box.appendChild(b);
  }
  if (entering) FX.rise($$(".order-row"), { delay: 0.25, stagger: 0.06, y: 24 });
}
$("#stageFilter").onchange = () => loadOrders(true);

/* ---------- settings ---------- */
function applyBrand() {
  $("#brandName").textContent = settings.business_name || "Lumina";
  const img = $("#brandLogo");
  img.hidden = !settings.has_logo;
  if (settings.has_logo) img.src = "/brand/logo?v=" + Date.now();
  $("#sizeSystemLabel").textContent = meta.size_systems[settings.size_system];
  document.title = (settings.business_name || "Lumina") + " – סטודיו";
}
function fillSettings() {
  const f = $("#settingsForm");
  for (const k of ["business_name", "business_phone", "public_url", "share_message", "currency", "labor_cost",
    "margin_percent", "wax_shrink", "size_system"]) f[k].value = settings[k] ?? "";
  for (const k of ["client_sees_specs", "client_sees_price", "client_sees_weight"]) f[k].checked = !!settings[k];
  f.gold14.value = settings.gold_price_per_gram["14K"] || "";
  f.gold18.value = settings.gold_price_per_gram["18K"] || "";
  $("#settingsSaved").textContent = "";
}
$("#settingsForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    settings = await api("/api/settings", json("PUT", {
      business_name: f.business_name.value.trim(),
      business_phone: f.business_phone.value.trim(),
      public_url: f.public_url.value.trim(),
      share_message: f.share_message.value,
      client_sees_specs: f.client_sees_specs.checked,
      client_sees_price: f.client_sees_price.checked,
      client_sees_weight: f.client_sees_weight.checked,
      currency: f.currency.value || "₪",
      gold_price_per_gram: { "14K": Number(f.gold14.value) || 0, "18K": Number(f.gold18.value) || 0 },
      labor_cost: Number(f.labor_cost.value) || 0,
      margin_percent: Number(f.margin_percent.value) || 0,
      wax_shrink: Number(f.wax_shrink.value) || 1,
      size_system: f.size_system.value,
    }));
    const logo = $("#logoFile").files[0];
    if (logo) {
      const fd = new FormData();
      fd.append("file", logo);
      settings = await api("/api/settings/logo", { method: "POST", body: fd });
      $("#logoFile").value = "";
    }
    applyBrand();
    $("#settingsSaved").textContent = "ההגדרות נשמרו.";
    FX.sparkAt(e.submitter || f.querySelector("[type=submit]"), { count: 10, reach: 34 });
  } catch (err) {
    $("#settingsSaved").textContent = err.message;
  }
});

/* ---------- boot ---------- */
(async () => {
  if (!FX.animate) document.documentElement.classList.add("no-motion");
  FX.smoothScroll();
  FX.spotlight();
  [meta, settings] = await Promise.all([api("/api/meta"), api("/api/settings")]);
  for (const [k, v] of Object.entries(meta.size_systems)) $("#sizeSystem").add(new Option(v, k));
  for (const [k, v] of meta.stages) {
    $("#orderStage").add(new Option(v, k));
    $("#stageFilter").add(new Option(v, k));
  }
  const p = meta.providers;
  if (p.image === "mock" || p.model3d === "mock") {
    $("#providers").hidden = false;
    $("#providers").textContent = "מצב הדגמה: התמונות והתלת-ממד אינם אמיתיים";
  }
  renderOptions();
  applyBrand();
  render(null);
  setStep("design", { animate: false });
  route();
  ["#generate", "#produce", "#signHere"].forEach((s) => FX.magnet($(s)));
  // the one orchestrated moment: lights come on in the vitrine
  const words = [currentView === "studio" && !current ? $("#stageEmpty h1") : null, $("#step-design .step-title")].filter(Boolean);
  FX.lightsOn({ curtain: $("#curtain"), words, rest: [$(".steps"), ...$("#step-design").children].filter((c) => !c.classList.contains("step-title")) });
})();
