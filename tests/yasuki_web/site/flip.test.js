import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { flipDeltas, flip } from '../../../src/yasuki_web/static/site/flip.js';

const rects = (entries) => new Map(entries.map(([id, left, top]) => [id, { left, top }]));
const byId = (deltas) => [...deltas].sort((a, b) => a.id.localeCompare(b.id));

describe('flipDeltas', () => {
  it('gives a survivor the translate from its new position back to its old one', () => {
    const before = rects([['a', 100, 50]]);
    const after = rects([['a', 130, 90]]);
    assert.deepEqual(flipDeltas(before, after), [{ id: 'a', dx: -30, dy: -40 }]);
  });

  it('skips a card that did not move', () => {
    const before = rects([['a', 100, 50]]);
    const after = rects([['a', 100, 50]]);
    assert.deepEqual(flipDeltas(before, after), []);
  });

  it('skips a card that only appeared after the render', () => {
    const before = rects([]);
    const after = rects([['a', 130, 90]]);
    assert.deepEqual(flipDeltas(before, after), []);
  });

  it('skips a card that was removed by the render', () => {
    const before = rects([['a', 100, 50]]);
    const after = rects([]);
    assert.deepEqual(flipDeltas(before, after), []);
  });

  it('returns a delta for each survivor that moved', () => {
    const before = rects([['a', 0, 0], ['b', 10, 10], ['c', 20, 20]]);
    const after = rects([['a', 5, 0], ['b', 10, 10], ['c', 20, 25]]);
    assert.deepEqual(byId(flipDeltas(before, after)), [
      { id: 'a', dx: -5, dy: 0 },
      { id: 'c', dx: 0, dy: -5 },
    ]);
  });
});

describe('flip', () => {
  it('still runs the render under reduced motion', () => {
    const original = globalThis.matchMedia;
    globalThis.matchMedia = () => ({ matches: true });
    try {
      let rendered = false;
      flip({}, () => (rendered = true));
      assert.ok(rendered, 'the board still draws when animation is suppressed');
    } finally {
      globalThis.matchMedia = original;
    }
  });

  it('runs the render on the normal path when nothing moved', () => {
    let rendered = false;
    flip({ querySelectorAll: () => [] }, () => (rendered = true));
    assert.ok(rendered);
  });
});
