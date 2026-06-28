import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { resetDOM } from '../deck_builder/dom-shim.js';
import { reconcile } from '../../../src/yasuki_web/static/site/reconcile.js';

// Generic stand-in hooks: the engine is card-agnostic, so the board's real cardElement/patchCard are
// out of scope here (their integration is covered where the battlefield render is converted).
const patch = (el, view) => {
  el.dataset.v = String(view.v ?? '');
};
const create = (view) => {
  const el = document.createElement('div');
  el.dataset.cardId = view.id;
  patch(el, view);
  return el;
};
const hooks = { create, patch };

const card = (id, v) => ({ id, v });
const ids = (container) => container.children.map((el) => el.dataset.cardId);

describe('reconcile', () => {
  let container;
  let registry;

  beforeEach(() => {
    resetDOM();
    container = document.createElement('div');
    registry = new Map();
  });

  it('creates a node per card on first render', () => {
    const ops = reconcile(container, [card('a'), card('b')], registry, hooks);
    assert.deepEqual(ops.created, ['a', 'b']);
    assert.deepEqual(ids(container), ['a', 'b']);
  });

  it('reuses the same element across renders instead of recreating it', () => {
    reconcile(container, [card('a', 1)], registry, hooks);
    const first = registry.get('a').el;
    const ops = reconcile(container, [card('a', 2)], registry, hooks);
    assert.equal(registry.get('a').el, first, 'element identity preserved');
    assert.deepEqual(ops.created, []);
    assert.equal(first.dataset.v, '2', 'patched in place');
  });

  it('removes stale nodes and drops them from the registry', () => {
    reconcile(container, [card('a'), card('b')], registry, hooks);
    const ops = reconcile(container, [card('a')], registry, hooks);
    assert.deepEqual(ops.removed, ['b']);
    assert.deepEqual(ids(container), ['a']);
    assert.equal(registry.has('b'), false);
  });

  it('reorders with the minimum number of moves (LIS keeps the stable run)', () => {
    reconcile(container, [card('a'), card('b'), card('c'), card('d')], registry, hooks);

    let inserts = 0;
    const realInsertBefore = container.insertBefore.bind(container);
    container.insertBefore = (node, ref) => {
      inserts++;
      return realInsertBefore(node, ref);
    };

    // a,b,c,d -> d,a,b,c: only 'd' must move; a,b,c are the longest increasing run.
    const ops = reconcile(container, [card('d'), card('a'), card('b'), card('c')], registry, hooks);

    assert.deepEqual(ids(container), ['d', 'a', 'b', 'c']);
    assert.equal(inserts, 1, 'exactly one DOM move for a single-card reorder');
    assert.deepEqual(ops.moved, ['d']);
  });

  it('clears every node and empties the registry when next is empty', () => {
    reconcile(container, [card('a'), card('b')], registry, hooks);
    const ops = reconcile(container, [], registry, hooks);
    assert.deepEqual(ops.removed.sort(), ['a', 'b']);
    assert.deepEqual(ids(container), []);
    assert.equal(registry.size, 0);
  });

  it('passes the previous view to patch — null on create, the prior view on update', () => {
    const seen = [];
    const trackingPatch = (el, view, prev) => {
      seen.push(prev);
      patch(el, view);
    };
    const tracking = { create, patch: trackingPatch };
    reconcile(container, [card('a', 1)], registry, tracking);
    reconcile(container, [card('a', 2)], registry, tracking);
    assert.equal(seen[0], null, 'null prev when the element is first built');
    assert.deepEqual(seen[1], { id: 'a', v: 1 }, 'prior view on a re-patch');
  });
});
