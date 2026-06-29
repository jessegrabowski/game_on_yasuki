import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { resolvePane } from '../../../src/yasuki_web/static/site/settings.js';

describe('resolvePane', () => {
  it('keeps a known pane id', () => {
    assert.equal(resolvePane('privacy'), 'privacy');
    assert.equal(resolvePane('delete'), 'delete');
  });

  it('falls back to the first pane for an unknown or empty hash', () => {
    assert.equal(resolvePane(''), 'display');
    assert.equal(resolvePane('nope'), 'display');
  });
});
