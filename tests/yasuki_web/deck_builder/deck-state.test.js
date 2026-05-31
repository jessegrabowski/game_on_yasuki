import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import {
  getDeck,
  getBucket,
  addCard,
  removeCard,
  clearDeck,
  deckEntryTotal,
  nextCardAfterRemoval,
  getDeckNavItems,
} from '../../../src/yasuki_web/static/deck_builder/js/deck-state.js';
import { makeCard } from './fixtures.js';

const CARD_A = makeCard({ card_id: 'card_a', name: 'Alpha', types: ['Strategy'], decks: ['Fate'] });
const CARD_B = makeCard({ card_id: 'card_b', name: 'Beta', types: ['Strategy'], decks: ['Fate'] });
const CARD_C = makeCard({ card_id: 'card_c', name: 'Castle', types: ['Holding'], decks: ['Dynasty'] });
const CARD_SH = makeCard({
  card_id: 'card_sh',
  name: 'Kyuden Hida',
  types: ['Stronghold'],
  decks: ['Pre-Game'],
});

beforeEach(() => clearDeck());

describe('addCard', () => {
  it('adds a new card with one print', () => {
    addCard('card_a', 'FATE', CARD_A, 10, 'Imperial Edition');
    const bucket = getBucket('FATE');
    assert.deepEqual(bucket['card_a'].prints, { 10: { qty: 1, set_name: 'Imperial Edition' } });
  });

  it('increments qty for same print', () => {
    addCard('card_a', 'FATE', CARD_A, 10, 'Imperial Edition');
    addCard('card_a', 'FATE', CARD_A, 10, 'Imperial Edition');
    assert.equal(getBucket('FATE')['card_a'].prints[10].qty, 2);
  });

  it('tracks different prints separately', () => {
    addCard('card_a', 'FATE', CARD_A, 10, 'Imperial Edition');
    addCard('card_a', 'FATE', CARD_A, 20, 'Ivory Edition');
    const prints = getBucket('FATE')['card_a'].prints;
    assert.equal(prints[10].qty, 1);
    assert.equal(prints[20].qty, 1);
  });

  it('adds card to PRE_GAME bucket', () => {
    addCard('card_sh', 'PRE_GAME', CARD_SH, 40, 'Imperial Edition');
    const bucket = getBucket('PRE_GAME');
    assert.deepEqual(bucket['card_sh'].prints, { 40: { qty: 1, set_name: 'Imperial Edition' } });
    assert.equal(bucket['card_sh'].card.types[0], 'Stronghold');
  });
});

describe('removeCard', () => {
  it('decrements qty', () => {
    addCard('card_a', 'FATE', CARD_A, 10, 'IE');
    addCard('card_a', 'FATE', CARD_A, 10, 'IE');
    const result = removeCard('card_a', 'FATE', 10);
    assert.equal(result.cardRemoved, false);
    assert.equal(getBucket('FATE')['card_a'].prints[10].qty, 1);
  });

  it('removes print when qty hits zero', () => {
    addCard('card_a', 'FATE', CARD_A, 10, 'IE');
    const result = removeCard('card_a', 'FATE', 10);
    assert.equal(result.cardRemoved, true);
    assert.equal(result.printRemoved, true);
    assert.equal(getBucket('FATE')['card_a'], undefined);
  });

  it('removes first print when printId is null', () => {
    addCard('card_a', 'FATE', CARD_A, 10, 'IE');
    addCard('card_a', 'FATE', CARD_A, 20, 'Ivory');
    const result = removeCard('card_a', 'FATE', null);
    assert.equal(result.printRemoved, true);
    assert.equal(result.cardRemoved, false);
    const prints = getBucket('FATE')['card_a'].prints;
    assert.equal(prints[10], undefined);
    assert.equal(prints[20].qty, 1);
  });

  it('returns no-op for nonexistent card', () => {
    const result = removeCard('nope', 'FATE', 1);
    assert.equal(result.cardRemoved, false);
    assert.equal(result.printRemoved, false);
  });
});

describe('clearDeck', () => {
  it('empties all sides', () => {
    addCard('card_a', 'FATE', CARD_A, 10, 'IE');
    addCard('card_c', 'DYNASTY', CARD_C, 30, 'Gold');
    clearDeck();
    assert.deepEqual(getDeck().FATE, {});
  });
});

describe('deckEntryTotal', () => {
  it('sums across prints', () => {
    addCard('card_a', 'FATE', CARD_A, 10, 'IE');
    addCard('card_a', 'FATE', CARD_A, 10, 'IE');
    addCard('card_a', 'FATE', CARD_A, 20, 'Ivory');
    assert.equal(deckEntryTotal(getBucket('FATE')['card_a']), 3);
  });
});

describe('nextCardAfterRemoval', () => {
  it('returns next card alphabetically', () => {
    addCard('card_a', 'FATE', CARD_A, 10, 'IE');
    addCard('card_b', 'FATE', CARD_B, 20, 'IE');
    const next = nextCardAfterRemoval('FATE', 'card_a');
    assert.equal(next.id, 'card_b');
  });
});

describe('getDeckNavItems', () => {
  it('returns empty for empty side', () => {
    assert.deepEqual(getDeckNavItems('FATE'), []);
  });

  it('returns flat item for single-print card', () => {
    addCard('card_a', 'FATE', CARD_A, 10, 'IE');
    const items = getDeckNavItems('FATE');
    assert.equal(items.length, 1);
    assert.equal(items[0].id, 'card_a');
    assert.equal(items[0].printId, 10);
  });

  it('returns parent + children for multi-print card', () => {
    addCard('card_a', 'FATE', CARD_A, 10, 'IE');
    addCard('card_a', 'FATE', CARD_A, 20, 'Ivory');
    const items = getDeckNavItems('FATE');
    assert.equal(items.length, 3);
    assert.equal(items[0].printId, null);
    assert.equal(items[1].printId, 10);
    assert.equal(items[2].printId, 20);
  });

  it('groups by type alphabetically', () => {
    addCard('card_a', 'FATE', CARD_A, 10, 'IE');
    addCard('card_c', 'FATE', CARD_C, 30, 'Gold');
    const items = getDeckNavItems('FATE');
    assert.equal(items[0].card.types[0], 'Holding');
    assert.equal(items[1].card.types[0], 'Strategy');
  });
});
