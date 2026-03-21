import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { resetDOM } from './dom-shim.js';
import {
  initCardList,
  getSelectedCard,
  setSelectedCard,
  getAllResults,
  updateResults,
  setFetching,
  isFetching,
} from '../../app/assets/deck_builder/js/card-list.js';

beforeEach(() => {
  resetDOM();
  updateResults([], false, false);
  setSelectedCard(null);
  setFetching(false);
});

describe('card-list state', () => {
  it('starts with no selected card', () => {
    assert.equal(getSelectedCard(), null);
  });

  it('set and get selected card', () => {
    const card = { id: 'c1', name: 'Test' };
    setSelectedCard(card);
    assert.equal(getSelectedCard(), card);
  });

  it('starts with empty results', () => {
    assert.deepEqual(getAllResults(), []);
  });

  it('updateResults replaces results when not appending', () => {
    const cards = [{ id: 'c1' }, { id: 'c2' }];
    updateResults(cards, false, false);
    assert.equal(getAllResults().length, 2);

    updateResults([{ id: 'c3' }], false, false);
    assert.equal(getAllResults().length, 1);
    assert.equal(getAllResults()[0].id, 'c3');
  });

  it('updateResults appends when append=true', () => {
    updateResults([{ id: 'c1' }], true, false);
    updateResults([{ id: 'c2' }], false, true);
    assert.equal(getAllResults().length, 2);
  });

  it('fetching flag', () => {
    assert.equal(isFetching(), false);
    setFetching(true);
    assert.equal(isFetching(), true);
  });

  it('updateResults clears fetching flag', () => {
    setFetching(true);
    updateResults([], false, false);
    assert.equal(isFetching(), false);
  });
});
