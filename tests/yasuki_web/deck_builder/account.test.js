import { describe, it, beforeEach, mock } from 'node:test';
import assert from 'node:assert/strict';

globalThis.fetch = mock.fn();

import {
  getMe,
  saveDeck,
  listMyDecks,
  deleteDeck,
  fetchSharedDeck,
} from '../../../src/yasuki_web/static/deck_builder/js/account.js';

const respond = (body, { ok = true, status = 200 } = {}) =>
  Promise.resolve({ ok, status, json: () => Promise.resolve(body) });

beforeEach(() => {
  fetch.mock.resetCalls();
});

describe('getMe', () => {
  it('returns the user when signed in', async () => {
    fetch.mock.mockImplementation(() => respond({ user: { id: 1, display_name: 'Ada' } }));
    assert.deepEqual(await getMe(), { id: 1, display_name: 'Ada' });
  });

  it('returns null when the request fails', async () => {
    fetch.mock.mockImplementation(() => Promise.reject(new Error('offline')));
    assert.equal(await getMe(), null);
  });
});

describe('saveDeck', () => {
  it('POSTs the deck as JSON and returns the saved summary', async () => {
    fetch.mock.mockImplementation(() => respond({ deck: { slug: 'abc', name: 'Crab' } }, { status: 201 }));
    const result = await saveDeck({ name: 'Crab', yaml: 'Dynasty:\n  - Card\n', visibility: 'public' });

    assert.deepEqual(result, { ok: true, deck: { slug: 'abc', name: 'Crab' } });
    const [url, options] = fetch.mock.calls[0].arguments;
    assert.equal(url, '/api/me/decks');
    assert.equal(options.method, 'POST');
    assert.deepEqual(JSON.parse(options.body), {
      name: 'Crab',
      yaml: 'Dynasty:\n  - Card\n',
      visibility: 'public',
      description: null,
      format: null,
    });
  });

  it('maps a 401 to a sign-in prompt', async () => {
    fetch.mock.mockImplementation(() => respond({}, { ok: false, status: 401 }));
    const result = await saveDeck({ name: 'Crab', yaml: 'x' });
    assert.deepEqual(result, { ok: false, status: 401, error: 'Sign in to save decks' });
  });

  it('surfaces the unknown-card list from a 400', async () => {
    const body = { detail: { error: 'unknown_cards', cards: ['Ghost', 'Phantom'] } };
    fetch.mock.mockImplementation(() => respond(body, { ok: false, status: 400 }));
    const result = await saveDeck({ name: 'Crab', yaml: 'x' });
    assert.equal(result.error, 'Unknown card(s): Ghost, Phantom');
  });

  it('surfaces a 422 cap message verbatim', async () => {
    fetch.mock.mockImplementation(() => respond({ detail: 'At the 200-deck limit' }, { ok: false, status: 422 }));
    const result = await saveDeck({ name: 'Crab', yaml: 'x' });
    assert.equal(result.error, 'At the 200-deck limit');
  });
});

describe('listMyDecks', () => {
  it('returns the decks array', async () => {
    fetch.mock.mockImplementation(() => respond({ decks: [{ slug: 'a' }, { slug: 'b' }] }));
    assert.deepEqual(await listMyDecks(), [{ slug: 'a' }, { slug: 'b' }]);
  });

  it('returns an empty list when unauthorized', async () => {
    fetch.mock.mockImplementation(() => respond({}, { ok: false, status: 401 }));
    assert.deepEqual(await listMyDecks(), []);
  });
});

describe('deleteDeck', () => {
  it('DELETEs by slug and reports success', async () => {
    fetch.mock.mockImplementation(() => respond({ deleted: 'abc' }));
    assert.equal(await deleteDeck('abc'), true);
    const [url, options] = fetch.mock.calls[0].arguments;
    assert.equal(url, '/api/me/decks/abc');
    assert.equal(options.method, 'DELETE');
  });

  it('reports failure on a non-ok response', async () => {
    fetch.mock.mockImplementation(() => respond({}, { ok: false, status: 404 }));
    assert.equal(await deleteDeck('missing'), false);
  });
});

describe('fetchSharedDeck', () => {
  it('returns the deck payload by slug', async () => {
    const body = { deck: { slug: 'abc' }, cards: [], yaml: 'name: x\n' };
    fetch.mock.mockImplementation(() => respond(body));
    assert.deepEqual(await fetchSharedDeck('abc'), body);
  });

  it('returns null when the deck is missing or private', async () => {
    fetch.mock.mockImplementation(() => respond({}, { ok: false, status: 404 }));
    assert.equal(await fetchSharedDeck('nope'), null);
  });
});
