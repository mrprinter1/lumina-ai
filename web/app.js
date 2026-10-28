const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

async function api(path, opts = {}) {
  const isForm = opts.body instanceof FormData;
  const r = await fetch(path, { ...opts, headers: isForm ? {} : { "Content-Type": "application/json" } });
  if (r.status === 401) { location.href = "/login"; throw new Error("צריך להתחבר מחדש"); }
  if (!r.ok) {
    const detail = (await r.json().catch(() => ({}))).detail;
    throw new Error(typeof detail === "string" ? detail : r.statusText);
  }
  const body = await r.json();
  if (body && body.server_now) clockSkew = Date.now() / 1000 - body.server_now;
  return body;
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
let clockSkew = 0, progressTimer = null, wasBusy = false;
const selections = {};
const busy = (d) => d && (d.status === "queued" || d.status === "working");
const money = (v, cur) => (v || v === 0) && v !== null ? `${Math.round(v).toLocaleString("he-IL")} ${cur}` : "—";
// version files by the job that wrote them, so polling and price edits don't re-download images and models
const fileUrl = (d, name) => `/files/${d.id}/${name}?v=${Math.round(d.progress?.started_at || d.created_at)}`;
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
const PREVIEW_KEYS = ["shape", "setting", "band"];
function renderOptions() {
  const box = $("#optionGroups");
  box.innerHTML = "";
  for (const [key, group] of Object.entries(meta.options)) {
    selections[key] ??= meta.defaults[key];
    const g = document.createElement("div");
    g.className = "group" + (key === "shape" ? " shapes" : "");
    g.innerHTML = `<h3>${group.label}</h3>` + (PREVIEW_KEYS.includes(key) ? previewPanel(key) : "") +
      `<div class="opts" role="group" aria-label="${group.label}"></div>`;
    for (const item of group.items) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "opt";
      b.dataset.spot = "";
      b.dataset.key = key;
      b.dataset.id = item.id;
      b.innerHTML = (key === "shape" ? shapeIcon(item.id) : key === "metal" ? `<i class="sw sw-${item.id}" aria-hidden="true"></i>` : "") +
        `<span>${item.he}</span>`;
      b.onclick = () => { selections[key] = item.id; syncOptions(); FX.sparkAt(b, { count: 7, reach: 22 }); };
      if (PREVIEW_KEYS.includes(key)) {
        // desktop: the preview follows the pointer; touch: it follows the selection (a tap selects)
        b.addEventListener("pointerenter", (e) => e.pointerType === "mouse" && showPreview(key, item.id));
        b.addEventListener("pointerleave", (e) => e.pointerType === "mouse" && showPreview(key, selections[key]));
        b.addEventListener("focus", () => showPreview(key, item.id));
        b.addEventListener("blur", () => showPreview(key, selections[key]));
      }
      g.querySelector(".opts").appendChild(b);
    }
    box.appendChild(g);
  }
  syncOptions();
}
function syncOptions() {
  $$(".opt").forEach((b) => b.setAttribute("aria-pressed", String(selections[b.dataset.key] === b.dataset.id)));
  PREVIEW_KEYS.forEach((k) => showPreview(k, selections[k]));
}

/* ---------- option previews ----------
   Each shape, setting and band can show a photo (made once by scripts/make_catalog_images.py, listed in
   meta.previews) with a one-line description. Until a photo exists: shapes show a turning 3D model,
   settings and bands show just the description. */
