import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  artRect,
  coverCrop,
  monOverlaysFor,
  overlaysFor,
  patchesFor,
  setArtLayout,
} from '../../../src/yasuki_web/static/deck_builder/js/art.js';

setArtLayout({
  default_era: '2016+',
  default_layout: 'Strategy',
  rects: {
    '2016+|Strategy': [0.052, 0.112, 0.956, 0.524],
    '2000-04|Strategy': [0.1, 0.17, 0.9, 0.586],
    '2000-04|Personality': [0.107, 0.185, 0.893, 0.585],
  },
  overlays: {
    '2016+|Holding': [{ asset: 'holding_flair.png', rect: [0.3058, 0.4735, 0.6942, 0.5864] }],
  },
  mons: {
    era: '2016+',
    assets: { Air: 'air.png', Earth: 'earth.png', Fire: 'fire.png', Void: 'void.png' },
    left: 0.0075,
    width: 0.111,
    height: 0.074,
    cy0: 0.178,
    pitch: 0.0774,
  },
  patches: {
    '2016+|Personality': [
      { mask: 'gold_coin.png', rect: [0.4408, 0.5623, 0.5584, 0.6397] },
      { rect: [0.0333, 0.1072, 0.0683, 0.1235] },
    ],
  },
});

describe('artRect', () => {
  it('returns the exact (era, layout) rect when present', () => {
    assert.deepEqual(artRect('2000-04', 'Personality'), [0.107, 0.185, 0.893, 0.585]);
  });
  it('falls back to the era Strategy window for an unmeasured layout', () => {
    assert.deepEqual(artRect('2000-04', 'Nonexistent'), [0.1, 0.17, 0.9, 0.586]);
  });
  it('falls back to the modern Strategy window for an unknown era', () => {
    assert.deepEqual(artRect('9999', 'Nonsense'), [0.052, 0.112, 0.956, 0.524]);
  });
});

describe('overlaysFor', () => {
  it('returns the frame overlays for a layout that has them', () => {
    assert.deepEqual(overlaysFor('2016+', 'Holding'), [
      { asset: 'holding_flair.png', rect: [0.3058, 0.4735, 0.6942, 0.5864] },
    ]);
  });
  it('returns empty for a layout with no overlays', () => {
    assert.deepEqual(overlaysFor('2016+', 'Personality'), []);
  });
});

describe('monOverlaysFor', () => {
  it('stacks present mon keywords alphabetically, same size/left, even slot centers', () => {
    const o = monOverlaysFor(['Void', 'Earth', 'Charge', 'Air'], '2016+');
    assert.deepEqual(
      o.map((x) => x.asset),
      ['air.png', 'earth.png', 'void.png'],
    );
    assert.equal(new Set(o.map((x) => (x.rect[2] - x.rect[0]).toFixed(6))).size, 1);
    const centers = o.map((x) => (x.rect[1] + x.rect[3]) / 2);
    assert.ok(Math.abs(centers[1] - centers[0] - (centers[2] - centers[1])) < 1e-9);
  });
  it('is empty off the modern frame or with no mon keywords', () => {
    assert.deepEqual(monOverlaysFor(['Fire'], '2005-09'), []);
    assert.deepEqual(monOverlaysFor([], '2016+'), []);
  });
});

describe('patchesFor', () => {
  it('returns masked + unmasked patches for a key that has them', () => {
    const p = patchesFor('2016+', 'Personality');
    assert.equal(p.length, 2);
    assert.equal(p[0].mask, 'gold_coin.png');
    assert.deepEqual(p[0].rect, [0.4408, 0.5623, 0.5584, 0.6397]);
    assert.equal(p[1].mask, undefined);
    assert.deepEqual(p[1].rect, [0.0333, 0.1072, 0.0683, 0.1235]);
  });
  it('is empty for a key with no patches', () => {
    assert.deepEqual(patchesFor('2005-09', 'Personality'), []);
    assert.deepEqual(patchesFor('2016+', 'Holding'), []);
  });
});

describe('coverCrop', () => {
  it('trims the sides of a too-wide box, keeping full height, centered', () => {
    assert.deepEqual(coverCrop([0, 0, 200, 100], 50, 100), [75, 0, 125, 100]);
  });
  it('trims top/bottom of a too-tall box, keeping full width, centered', () => {
    assert.deepEqual(coverCrop([0, 0, 100, 200], 100, 50), [0, 75, 100, 125]);
  });
});
