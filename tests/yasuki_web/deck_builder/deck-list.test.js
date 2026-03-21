import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { resetDOM } from './dom-shim.js';
import { addCard, clearDeck } from '../../../src/yasuki_web/static/deck_builder/js/deck-state.js';
import {
  initDeckList,
  getSelectedDeckCard,
  setSelectedDeckCard,
  renderDeckLists,
} from '../../../src/yasuki_web/static/deck_builder/js/deck-list.js';

const CARD_STR = { id: 'strategy1', name: 'Ambush', type: 'Strategy', side: 'FATE' };
const CARD_HOLD = { id: 'holding1', name: 'Gold Mine', type: 'Holding', side: 'DYNASTY' };
const CARD_SH = { id: 'stronghold1', name: 'Kyuden Hida', type: 'Stronghold', side: 'PRE_GAME' };

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
    assert.equal(document.getElementById('preGameCount').textContent, 0);
  });

  it('renders correct count for fate deck', () => {
    addCard('strategy1', 'FATE', CARD_STR, 10, 'Imperial Edition');
    addCard('strategy1', 'FATE', CARD_STR, 10, 'Imperial Edition');
    renderDeckLists();
    assert.equal(document.getElementById('fateCount').textContent, 2);
  });

  it('renders type header and card item', () => {
    addCard('strategy1', 'FATE', CARD_STR, 10, 'Imperial Edition');
    renderDeckLists();
    const el = document.getElementById('fateList');
    assert.ok(el.children.length >= 2, 'Should have at least a header and a card');
    assert.ok(el.children[0].textContent.includes('Strategies'));
  });

  it('renders hierarchical view for multi-print card', () => {
    addCard('strategy1', 'FATE', CARD_STR, 10, 'Imperial Edition');
    addCard('strategy1', 'FATE', CARD_STR, 20, 'Ivory Edition');
    renderDeckLists();
    const el = document.getElementById('fateList');
    assert.ok(el.children.length >= 4, 'Should have header, card, and two sub-items');
  });

  it('renders cards into correct side lists', () => {
    addCard('strategy1', 'FATE', CARD_STR, 10, 'IE');
    addCard('holding1', 'DYNASTY', CARD_HOLD, 30, 'Gold');
    renderDeckLists();

    const fate = document.getElementById('fateList');
    assert.ok(fate.children[0].textContent.includes('Strategies'));

    const dynasty = document.getElementById('dynastyList');
    assert.ok(dynasty.children[0].textContent.includes('Holdings'));
  });

  it('renders pre-game cards into preGameList', () => {
    addCard('stronghold1', 'PRE_GAME', CARD_SH, 50, 'Imperial Edition');
    renderDeckLists();

    const preGame = document.getElementById('preGameList');
    assert.equal(document.getElementById('preGameCount').textContent, 1);
    assert.ok(preGame.children.length >= 2, 'Should have header and card');
    assert.ok(preGame.children[0].textContent.includes('Strongholds'));
  });
});
