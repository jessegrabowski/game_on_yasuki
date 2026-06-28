import { describe, it, beforeEach, mock } from 'node:test';
import assert from 'node:assert/strict';

import { resetDOM } from '../deck_builder/dom-shim.js';

globalThis.fetch = mock.fn();

import {
  fetchMyDecks,
  fetchDeckYaml,
  deckLabel,
  openSavedDeckPicker,
} from '../../../src/yasuki_web/static/site/saved-decks.js';

const respond = (body, { ok = true, status = 200 } = {}) =>
  Promise.resolve({ ok, status, json: () => Promise.resolve(body) });

beforeEach(() => {
  resetDOM();
  fetch.mock.resetCalls();
});

describe('fetchMyDecks', () => {
  it('returns the decks when signed in', async () => {
    fetch.mock.mockImplementation(() => respond({ decks: [{ slug: 'a' }] }));
    assert.deepEqual(await fetchMyDecks(), [{ slug: 'a' }]);
  });

  it('returns null when unauthorized, signalling sign-in', async () => {
    fetch.mock.mockImplementation(() => respond({}, { ok: false, status: 401 }));
    assert.equal(await fetchMyDecks(), null);
  });
});

describe('fetchDeckYaml', () => {
  it('returns the deck YAML by slug', async () => {
    fetch.mock.mockImplementation(() => respond({ yaml: 'name: Crab\n' }));
    assert.equal(await fetchDeckYaml('abc'), 'name: Crab\n');
    assert.equal(fetch.mock.calls[0].arguments[0], '/api/decks/abc');
  });

  it('returns null when the deck is gone', async () => {
    fetch.mock.mockImplementation(() => respond({}, { ok: false, status: 404 }));
    assert.equal(await fetchDeckYaml('nope'), null);
  });
});

describe('deckLabel', () => {
  it('includes clan and counts when the clan is known', () => {
    assert.equal(
      deckLabel({ name: 'Crab Beats', clan: 'Crab', dynasty_count: 40, fate_count: 40 }),
      'Crab Beats — Crab (40D / 40F)',
    );
  });

  it('omits the clan when absent', () => {
    assert.equal(deckLabel({ name: 'Untitled', dynasty_count: 0, fate_count: 0 }), 'Untitled (0D / 0F)');
  });
});

describe('openSavedDeckPicker', () => {
  const slugs = (handle) =>
    handle.el.children[0].children[1].children.map((li) => li.dataset.slug);

  it('lists each deck by slug', () => {
    const handle = openSavedDeckPicker({
      decks: [{ slug: 'a', name: 'A' }, { slug: 'b', name: 'B' }],
      onPick: () => {},
    });
    assert.deepEqual(slugs(handle), ['a', 'b']);
  });

  it('calls onPick with the chosen slug and closes', () => {
    const picked = [];
    const handle = openSavedDeckPicker({
      decks: [{ slug: 'a', name: 'A' }, { slug: 'b', name: 'B' }],
      onPick: (slug) => picked.push(slug),
    });
    const list = handle.el.children[0].children[1];
    list.children[1]._emit('click', {});
    assert.deepEqual(picked, ['b']);
  });

  it('shows an empty-state row when there are no decks', () => {
    const handle = openSavedDeckPicker({ decks: [], onPick: () => {} });
    const list = handle.el.children[0].children[1];
    assert.equal(list.children.length, 1);
    assert.equal(list.children[0].dataset.slug, undefined);
  });
});
