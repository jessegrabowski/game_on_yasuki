import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { initials, cropToPixels } from '../../../src/yasuki_web/static/site/avatar.js';

describe('initials', () => {
  it('takes the first letter of a single-word handle', () => {
    assert.equal(initials('CunningRonin238'), 'C');
  });

  it('takes the first letter of each of the first two words', () => {
    assert.equal(initials('Hida Kisada Crab'), 'HK');
  });

  it('falls back to ? for an empty or missing name', () => {
    assert.equal(initials(''), '?');
    assert.equal(initials(null), '?');
  });
});

describe('cropToPixels', () => {
  it('maps a fractional crop to source pixels on the natural image', () => {
    const crop = { left: 0.25, top: 0.25, right: 0.75, bottom: 0.5 };
    assert.deepEqual(cropToPixels(crop, 100, 200), { sx: 25, sy: 50, sw: 50, sh: 50 });
  });
});
