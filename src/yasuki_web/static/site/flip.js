// FLIP animation support: given where tracked cards sat before a render and where they land after,
// work out the geometry to animate each survivor from its old position to its new one. This is the
// pure, unit-testable core; the rect capture and the WAAPI playback are layered on top in a real
// browser.

// The translate each surviving card needs to *appear* to start at its old position — old minus new,
// in viewport pixels — so animating it back to zero glides it into place. `before` and `after` map a
// card id to its rect ({ left, top }). Cards present in only one map (created or removed) are skipped,
// as are cards that did not move.
export function flipDeltas(before, after) {
  const deltas = [];
  for (const [id, from] of before) {
    const to = after.get(id);
    if (!to) continue;
    const dx = from.left - to.left;
    const dy = from.top - to.top;
    if (dx !== 0 || dy !== 0) deltas.push({ id, dx, dy });
  }
  return deltas;
}

const FLIP_MS = 180;

// Animate the position changes a render produces: record where each tracked card sits, run `mutate`
// (which reconciles the board), then glide every survivor from its old position to its new one. The
// move is keyed by card id, not element identity, so a card that crosses containers (hand -> board)
// animates correctly even though reconcile rebuilds it there. Cards that appear, vanish, or stay put
// render normally. A no-op under prefers-reduced-motion, and inert where there is no layout to measure
// (the rects collapse to zero delta), so the caller can always route a render through it.
export function flip(stage, mutate) {
  if (!stage || prefersReducedMotion()) {
    mutate();
    return;
  }
  const before = rectsById(stage);
  mutate();
  const after = rectsById(stage);
  for (const { id, dx, dy } of flipDeltas(before, after)) {
    const el = stage.querySelector(`[data-card-id="${CSS.escape(id)}"]`);
    el?.animate(
      [{ transform: `translate(${dx}px, ${dy}px)` }, { transform: 'none' }],
      { duration: FLIP_MS, easing: 'ease-out' },
    );
  }
}

function rectsById(stage) {
  const rects = new Map();
  for (const el of stage.querySelectorAll('[data-card-id]')) {
    const { left, top } = el.getBoundingClientRect();
    rects.set(el.dataset.cardId, { left, top });
  }
  return rects;
}

function prefersReducedMotion() {
  return globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
}
