// A keyed, minimal-move DOM reconciler: make a container hold exactly `next` (view objects with a
// stable `id`), in order, by reusing the existing nodes instead of tearing the container down and
// rebuilding it. Card-agnostic — the caller supplies create/patch/remove hooks — so the engine is
// unit-testable on its own; the board wires its real card element + patchCard in as the hooks.

// Longest-increasing-subsequence of `arr`, as the positions (into arr) that form it. A 0 entry is a
// sentinel — a freshly created node with no current position — and never joins the kept run. Patience
// sort + predecessor reconstruction, the algorithm Vue 3 / Inferno use to minimise moves on a reorder.
function lisPositions(source) {
  const predecessor = source.slice();
  const tails = [];
  for (let i = 0; i < source.length; i++) {
    if (source[i] === 0) continue;
    let lo = 0;
    let hi = tails.length;
    while (lo < hi) {
      const mid = (lo + hi) >> 1;
      if (source[tails[mid]] < source[i]) lo = mid + 1;
      else hi = mid;
    }
    predecessor[i] = lo > 0 ? tails[lo - 1] : -1;
    if (lo === tails.length) tails.push(i);
    else tails[lo] = i;
  }
  const result = [];
  let k = tails.length ? tails[tails.length - 1] : -1;
  while (k >= 0) {
    result.push(k);
    k = predecessor[k];
  }
  return result.reverse();
}

// Reconcile `container` to `next`, reusing nodes by id. `registry` (Map<id, {el, view}>) persists
// across calls so a card keeps its element — and any in-flight state on it — between renders. Hooks:
//   create(view)          -> a fresh element for a never-seen card
//   patch(el, view, prev) -> update the element in place (prev is its last view, null on create)
//   remove(el)            -> detach a stale card (defaults to el.remove())
// Returns an ops log for tests/telemetry. The container is assumed to hold only reconciler-owned nodes.
export function reconcile(container, next, registry, { create, patch, remove }) {
  const ops = { created: [], removed: [], moved: [] };
  const nextIds = new Set(next.map((view) => view.id));

  for (const [id, entry] of registry) {
    if (nextIds.has(id)) continue;
    if (remove) remove(entry.el);
    else entry.el.remove();
    registry.delete(id);
    ops.removed.push(id);
  }

  // Ensure every desired card has a patched element; collect them in target order.
  const desired = new Array(next.length);
  for (let i = 0; i < next.length; i++) {
    const view = next[i];
    let entry = registry.get(view.id);
    if (!entry) {
      entry = { el: create(view), view: null };
      registry.set(view.id, entry);
      ops.created.push(view.id);
    }
    patch(entry.el, view, entry.view);
    entry.view = view;
    desired[i] = entry.el;
  }

  // Minimal reorder. source[i] = (current index of desired[i] in container) + 1, or 0 if the node is
  // new / not yet attached. The LIS over source is the longest run already in correct relative order;
  // it stays put, and everything else is moved — walking right-to-left so the already-placed neighbour
  // is a stable insertBefore anchor. (Spread first: a live HTMLCollection has no indexOf.)
  const current = [...container.children];
  const source = desired.map((el) => {
    const idx = current.indexOf(el);
    return idx === -1 ? 0 : idx + 1;
  });
  const keep = new Set(lisPositions(source));
  for (let i = desired.length - 1; i >= 0; i--) {
    if (source[i] === 0 || !keep.has(i)) {
      container.insertBefore(desired[i], desired[i + 1] ?? null);
      ops.moved.push(next[i].id);
    }
  }
  return ops;
}
