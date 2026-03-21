import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { resetDOM } from './dom-shim.js';
import { addCard, clearDeck } from '../../app/assets/deck_builder/js/deck-state.js';
import {
  initDeckList,
  getSelectedDeckCard,
  setSelectedDeckCard,
  renderDeckLists,
} from '../../app/assets/deck_builder/js/deck-list.js';

const CARD_STR = { id: 'strategy1', name: 'Ambush', type: 'Strategy', side: 'FATE' };
const CARD_HOLD = { id: 'holding1', name: 'Gold Mine', type: 'Holding', side: 'DYNASTY' };

beforeEach(() => {
  resetDOM();
  clearDeck();
  setSelectedDeckCard(null);
  initDeckList({ onSelect: () => {}, onDblClick: () => {} });
});

describe('deck-list state', () => {
  it('starts with no selection', () => {
    assert.equal(getSelectedDeckCard(), null);
  });

  it('set and get selection', () => {
    const sel = { side: 'FATE', id: 'card1', printId: 10 };
    setSelectedDeckCard(sel);
    assert.deepEqual(getSelectedDeckCard(), sel);
  });
});

describe('renderDeckLists', () => {
  it('sets count to 0 for empty decks', () => {
    renderDeckLists();
    assert.equal(document.getElementById('dynastyCount').textContent, 0);
    assert.equal(document.getElementById('fateCount').textContent, 0);
  });

  it('renders correct count for fate deck', () => {
    addCard('strategy1', 'FATE', CARD_STR, 10, 'Imperial Edition');
    addCard('strategy1', 'FATE', CARD_STR, 10, 'Imperial Edition');
    renderDeckLists();
    assert.equal(document.getElementById('fateCount').textContent, 2);
  });

  it('renders type header for single type', () => {
    addCard('strategy1', 'FATE', CARD_STR, 10, 'IE');
    renderDeckLists();
    const el = document.getElementById('fateList');
    const typeHeader = el.children[0];
    assert.ok(typeHeader.className.includes('deck-type-header'));
    assert.ok(typeHeader.textContent.includes('Strategies'));
    assert.ok(typeHeader.textContent.includes('1'));
  });

  it('renders card item with set name for single-print card', () => {
    addCard('strategy1', 'FATE', CARD_STR, 10, 'Imperial Edition');
    renderDeckLists();
    const el = document.getElementById('fateList');
    const cardItem = el.children[1];
    assert.ok(cardItem.className.includes('deck-item'));
    const nameText = cardItem.children[0].textContent;
    assert.ok(nameText.includes('Ambush'));
    assert.ok(nameText.includes('[Imperial Edition]'));
  });

  it('renders hierarchical view for multi-print card', () => {
    addCard('strategy1', 'FATE', CARD_STR, 10, 'Imperial Edition');
    addCard('strategy1', 'FATE', CARD_STR, 20, 'Ivory Edition');
    renderDeckLists();
    const el = document.getElementById('fateList');
    // children: [type-header, card-item, sub-item-1, sub-item-2]
    assert.equal(el.children.length, 4);

    const cardItem = el.children[1];
    assert.ok(cardItem.className.includes('deck-item'));
    assert.ok(cardItem.children[0].textContent.includes('Ambush'));
    assert.ok(cardItem.children[1].textContent.includes('2'));

    const sub1 = el.children[2];
    assert.ok(sub1.className.includes('deck-sub-item'));
    assert.ok(sub1.children[0].textContent.includes('Imperial Edition'));

    const sub2 = el.children[3];
    assert.ok(sub2.className.includes('deck-sub-item'));
    assert.ok(sub2.children[0].textContent.includes('Ivory Edition'));
  });

  it('groups cards by type', () => {
    addCard('strategy1', 'FATE', CARD_STR, 10, 'IE');
    addCard('holding1', 'DYNASTY', CARD_HOLD, 30, 'Gold');
    renderDeckLists();

    const fate = document.getElementById('fateList');
    assert.ok(fate.children[0].textContent.includes('Strategies'));

    const dynasty = document.getElementById('dynastyList');
    assert.ok(dynasty.children[0].textContent.includes('Holdings'));
  });

  it('sorts cards alphabetically within type', () => {
    const cardZ = { id: 'z_card', name: 'Zephyr', type: 'Strategy', side: 'FATE' };
    const cardA = { id: 'a_card', name: 'Assault', type: 'Strategy', side: 'FATE' };
    addCard('z_card', 'FATE', cardZ, 1, 'Set');
    addCard('a_card', 'FATE', cardA, 2, 'Set');
    renderDeckLists();

    const el = document.getElementById('fateList');
    // children: [type-header, card-A, card-Z]
    assert.ok(el.children[1].children[0].textContent.includes('Assault'));
    assert.ok(el.children[2].children[0].textContent.includes('Zephyr'));
  });
});
