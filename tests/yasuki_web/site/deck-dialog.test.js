import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { resetDOM } from '../deck_builder/dom-shim.js';
import { openDeckDialog } from '../../../src/yasuki_web/static/site/deck-dialog.js';

beforeEach(() => {
  resetDOM();
});

// A representative DECK_CONTENTS payload for seat P1's fate deck, top of deck first (see
// ServerDeckContents in src/yasuki_web/schemas.py and serialize_deck_cards in snapshot.py). The
// owner receives full identities, so each card carries name and art.
function deckContents() {
  return {
    deck: { owner: 'P1', side: 'FATE' },
    cards: [
      { id: 't3', name: 'Top Card', img: 'sets/x/t3.jpg', side: 'FATE', hidden: false },
      { id: 'm2', name: 'Mid Card', img: 'sets/x/m2.jpg', side: 'FATE', hidden: false },
      { id: 'b1', name: 'Bottom Card', img: 'sets/x/b1.jpg', side: 'FATE', hidden: false },
    ],
  };
}

const open = (overrides = {}) => {
  const sent = [];
  const payload = deckContents();
  const handle = openDeckDialog({
    deck: payload.deck,
    cards: payload.cards,
    imgBase: '/images',
    send: (frame) => sent.push(frame),
    ...overrides,
  });
  return { handle, sent };
};

// Layout: overlay > modal > [header, filterInput, body]; body > [list, preview]; preview > [img, pull].
const modalOf = (overlay) => overlay.children[0];
const filterOf = (overlay) => modalOf(overlay).children[1];
const listOf = (overlay) => modalOf(overlay).children[2].children[0];
const previewOf = (overlay) => modalOf(overlay).children[2].children[1];
const names = (overlay) => listOf(overlay).children.map((li) => li.dataset.cardId);
const selectedName = (overlay) =>
  listOf(overlay).children.find((li) => li.classList.contains('selected'))?.dataset.cardId;

describe('openDeckDialog', () => {
  it('lists the deck top-first, first card selected with its art previewed', () => {
    const { handle } = open();
    assert.deepEqual(names(handle.el), ['t3', 'm2', 'b1']);
    assert.equal(selectedName(handle.el), 't3');
    assert.equal(previewOf(handle.el).children[0].src, '/images/sets/x/t3.jpg');
  });

  it('filters by title while preserving the underlying order', () => {
    const { handle } = open();
    const filter = filterOf(handle.el);
    filter.value = 'o'; // matches Top Card and Bottom Card, skips Mid Card
    filter._emit('input', {});
    assert.deepEqual(names(handle.el), ['t3', 'b1']);
  });

  it('previews the card whose name is clicked', () => {
    const { handle } = open();
    listOf(handle.el).children[1]._emit('click', {}); // Mid Card
    assert.equal(selectedName(handle.el), 'm2');
    assert.equal(previewOf(handle.el).children[0].src, '/images/sets/x/m2.jpg');
  });

  it('pulls the selected card to the battlefield above its dynasty deck', () => {
    const { handle, sent } = open();
    listOf(handle.el).children[1]._emit('click', {}); // select Mid Card
    previewOf(handle.el).children[1]._emit('click', {}); // Pull
    assert.deepEqual(sent, [
      {
        type: 'INTENT',
        intent: {
          op: 'MOVE_CARD',
          card_id: 'm2',
          to: { kind: 'battlefield' },
          position: [-1, -1],
        },
      },
    ]);
  });

  it('drops the pulled card from the list, advances selection, and stays open', () => {
    let closed = 0;
    const { handle } = open({ onClose: () => (closed += 1) });
    listOf(handle.el).children[1]._emit('click', {}); // select Mid Card
    previewOf(handle.el).children[1]._emit('click', {}); // Pull
    assert.deepEqual(names(handle.el), ['t3', 'b1'], 'pulled card leaves the list');
    assert.equal(selectedName(handle.el), 'b1', 'selection slides to the next card');
    assert.equal(closed, 0, 'the dialog stays open for more pulls');
  });

  it('caps the list to the top N when a limit is given', () => {
    const { handle } = open({ limit: 2 });
    assert.deepEqual(names(handle.el), ['t3', 'm2']);
  });

  it('closes on a backdrop click but not a click inside the modal', () => {
    let closed = 0;
    const { handle } = open({ onClose: () => (closed += 1) });
    handle.el._emit('click', { target: modalOf(handle.el) });
    assert.equal(closed, 0, 'a click inside the modal keeps it open');
    handle.el._emit('click', { target: handle.el });
    assert.equal(closed, 1, 'a click on the backdrop closes it');
  });

  it('closes from the header close button, and close is idempotent', () => {
    let closed = 0;
    const { handle } = open({ onClose: () => (closed += 1) });
    modalOf(handle.el).children[0].children[1]._emit('click', {}); // close button
    handle.close();
    assert.equal(closed, 1, 'closing twice fires onClose once');
  });

  const footerOf = (overlay) => modalOf(overlay).children[3];

  it('closes from the footer Close button without sending anything', () => {
    let closed = 0;
    const { handle, sent } = open({ onClose: () => (closed += 1) });
    footerOf(handle.el).children[0]._emit('click', {}); // Close
    assert.equal(closed, 1);
    assert.deepEqual(sent, []);
  });

  it('shuffles the deck and closes from "Close and shuffle"', () => {
    let closed = 0;
    const { handle, sent } = open({ onClose: () => (closed += 1) });
    footerOf(handle.el).children[1]._emit('click', {}); // Close and shuffle
    assert.equal(sent[0].intent.op, 'SHUFFLE');
    assert.deepEqual(sent[0].intent.deck, { owner: 'P1', side: 'FATE' });
    assert.equal(closed, 1);
  });
});
