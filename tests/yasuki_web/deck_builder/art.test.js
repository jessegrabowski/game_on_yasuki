import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { artRect, coverCrop, setArtLayout } from '../../../src/yasuki_web/static/deck_builder/js/art.js';

setArtLayout({
  default_era: '2016+',
  default_layout: 'Strategy',
  rects: {
    '2016+|Strategy': [0.052, 0.112, 0.956, 0.524],
    '2000-04|Strategy': [0.1, 0.17, 0.9, 0.586],
    '2000-04|Personality': [0.107, 0.185, 0.893, 0.585],
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

describe('coverCrop', () => {
  it('trims the sides of a too-wide box, keeping full height, centered', () => {
    assert.deepEqual(coverCrop([0, 0, 200, 100], 50, 100), [75, 0, 125, 100]);
  });
  it('trims top/bottom of a too-tall box, keeping full width, centered', () => {
    assert.deepEqual(coverCrop([0, 0, 100, 200], 100, 50), [0, 75, 100, 125]);
  });
});