function previewPanel(key) {
  const viewer = key === "shape"
    ? `<model-viewer auto-rotate rotation-per-second="38deg" camera-orbit="25deg 66deg 112%" interaction-prompt="none"
         disable-zoom disable-pan exposure="1.25" shadow-intensity="0" environment-image="gems/env.jpg" alt="" loading="eager" hidden></model-viewer>` : "";
  return `<div class="gem" id="pv-${key}" aria-live="polite">
    <div class="gem-media"><img alt="" hidden>${viewer}</div>
    <div class="gem-text"><b></b><p></p><small hidden></small></div>
  </div>`;
}
function stoneSize(item, carat) {
  // stone width and length scale with the cube root of weight; 1 carat sizes are typical, not exact
  const k = Math.cbrt(Number(carat) || 1);
  const [w, l] = item.dims_1ct.map((v) => Math.round(v * k * 10) / 10);
  return w === l ? `${w} מ״מ` : `${l} × ${w} מ״מ`;
}
function showPreview(key, id) {
  const box = $(`#pv-${key}`);
  if (!box || !meta || !id) return;
  const item = meta.options[key].items.find((i) => i.id === id);
  if (!item) return;
  box.classList.toggle("peek", id !== selections[key]);
  box.querySelector("b").textContent = item.he;
  box.querySelector("p").textContent = item.blurb || "";
  const size = box.querySelector("small");
  size.hidden = key !== "shape";
  if (key === "shape") {
    const carat = selections.carat || meta.defaults.carat;
    size.textContent = `בערך ${stoneSize(item, carat)} ב-${labelOf("carat", carat)}`;
  }
  const img = box.querySelector("img"), viewer = box.querySelector("model-viewer");
  const photos = meta.previews?.[key] || [];
  const hasPhoto = photos.includes(id);
  const hasModel = key === "shape";
  img.hidden = !hasPhoto;
  if (viewer) viewer.hidden = hasPhoto || !hasModel;
  // the panel keeps one height per category, or the buttons below would jump out from under the pointer on hover:
  // the picture slot stays (empty if this option has no photo) whenever any option of the category has one
  box.classList.toggle("no-media", !photos.length && !hasModel);
  if (hasPhoto) {
    const src = `catalog/${key}/${id}.jpg`;
    if (img.getAttribute("src") !== src) { img.setAttribute("src", src); img.alt = item.he; }
  } else if (viewer) {
    const src = `gems/${id}.glb`;
    if (viewer.getAttribute("src") !== src) viewer.setAttribute("src", src);
  }
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
$$("#steps button").forEach((b) => (b.onclick = () => { setStep(b.dataset.step); if (current) render(current); }));

function setStageView(v) {
  stageView = v;
  $$("#stageSwitch button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.show === v)));
  if (current) renderStage(current);
}
$$("#stageSwitch button").forEach((b) => (b.onclick = () => setStageView(b.dataset.show)));

/* ---------- progress ----------
   The server stores a plan of steps with expected durations (learned from past runs).
   The browser extrapolates between polls so the percentage moves smoothly. */
const activeStep = (d) => (d?.progress?.steps || []).find((s) => s.state === "active");

function stepFraction(s, now) {
  if (s.state === "done") return 1;
  if (s.state !== "active" || !s.started_at) return 0;
  if (s.pct != null) return Math.min(s.pct / 100, 0.99);
  const x = (now - s.started_at) / s.expected_s;
  // linear up to 85%, then creeps toward 99% so a slow run never looks frozen or finished
  return x < 0.85 ? x : 0.85 + 0.14 * (1 - Math.exp(-(x - 0.85) * 2.5));
}

function progressOf(d) {
  const steps = d?.progress?.steps;
  if (!steps || !steps.length) return null;
  const now = Date.now() / 1000 - clockSkew;
  let total = 0, done = 0, remaining = 0;
  for (const s of steps) {
    const f = stepFraction(s, now);
    total += s.expected_s;
    done += f * s.expected_s;
    if (s.state === "pending") remaining += s.expected_s;
    if (s.state === "active") remaining += Math.max(s.expected_s - (now - (s.started_at || now)), 0);
  }
  return { pct: Math.min(99, Math.floor((done / total) * 100)), remaining, steps, now };
}

function etaText(sec) {
  if (sec < 8) return "עוד רגע…";
  if (sec < 60) return "פחות מדקה";
  const m = Math.round(sec / 60);
  return m === 1 ? "בערך דקה" : `בערך ${m} דקות`;
}

function paintProgress() {
  const d = current;
  if (!busy(d)) return;
  const p = progressOf(d);
  const a = activeStep(d);
  $("#stageStep").textContent = (a ? d.step || a.label : "ממתינים בתור") + "…";
  if (!p) return;
  $("#stagePct").textContent = p.pct + "%";
  $("#stageBar").style.width = p.pct + "%";
  const n = p.steps.length, i = p.steps.findIndex((s) => s.state === "active");
  $("#stageEta").textContent = (n > 1 && i >= 0 ? `שלב ${i + 1} מתוך ${n} · ` : "") + etaText(p.remaining);
  $$("#pipeline li").forEach((li, i) => {
    const s = p.steps[i];
    if (s) li.querySelector(".p").textContent = s.state === "active" ? Math.floor(stepFraction(s, p.now) * 100) + "%" : "";
  });
}

function renderPipeline(d) {
  const steps = d?.progress?.steps || [];
  const production = steps.some((s) => s.key === "mesh");
  const show = !!(d && production && (busy(d) || d.status === "error"));
  $("#pipeline").hidden = !show;
  if (!show) return;
  const sig = steps.map((s) => s.key + s.state).join();
  if ($("#pipeline").dataset.sig !== sig) {
    $("#pipeline").dataset.sig = sig;
    $("#pipeline").innerHTML = steps.map((s) =>
      `<li class="${s.state}"><span>${escapeHtml(s.label)}</span><span class="p"></span></li>`).join("");
  }
}

function renderStage(d) {
  const hasImage = !!(d && d.image);
  const hasModel = !!(d && d.spec);
  const a = busy(d) ? activeStep(d) : null;
  // "model" is the generator's textured model (what the client approved, smooth to the eye);
  // "production" is the scaled, closed STL that gets printed, shown raw so the jeweler can judge it
  const hasSource = !!(d && d.glb_source);
  const sources = {
    model: hasSource ? fileUrl(d, "source.glb") : null,
    production: hasModel ? fileUrl(d, d.spec.view_glb) : null,
  };
  let view = stageView;
  // while the file is being built, show what the machine is working from
  if (a && a.key === "model3d" && d.stoneless_image) view = "stoneless";
  if (a && a.key === "mesh" && hasSource) view = "model";
  $("#stageEmpty").hidden = hasImage || busy(d);
  $("#stageSwitch").hidden = busy(d) || !(d && (d.stoneless_image || hasSource || hasModel));
  $$("#stageSwitch button").forEach((b) => {
    const k = b.dataset.show;
    b.hidden = (k === "stoneless" && !d?.stoneless_image) || ((k === "model" || k === "production") && !sources[k]);
  });
  if ((view === "model" || view === "production") && !sources[view]) view = "image";
  if (view === "stoneless" && !d?.stoneless_image) view = "image";
  const showModel = view === "model" || view === "production";
  const modelSrc = showModel ? sources[view] : null;
  $("#viewer").hidden = !showModel;
  $("#stagePrint").hidden = !hasImage || showModel;
  if (showModel) {
    if ($("#viewer").getAttribute("src") !== modelSrc) $("#viewer").setAttribute("src", modelSrc);
  } else if (hasImage) {
    const name = view === "stoneless" ? d.stoneless_image : d.image;
    const src = fileUrl(d, name);
    const img = $("#stageImage");
    if (img.getAttribute("src") !== src) {
      img.onload = () => FX.unveil($("#stagePrint"));
      img.src = src;
    }
  }
  $("#stageWorking").hidden = !busy(d);
  $("#stage").classList.toggle("working", busy(d));
  $("#stage").classList.toggle("has-content", hasImage || showModel);
  $("#stagePrint").classList.toggle("scanning", !!(a && a.key !== "image"));
  $("#stageCaption").textContent = d ? caption(d.selections) : "";
  clearInterval(progressTimer);
  if (busy(d)) {
    paintProgress();
    progressTimer = setInterval(paintProgress, 250);
  }
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
  $("#deleteDesign").hidden = !d;
  $("#optionGroups").inert = approved;

  // what to do next, at the bottom of the step where the eyes already are
  $("#nextDesign").hidden = !(d && d.image && !busy(d) && step === "design");
  $("#nextPrice").hidden = !(d && d.image && !busy(d) && step === "price");

  // step 2: production file
  const q = d ? d.quote : null;
  const producing = busy(d) && (d.progress?.steps || []).some((s) => s.key === "mesh");
  $("#produce").hidden = !d || !!d.spec || producing;
  $("#produce").disabled = !d || !d.image || busy(d);
  $("#produce").textContent = d && d.status === "error" && d.stoneless_image ? "ניסיון חוזר" : "הכנת קובץ ייצור";
  $("#priceIntro").hidden = !d || !!d.spec || producing;
  renderPipeline(d);
  $("#fileReady").hidden = !(d && d.spec);
  $("#reprocess").disabled = busy(d);
  if (d && d.spec) {
    $("#downloadStl").href = `/files/${d.id}/ring.stl`;
    $("#specLink").href = `/designs/${d.id}/spec`;
    $("#warnings").innerHTML = d.spec.warnings.map((w) => `<li>${escapeHtml(w)}</li>`).join("");
  }
  $("#uploadGlb").disabled = !d || busy(d);

  // step 2: price. The jeweler sets it; the client sees it only after "send".
  $("#priceBlock").hidden = !(d && d.image);
  if (d && d.image) {
    const cur = q.currency;
    const rows = [];
    if (d.spec) {
      rows.push(["משקל זהב משוער", q.weight_g ? `${q.weight_g} גרם` : "—"]);
      const goldName = `${labelOf("metal", d.selections.metal)} ${d.selections.karat}`;
      rows.push([goldName, q.gold_cost ? money(q.gold_cost, cur) : `צריך להגדיר מחיר לגרם ל${goldName} בהגדרות`]);
    }
    if (q.stone_price) rows.push(["אבן", money(q.stone_price, cur)]);
    if (q.labor_cost) rows.push(["עבודה", money(q.labor_cost, cur)]);
    if (q.margin_percent && q.computed_price) rows.push(["רווח", `${q.margin_percent}%`]);
    if (q.computed_price) rows.push(["מחיר מחושב", money(q.computed_price, cur)]);
    $("#ledger").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
    $("#ledger").hidden = !rows.length;
    if (q.final_price) FX.countUp($("#totalPrice"), q.final_price, (v) => money(v, cur));
    else { $("#totalPrice")._value = 0; $("#totalPrice").textContent = "—"; }
    $("#priceOverride").placeholder = q.computed_price ? String(q.computed_price) : "";
    $("#priceHint").textContent = q.computed_price
      ? "אם לא תקבעו מחיר, יישלח המחיר המחושב."
      : d.spec ? "כדי לקבל מחיר מחושב, הגדירו מחיר לגרם זהב בהגדרות. אפשר גם לקבוע מחיר ידני."
        : "המחיר המחושב יופיע אחרי הכנת קובץ הייצור. אפשר לקבוע מחיר כבר עכשיו.";
    if (document.activeElement !== $("#stonePrice")) $("#stonePrice").value = d.order.stone_price || "";
    if (document.activeElement !== $("#priceOverride")) $("#priceOverride").value = d.order.price_override ?? "";
    const pub = q.published;
    const sentAt = pub ? new Date(pub.at * 1000).toLocaleDateString("he-IL") : "";
    $("#publishState").className = "publish-state" + (q.published_stale ? " stale" : pub ? " sent" : "");
    $("#publishState").textContent = !pub ? "הלקוח עדיין לא רואה מחיר."
      : q.published_stale ? `שיניתם את המחיר אחרי השליחה. הלקוח עדיין רואה ${money(pub.total, pub.currency)}.`
        : `נשלח ללקוח ב-${sentAt}: ${money(pub.total, pub.currency)}`;
    $("#publishPrice").textContent = !pub ? "שליחת הצעת המחיר ללקוח" : q.published_stale ? "שליחת המחיר המעודכן" : "שליחת הקישור שוב";
    $("#publishPrice").disabled = !q.final_price || approved;
    $("#unpublishPrice").hidden = !pub || approved;
    $("#stonePrice").disabled = $("#priceOverride").disabled = approved;
  }

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
  else if (d.image && !d.spec && step === "design") notice("ההדמיה מוכנה. לחצו על \"המשך\" למטה כדי להכין קובץ ומחיר.");
  else notice("");

  // finished building the file: turn the stage to the 3D model once
  if (wasBusy && d && !busy(d) && d.spec && step === "price") setStageView("model");
  // finished the picture: take the jeweler to the button that continues, instead of leaving them to find the tabs
  if (wasBusy && d && !busy(d) && d.image && !d.spec && step === "design" && d.status === "image_ready") {
    const box = $("#nextDesign");
    box.classList.remove("attn"); void box.offsetWidth; box.classList.add("attn");
    setTimeout(() => FX.scrollTo(box), 350);
  }
  wasBusy = busy(d);

  clearTimeout(pollTimer);
  if (busy(d)) pollTimer = setTimeout(() => poll(d.id), 2000);
}

// keep polling through hiccups (server busy with a mesh, laptop asleep): one failed request must not freeze the screen
async function poll(id, failures = 0) {
  if (!current || current.id !== id) return;
  try {
    render(await api(`/api/designs/${id}`));
  } catch (e) {
    if (failures >= 2) notice("אין חיבור לשרת. בודקים שוב…", true);
    pollTimer = setTimeout(() => poll(id, failures + 1), Math.min(2000 * 2 ** failures, 15000));
  }
}
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "visible" && current && busy(current)) { clearTimeout(pollTimer); poll(current.id); }
});

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
  $("#engraving").value = d.engraving || "";
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
  engraving: $("#engraving").value,
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
// a blank order: forget the open one (it stays in the orders list) and reset every choice to its default
function startNew() {
  current = null;
  clearTimeout(pollTimer);
  Object.assign(selections, meta.defaults);
  syncOptions();
  ["#clientName", "#clientPhone", "#freeText", "#engraving"].forEach((s) => ($(s).value = ""));
  $("#ringSize").value = 54;
  setStep("design");
  render(null);
  if (location.hash !== "#studio") location.hash = "#studio";
  FX.scrollTop();
}
$("#newDesign").onclick = startNew;
$("#newOrder").onclick = startNew;

