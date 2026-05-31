import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { resetDOM } from './dom-shim.js';
import { makeCard } from './fixtures.js';
import {
  initCardList,
  getAllResults,
  updateResults,
  setSelectedCard,
  setFetching,
  renderCardList,
} from '../../../src/yasuki_web/static/deck_builder/js/card-list.js';

beforeEach(() => {
  resetDOM();
  updateResults([], false, false);
  setSelectedCard(null);
  setFetching(false);
});

describe('card-list state', () => {
  it('updateResults replaces results when not appending', () => {
    const cards = [makeCard({ card_id: 'c1' }), makeCard({ card_id: 'c2' })];
    updateResults(cards, false, false);
    assert.equal(getAllResults().length, 2);

    updateResults([makeCard({ card_id: 'c3' })], false, false);
    assert.equal(getAllResults().length, 1);
    assert.equal(getAllResults()[0].card_id, 'c3');
  });

  it('updateResults appends when append=true', () => {
    updateResults([makeCard({ card_id: 'c1' })], true, false);
    updateResults([makeCard({ card_id: 'c2' })], false, true);
    assert.equal(getAllResults().length, 2);
  });
});

describe('renderCardList', () => {
  it('renders each card keyed by card_id with a deck-derived side tag', () => {
    updateResults(
      [
        makeCard({ card_id: 'fate_card', decks: ['Fate'] }),
        makeCard({ card_id: 'setup_card', decks: ['Pre-Game'] }),
      ],
      false,
      false,
    );
    renderCardList();

    const items = document.getElementById('cardList').children.filter(
      (el) => el.className && el.className.includes('card-list-item'),
    );
    assert.equal(items.length, 2);
    assert.equal(items[0]._cardId, 'fate_card');

    const fateTag = items[0].children[1];
    assert.ok(fateTag.className.includes('fate'));
    assert.equal(fateTag.textContent, 'Fate');

    const setupTag = items[1].children[1];
    assert.ok(setupTag.className.includes('pre_game'));
    assert.equal(setupTag.textContent, 'Pre-Game');
  });
});
