/* Lumina FX – motion layer on GSAP + Lenis, with small vanilla ports of react-bits ideas
   (SplitText reveal, ShinyText, Spotlight, Magnet, ClickSpark, CountUp).
   Everything degrades to a static page when the libraries are missing or motion is reduced. */
const FX = (() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  const finePointer = matchMedia("(pointer: fine)").matches;
  const G = typeof gsap !== "undefined" ? gsap : null;
  if (G && window.ScrollTrigger) G.registerPlugin(ScrollTrigger);
  if (G && window.SplitText) G.registerPlugin(SplitText);
  const animate = !!G && !reduce;

  /* ---- smooth scroll (Lenis) ---- */
  let lenis = null;
  function smoothScroll() {
    if (reduce || typeof Lenis === "undefined") return null;
    lenis = new Lenis({ lerp: 0.085, smoothWheel: true });
    if (G) {
      lenis.on("scroll", () => window.ScrollTrigger && ScrollTrigger.update());
      G.ticker.add((t) => lenis.raf(t * 1000));
      G.ticker.lagSmoothing(0);
    } else {
      const raf = (t) => { lenis.raf(t); requestAnimationFrame(raf); };
      requestAnimationFrame(raf);
    }
    return lenis;
  }
  const scrollTop = () => (lenis ? lenis.scrollTo(0, { immediate: true }) : window.scrollTo(0, 0));

  /* ---- SplitText: words rise out of a mask ---- */
  function split(el, { delay = 0, stagger = 0.06, duration = 1.1 } = {}) {
    if (!el) return null;
    if (el._split) { el._split.revert(); el._split = null; }
    el.style.visibility = "visible";
    if (!animate || !window.SplitText) return null;
    el._split = SplitText.create(el, { type: "words", mask: "words" });
    return G.from(el._split.words, { yPercent: 115, duration, ease: "expo.out", stagger, delay });
  }

  /* ---- staggered entrance for a group of children ---- */
  function rise(targets, { delay = 0, y = 18, stagger = 0.05 } = {}) {
    if (!animate) return null;
    return G.from(targets, { y, autoAlpha: 0, duration: 0.8, ease: "power3.out", stagger, delay, clearProps: "transform,opacity,visibility" });
  }

  /* ---- unveil: an image appearing like a cloth lifted off a tray ---- */
  function unveil(el) {
    if (!animate || !el) return;
    G.fromTo(el,
      { clipPath: "inset(48% 0% 48% 0%)", filter: "blur(14px) brightness(1.4)", scale: 1.06 },
      { clipPath: "inset(0% 0% 0% 0%)", filter: "blur(0px) brightness(1)", scale: 1, duration: 1.6, ease: "expo.out", clearProps: "clipPath,filter" });
  }

  /* ---- CountUp ---- */
  function countUp(el, to, format) {
    if (!el) return;
    const from = el._value ?? 0;
    el._value = to;
    if (!animate || from === to) { el.textContent = format(to); return; }
    const box = { v: from };
    G.to(box, { v: to, duration: 1.3, ease: "power3.out", onUpdate: () => (el.textContent = format(box.v)) });
  }

  /* ---- Spotlight: radial light that follows the pointer inside [data-spot] ---- */
  function spotlight() {
    let frame = 0, ev = null;
    document.addEventListener("pointermove", (e) => {
      ev = e;
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        const el = ev.target.closest && ev.target.closest("[data-spot]");
        if (!el) return;
        const r = el.getBoundingClientRect();
        el.style.setProperty("--mx", `${ev.clientX - r.left}px`);
        el.style.setProperty("--my", `${ev.clientY - r.top}px`);
      });
    }, { passive: true });
  }

  /* ---- Magnet: primary buttons lean toward the pointer ---- */
  function magnet(el, strength = 0.28) {
    if (!animate || !finePointer || !el || el._magnet) return;
    el._magnet = true;
    const x = G.quickTo(el, "x", { duration: 0.6, ease: "power3.out" });
    const y = G.quickTo(el, "y", { duration: 0.6, ease: "power3.out" });
    el.addEventListener("pointermove", (e) => {
      if (el.disabled) return;
      const r = el.getBoundingClientRect();
      x((e.clientX - (r.left + r.width / 2)) * strength);
      y((e.clientY - (r.top + r.height / 2)) * strength);
    });
    el.addEventListener("pointerleave", () => { x(0); y(0); });
  }

  /* ---- ClickSpark: gold sparks drawn on a full-screen canvas ---- */
  let canvas, ctx, sparks = [], running = false;
  function ensureCanvas() {
    if (canvas) return;
    canvas = document.createElement("canvas");
    canvas.className = "fx-sparks";
    canvas.setAttribute("aria-hidden", "true");
    document.body.appendChild(canvas);
    ctx = canvas.getContext("2d");
    const size = () => {
      const d = devicePixelRatio || 1;
      canvas.width = innerWidth * d; canvas.height = innerHeight * d;
      ctx.setTransform(d, 0, 0, d, 0, 0);
    };
    size();
    addEventListener("resize", size);
  }
  function tick(now) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    sparks = sparks.filter((s) => now - s.t0 < s.life);
    for (const s of sparks) {
      const p = (now - s.t0) / s.life, e = 1 - Math.pow(1 - p, 3);
      const d = e * s.reach, len = s.len * (1 - e);
      ctx.strokeStyle = `rgba(${s.rgb},${1 - p})`;
      ctx.lineWidth = s.w;
      ctx.beginPath();
      ctx.moveTo(s.x + Math.cos(s.a) * d, s.y + Math.sin(s.a) * d);
      ctx.lineTo(s.x + Math.cos(s.a) * (d + len), s.y + Math.sin(s.a) * (d + len));
      ctx.stroke();
    }
    if (sparks.length) requestAnimationFrame(tick); else running = false;
  }
  function spark(x, y, { count = 8, reach = 26, len = 10, life = 480, w = 1.5, rgb = "222,190,120" } = {}) {
    if (reduce) return;
    ensureCanvas();
    const t0 = performance.now();
    for (let i = 0; i < count; i++) {
      sparks.push({ x, y, t0, life: life * (0.8 + Math.random() * 0.4), reach: reach * (0.7 + Math.random() * 0.6),
        len, w, rgb, a: (Math.PI * 2 * i) / count + Math.random() * 0.3 });
    }
    if (!running) { running = true; requestAnimationFrame(tick); }
  }
  function sparkAt(el, opts) {
    const r = el.getBoundingClientRect();
    spark(r.left + r.width / 2, r.top + r.height / 2, opts);
  }
  function celebrate(el) {
    const r = (el || document.body).getBoundingClientRect();
    const cx = r.left + r.width / 2, cy = r.top + Math.min(r.height / 2, innerHeight / 2);
    spark(cx, cy, { count: 28, reach: 150, len: 26, life: 1200, w: 1.6 });
    setTimeout(() => spark(cx, cy, { count: 16, reach: 80, len: 14, life: 900, w: 1.2, rgb: "246,236,214" }), 140);
  }

  /* ---- page-load: lights come on in the vitrine (the one orchestrated moment) ---- */
  function lightsOn({ curtain, words, rest } = {}) {
    if (!animate) { if (curtain) curtain.remove(); return; }
    const tl = G.timeline({ defaults: { ease: "expo.out" } });
    if (curtain) tl.to(curtain, { autoAlpha: 0, duration: 1.6, ease: "power2.inOut", onComplete: () => curtain.remove() }, 0);
    tl.fromTo(document.documentElement, { "--lamp": 0 }, { "--lamp": 1, duration: 2.2, ease: "power2.out" }, 0.1);
    (words || []).forEach((el, i) => { const t = split(el, { duration: 1.4 }); if (t) tl.add(t, 0.45 + i * 0.15); });
    if (rest && rest.length) tl.add(rise(rest, { stagger: 0.04 }), 0.8);
    return tl;
  }

  /* ---- reveal blocks as they scroll into view ---- */
  function onScrollReveal(targets) {
    if (!animate || !window.ScrollTrigger) return;
    G.utils.toArray(targets).forEach((el) => {
      G.from(el, { y: 36, autoAlpha: 0, duration: 1.1, ease: "expo.out", clearProps: "transform,opacity,visibility",
        scrollTrigger: { trigger: el, start: "top 88%", once: true } });
    });
  }

  /* ---- dialog open with a soft lift ---- */
  function openDialog(dlg) {
    dlg.showModal();
    if (animate) G.fromTo(dlg, { y: 24, autoAlpha: 0, scale: 0.98 }, { y: 0, autoAlpha: 1, scale: 1, duration: 0.7, ease: "expo.out" });
  }

  return { reduce, animate, smoothScroll, scrollTop, split, rise, unveil, countUp, spotlight, magnet, spark, sparkAt,
    celebrate, lightsOn, onScrollReveal, openDialog };
})();