/* ---------- delete an order ---------- */
let deleting = null;
function askDelete(d) {
  deleting = d;
  $("#deleteText").textContent = `למחוק את ההזמנה של ${d.client.name || "לקוח ללא שם"}? אי אפשר לשחזר אותה.`;
  const warn = $("#deleteWarn");
  warn.hidden = !d.approval;
  warn.textContent = d.approval ? "הלקוח כבר אישר את העיצוב בחתימה. המחיקה מוחקת גם את החתימה ואת האישור." : "";
  $("#deleteError").textContent = "";
  $("#deleteConfirm").disabled = false;
  FX.openDialog($("#deleteDialog"));
}
$("#deleteCancel").onclick = () => $("#deleteDialog").close();
$("#deleteDesign").onclick = () => current && askDelete(current);
$("#deleteConfirm").onclick = async () => {
  if (!deleting) return;
  $("#deleteConfirm").disabled = true;
  try {
    await api(`/api/designs/${deleting.id}`, { method: "DELETE" });
    const wasCurrent = current && current.id === deleting.id;
    deleting = null;
    $("#deleteDialog").close();
    if (wasCurrent) startNew();
    if (!$("#view-orders").hidden) loadOrders();
    notice("ההזמנה נמחקה.");
  } catch (e) {
    $("#deleteError").textContent = e.message;
    $("#deleteConfirm").disabled = false;
  }
};
$("#toPrice").onclick = () => { setStep("price"); FX.scrollTop(); render(current); };
$("#toApprove").onclick = () => { setStep("approve"); FX.scrollTop(); render(current); };
$("#produce").onclick = () => current && run(() => api(`/api/designs/${current.id}/produce`, json("POST")));
// rebuilds the STL from the model already received: no new API cost
$("#reprocess").onclick = () => current && run(() => api(`/api/designs/${current.id}/reprocess`, json("POST")));
$("#publishPrice").onclick = async () => {
  if (!current) return;
  try {
    render(await api(`/api/designs/${current.id}/price`, json("POST", { publish: true })));
    FX.sparkAt($("#publishPrice"), { count: 10, reach: 30 });
    openShare();
  } catch (e) { notice(e.message, true); }
};
$("#unpublishPrice").onclick = () => current && run(() => api(`/api/designs/${current.id}/price`, json("POST", { publish: false })));

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
    const item = document.createElement("div");
    item.className = "order-item";
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
    const del = document.createElement("button");
    del.className = "order-del hit";
    del.type = "button";
    del.setAttribute("aria-label", `מחיקת ההזמנה של ${d.client.name || "לקוח ללא שם"}`);
    del.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M5 7h14M10 7V5h4v2M7 7l1 12h8l1-12M10 11v5M14 11v5"/></svg>';
    del.onclick = () => askDelete(d);
    item.append(b, del);
    box.appendChild(item);
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
  document.documentElement.dataset.logo = settings.logo_background || "light";
  $("#sizeSystemLabel").textContent = meta.size_systems[settings.size_system];
  document.title = (settings.business_name || "Lumina") + " – סטודיו";
}
function showLogoPreview(file) {
  const box = $("#logoPreviewBox"), img = $("#logoPreview");
  if (file) img.src = URL.createObjectURL(file);
  else if (settings.has_logo) img.src = "/brand/logo?v=" + Date.now();
  box.hidden = !(file || settings.has_logo);
  $("#removeLogo").hidden = !settings.has_logo;
}
$("#logoFile").addEventListener("change", (e) => { if (e.target.files[0]) showLogoPreview(e.target.files[0]); });
$("#removeLogo").onclick = async () => {
  try {
    settings = await api("/api/settings/logo", { method: "DELETE" });
    $("#logoFile").value = "";
    applyBrand();
    showLogoPreview();
    $("#settingsSaved").textContent = "הלוגו הוסר.";
  } catch (e) { $("#settingsSaved").textContent = e.message; }
};
function fillSettings() {
  const f = $("#settingsForm");
  for (const k of ["business_name", "business_phone", "public_url", "share_message", "currency", "labor_cost",
    "margin_percent", "wax_shrink", "size_system"]) f[k].value = settings[k] ?? "";
  for (const k of ["client_sees_specs", "client_sees_weight"]) f[k].checked = !!settings[k];
  const gp = settings.gold_price_per_gram || {};
  for (const k of ["14K", "18K"]) for (const m of ["yellow", "white", "rose"]) {
    f[`gold_${k}_${m}`].value = gp[`${k} ${m}`] || gp[k] || "";  // older saves had one price per karat
  }
  f.logo_background.value = settings.logo_background || "light";
  showLogoPreview();
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
      client_sees_weight: f.client_sees_weight.checked,
      currency: f.currency.value || "₪",
      gold_price_per_gram: Object.fromEntries(["14K", "18K"].flatMap((k) =>
        ["yellow", "white", "rose"].map((m) => [`${k} ${m}`, Number(f[`gold_${k}_${m}`].value) || 0]))),
      logo_background: f.logo_background.value,
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
    showLogoPreview();
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
  $("#logout").hidden = !meta.login;
  // warm the cache so switching the preview doesn't flash
  meta.options.shape.items.forEach((i) => fetch(`gems/${i.id}.glb`).catch(() => {}));
  for (const k of PREVIEW_KEYS) (meta.previews?.[k] || []).forEach((id) => { new Image().src = `catalog/${k}/${id}.jpg`; });
  renderOptions();
  applyBrand();
  render(null);
  setStep("design", { animate: false });
  route();
  ["#generate", "#produce", "#signHere", "#publishPrice"].forEach((s) => FX.magnet($(s)));
  // split headings only after the display font is in, or the words get measured in the fallback font
  await Promise.race([document.fonts?.ready, new Promise((r) => setTimeout(r, 1500))]);
  // the one orchestrated moment: lights come on in the vitrine
  const words = [currentView === "studio" && !current ? $("#stageEmpty h1") : null, $("#step-design .step-title")].filter(Boolean);
  FX.lightsOn({ curtain: $("#curtain"), words, rest: [$(".steps"), ...$("#step-design").children].filter((c) => !c.classList.contains("step-title")) });
})();
