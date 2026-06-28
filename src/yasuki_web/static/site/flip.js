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
