import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { buildImageList } from '../../../src/yasuki_web/static/deck_builder/js/print.js';
import { makeCard } from './fixtures.js';

const IMG = '/images';

function entry(card, prints) {
  return { card, prints };
}

describe('buildImageList', () => {
  it('orders by side (Dynasty, Fate, Pre-Game) then card name, expanded by quantity', () => {
    const deck = {
      FATE: {
        zeta: entry(makeCard({ card_id: 'zeta', name: 'Zeta' }), { 2: { qty: 1, set_name: 'S' } }),
        alpha: entry(makeCard({ card_id: 'alpha', name: 'Alpha' }), { 3: { qty: 2, set_name: 'S' } }),
      },
      DYNASTY: {
        beta: entry(makeCard({ card_id: 'beta', name: 'Beta' }), { 1: { qty: 1, set_name: 'S' } }),
      },
      PRE_GAME: {
        omega: entry(makeCard({ card_id: 'omega', name: 'Omega' }), { 4: { qty: 1, set_name: 'S' } }),
      },
    };
    const map = new Map([
      [1, { front: 'sets/x/beta.jpg' }],
      [2, { front: 'sets/x/zeta.jpg' }],
      [3, { front: 'sets/x/alpha.jpg' }],
      [4, { front: 'sets/x/omega.jpg' }],
    ]);

    assert.deepEqual(buildImageList(deck, IMG, map), [
      '/images/sets/x/beta.jpg', // Dynasty
      '/images/sets/x/alpha.jpg', // Fate, Alpha, qty 2
      '/images/sets/x/alpha.jpg',
      '/images/sets/x/zeta.jpg', // Fate, Zeta
      '/images/sets/x/omega.jpg', // Pre-Game
    ]);
  });

  it('uses a custom print data URL verbatim and a real print path through the host', () => {
    const deck = {
      FATE: {
        a: entry(makeCard({ card_id: 'a', name: 'A' }), {
          5: { qty: 1, set_name: 'S' },
          '-9': { qty: 1, isCustom: true, dataUrl: 'data:image/jpeg;base64,ZZZ' },
        }),
      },
    };
    const map = new Map([[5, { front: 'sets/x/a.jpg' }]]);
    assert.deepEqual(buildImageList(deck, IMG, map), [
      '/images/sets/x/a.jpg',
      'data:image/jpeg;base64,ZZZ',
    ]);
  });

  it('includes both faces of a double-sided print, each expanded by quantity', () => {
    const deck = {
      FATE: {
        a: entry(makeCard({ card_id: 'a', name: 'A' }), { 5: { qty: 2, set_name: 'S' } }),
      },
    };
    const map = new Map([[5, { front: 'sets/x/a.jpg', back: 'sets/x/a__back.jpg' }]]);
    assert.deepEqual(buildImageList(deck, IMG, map), [
      '/images/sets/x/a.jpg',
      '/images/sets/x/a.jpg',
      '/images/sets/x/a__back.jpg',
      '/images/sets/x/a__back.jpg',
    ]);
  });

  it('falls back to the card default image when the print is not in the map', () => {
    const deck = {
      FATE: {
        a: entry(makeCard({ card_id: 'a', name: 'A', image_path: 'sets/d/a.jpg' }), {
          7: { qty: 1, set_name: 'S' },
        }),
      },
    };
    assert.deepEqual(buildImageList(deck, IMG, new Map()), ['/images/sets/d/a.jpg']);
  });

  it('skips a print with no resolvable image', () => {
    const deck = {
      FATE: {
        a: entry(makeCard({ card_id: 'a', name: 'A', image_path: null }), {
          7: { qty: 2, set_name: 'S' },
        }),
      },
    };
    assert.deepEqual(buildImageList(deck, IMG, new Map()), []);
  });
});
