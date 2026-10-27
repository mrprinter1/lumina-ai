// Minimal signature pad: pointer events on a canvas, exported as PNG.
function SignaturePad(canvas) {
  const ctx = canvas.getContext("2d");
  let drawing = false, dirty = false, last = null;
  const ink = () => getComputedStyle(canvas).color || "#1c2120";
  const pos = (e) => {
    const r = canvas.getBoundingClientRect();
    return [(e.clientX - r.left) * (canvas.width / r.width), (e.clientY - r.top) * (canvas.height / r.height)];
  };
  canvas.style.touchAction = "none";
  canvas.addEventListener("pointerdown", (e) => {
    drawing = true; last = pos(e); canvas.setPointerCapture(e.pointerId);
  });
  canvas.addEventListener("pointermove", (e) => {
    if (!drawing) return;
    const p = pos(e);
    ctx.strokeStyle = ink(); ctx.lineWidth = 3; ctx.lineCap = "round"; ctx.lineJoin = "round";
    ctx.beginPath(); ctx.moveTo(...last); ctx.lineTo(...p); ctx.stroke();
    last = p; dirty = true;
  });
  ["pointerup", "pointercancel", "pointerleave"].forEach((t) => canvas.addEventListener(t, () => { drawing = false; }));
  return {
    clear() { ctx.clearRect(0, 0, canvas.width, canvas.height); dirty = false; },
    isEmpty() { return !dirty; },
    toDataURL() { return canvas.toDataURL("image/png"); },
  };
}
