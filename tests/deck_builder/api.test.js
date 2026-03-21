import { describe, it, beforeEach, mock } from 'node:test';
import assert from 'node:assert/strict';

import { resetDOM } from './dom-shim.js';

globalThis.fetch = mock.fn();

import { fetchJSON } from '../../app/assets/deck_builder/js/api.js';

beforeEach(() => {
  resetDOM();
  fetch.mock.resetCalls();
});

describe('fetchJSON', () => {
  it('returns parsed JSON on success', async () => {
    const body = { cards: [{ id: 'c1' }] };
    fetch.mock.mockImplementation(() =>
      Promise.resolve({ ok: true, json: () => Promise.resolve(body) }),
    );

    const result = await fetchJSON('/api/cards');
    assert.deepEqual(result, body);
    assert.equal(fetch.mock.callCount(), 1);
    assert.equal(fetch.mock.calls[0].arguments[0], '/api/cards');
  });

  it('throws on non-ok response', async () => {
    fetch.mock.mockImplementation(() =>
      Promise.resolve({ ok: false, status: 404, statusText: 'Not Found' }),
    );

    await assert.rejects(() => fetchJSON('/api/missing'), { message: '404 Not Found' });
  });
});
