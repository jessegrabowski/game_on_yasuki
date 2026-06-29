import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { initials } from '../../../src/yasuki_web/static/site/avatar.js';

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
