import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { chanceOfAtLeastOne } from '../../../src/yasuki_web/static/site/probability.js';

// Independent reference: 1 - C(y-z, n) / C(y, n), the textbook hypergeometric P(X >= 1).
const choose = (n, k) => {
  if (k < 0 || k > n) return 0;
  let result = 1;
  for (let i = 0; i < k; i++) result = (result * (n - i)) / (i + 1);
  return result;
};
const reference = (population, copies, draws) => 1 - choose(population - copies, draws) / choose(population, draws);

describe('chanceOfAtLeastOne', () => {
  it('matches the hypergeometric reference across deck-sized inputs', () => {
    for (const [y, z, n] of [[40, 3, 1], [40, 3, 4], [45, 2, 5], [40, 1, 4], [12, 3, 2]]) {
      assert.ok(Math.abs(chanceOfAtLeastOne(y, z, n) - reference(y, z, n)) < 1e-12, `${y},${z},${n}`);
    }
  });

  it('scales with the number of copies — it is not the unique-card (z=1) formula', () => {
    // A single draw from 40 is z/40, so more copies strictly raises the odds.
    for (const z of [1, 2, 3]) {
      assert.ok(Math.abs(chanceOfAtLeastOne(40, z, 1) - z / 40) < 1e-12, `z=${z}`);
    }
    assert.ok(chanceOfAtLeastOne(40, 3, 4) > chanceOfAtLeastOne(40, 1, 4));
  });

  it('returns 0 when the deck holds no copies', () => {
    assert.equal(chanceOfAtLeastOne(40, 0, 5), 0);
  });

  it('returns 1 when a copy cannot be avoided', () => {
    assert.equal(chanceOfAtLeastOne(40, 40, 1), 1); // every card is a copy
    assert.equal(chanceOfAtLeastOne(5, 3, 3), 1); // only 2 non-copies, but 3 draws
    assert.equal(chanceOfAtLeastOne(5, 1, 5), 1); // drawing the whole deck is certain
  });

  it('returns NaN for nonsensical inputs so the UI can blank the result', () => {
    assert.ok(Number.isNaN(chanceOfAtLeastOne(0, 0, 1))); // empty deck
    assert.ok(Number.isNaN(chanceOfAtLeastOne(40, 3, 0))); // no draws
    assert.ok(Number.isNaN(chanceOfAtLeastOne(40, 41, 1))); // more copies than cards
    assert.ok(Number.isNaN(chanceOfAtLeastOne(40, 3, NaN)));
  });
});
