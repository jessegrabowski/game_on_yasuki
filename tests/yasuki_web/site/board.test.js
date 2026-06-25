import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { resetDOM } from '../deck_builder/dom-shim.js';
import {
  renderBoard,
  dragPosition,
  intentMessage,
  spawnMessage,
  removeMessage,
  moveIntent,
  flipIntent,
  bowIntent,
  initBoardInteractions,
  highlightCard,
} from '../../../src/yasuki_web/static/site/board.js';

beforeEach(() => {
  resetDOM();
});

// A pointer/context event as initBoardInteractions reads it: cardUnder() resolves the target via
// closest('.board-card'); the card element exposes its geometry and bowed flag (read for the menu).
function eventOnCard(cardId, { clientX = 30, clientY = 50, button = 0, pointerId = 1, bowed = false } = {}) {
  const cardEl = {
    dataset: { cardId, bowed: bowed ? '1' : '' },
    getBoundingClientRect: () => ({ left: 10, top: 20 }),
  };
  let prevented = false;
  return {
    button,
    pointerId,
    clientX,
    clientY,
    target: { closest: (sel) => (sel === '.board-card' ? cardEl : null) },
    preventDefault: () => {
      prevented = true;
    },
    get defaultPrevented() {
      return prevented;
    },
  };
}

const eventOnEmptySpace = (overrides = {}) => ({
  button: 0,
  pointerId: 1,
  clientX: 5,
  clientY: 5,
  target: { closest: () => null },
  preventDefault() {},
  ...overrides,
});

const activeMenu = (board) => board.children.find((c) => c.className === 'board-menu');

const card = (overrides = {}) => ({
  id: 'c1',
  name: 'Hida Kisada',
  img: 'sets/imperial_edition/hida_kisada.jpg',
  x: 10,
  y: 20,
  bowed: false,
  face_up: true,
  hidden: false,
  ...overrides,
});

describe('renderBoard', () => {
  it('renders one positioned element per card', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ id: 'a', x: 10, y: 20 }), card({ id: 'b', x: 30, y: 40 })], '/images');
    assert.equal(board.children.length, 2);
    assert.equal(board.children[0].dataset.cardId, 'a');
    assert.equal(board.children[0].style.left, '10px');
  });

  it('shows the front image when face up', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card()], '/images');
    assert.equal(board.children[0].children[0].src, '/images/sets/imperial_edition/hida_kisada.jpg');
  });

  it('marks an explicitly face-down card as a back', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ face_up: false })], '/images');
    assert.ok(board.children[0].classList.contains('face-down'));
    assert.equal(board.children[0].children.length, 0);
  });

  it('renders a hidden stub as a back, never reaching for its (absent) art', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [{ id: 's1', hidden: true, x: 0, y: 0 }], '/images');
    assert.ok(board.children[0].classList.contains('face-down'));
    assert.equal(board.children[0].children.length, 0);
  });

  it('marks bowed cards', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ bowed: true })], '/images');
    assert.ok(board.children[0].classList.contains('bowed'));
    assert.equal(board.children[0].dataset.bowed, '1');
  });
});

describe('message builders', () => {
  it('wrap a SET_CARD_POS / FLIP / BOW intent', () => {
    assert.deepEqual(moveIntent('c1', 5, 6), {
      type: 'INTENT',
      intent: { op: 'SET_CARD_POS', card_id: 'c1', x: 5, y: 6 },
    });
    assert.deepEqual(flipIntent('c1'), { type: 'INTENT', intent: { op: 'FLIP', card_ids: ['c1'] } });
  });

  it('pick BOW or UNBOW from the card current state', () => {
    assert.equal(bowIntent('c1', false).intent.op, 'BOW');
    assert.equal(bowIntent('c1', true).intent.op, 'UNBOW');
  });

  it('build SPAWN and REMOVE messages', () => {
    assert.deepEqual(spawnMessage({ name: 'X', img: 'a.jpg', x: 1, y: 2 }), {
      type: 'SPAWN',
      spawn: { name: 'X', img: 'a.jpg', x: 1, y: 2 },
    });
    assert.deepEqual(removeMessage('c1'), { type: 'REMOVE', remove: { id: 'c1' } });
    assert.deepEqual(intentMessage({ op: 'FLIP', card_ids: ['c1'] }).type, 'INTENT');
  });
});

describe('dragPosition', () => {
  const board = { left: 0, top: 0, width: 500, height: 400 };

  it('subtracts the board offset and the grab offset', () => {
    assert.deepEqual(dragPosition(100, 90, { ...board, left: 50, top: 30 }, { x: 10, y: 20 }), {
      x: 40,
      y: 40,
    });
  });

  it('clamps a card so it stays fully on the board', () => {
    assert.deepEqual(dragPosition(0, 0, board, { x: 50, y: 50 }), { x: 0, y: 0 });
    assert.deepEqual(dragPosition(9999, 9999, board, { x: 0, y: 0 }), { x: 410, y: 272 });
  });
});

describe('highlightCard', () => {
  it('flashes the matching board card', () => {
    const board = document.getElementById('battlefield');
    const cardEl = document.createElement('div');
    board.querySelector = () => cardEl;

    const realSetTimeout = globalThis.setTimeout;
    globalThis.setTimeout = () => 0; // do not schedule the removal during the test
    try {
      highlightCard(board, 'c1');
    } finally {
      globalThis.setTimeout = realSetTimeout;
    }

    assert.ok(cardEl.classList.contains('highlight'));
  });

  it('is a no-op when the card is not on the board', () => {
    const board = document.getElementById('battlefield');
    board.querySelector = () => null;
    highlightCard(board, 'ghost'); // must not throw
  });
});

describe('initBoardInteractions — dragging', () => {
  let board;
  let sent;

  beforeEach(() => {
    board = document.getElementById('battlefield');
    sent = [];
    initBoardInteractions(board, (message) => sent.push(message));
  });

  it('ignores a non-left button press', () => {
    board.setPointerCapture = () => {};
    board._emit('pointerdown', eventOnCard('c1', { button: 2 }));
    board._emit('pointermove', { clientX: 99, clientY: 99 });
    assert.equal(sent.length, 0);
  });

  it('ignores a press that lands off any card', () => {
    board._emit('pointerdown', eventOnEmptySpace());
    board._emit('pointermove', { clientX: 99, clientY: 99 });
    assert.equal(sent.length, 0);
  });

  it('captures the pointer and sends a throttled SET_CARD_POS intent on drag', () => {
    let captured = null;
    board.setPointerCapture = (id) => {
      captured = id;
    };
    const moving = { style: {} };
    board.querySelector = () => moving;

    const realNow = Date.now;
    Date.now = () => 1000;
    try {
      board._emit('pointerdown', eventOnCard('c1', { pointerId: 7 }));
      board._emit('pointermove', { clientX: 60, clientY: 70 });
      board._emit('pointermove', { clientX: 80, clientY: 90 }); // same tick → throttled out
    } finally {
      Date.now = realNow;
    }

    // grab offset is (30-10, 50-20) = (20, 30); board origin is (0, 0).
    assert.equal(captured, 7);
    assert.equal(moving.style.left, '60px'); // second move still repositions locally, though unsent
    assert.equal(sent.length, 1);
    assert.deepEqual(sent[0], {
      type: 'INTENT',
      intent: { op: 'SET_CARD_POS', card_id: 'c1', x: 40, y: 40 },
    });
  });

  it('does nothing on pointermove when no drag is active', () => {
    board._emit('pointermove', { clientX: 60, clientY: 70 });
    assert.equal(sent.length, 0);
  });

  it('sends a final position on pointerup and ends the drag', () => {
    board._emit('pointerdown', eventOnCard('c1'));
    board._emit('pointerup', { clientX: 120, clientY: 140 });
    assert.equal(sent.at(-1).intent.op, 'SET_CARD_POS');

    sent.length = 0;
    board._emit('pointermove', { clientX: 200, clientY: 200 });
    assert.equal(sent.length, 0, 'drag ended, later moves are ignored');
  });

  it('cancels a drag on pointercancel', () => {
    board._emit('pointerdown', eventOnCard('c1'));
    board._emit('pointercancel', {});
    board._emit('pointermove', { clientX: 200, clientY: 200 });
    assert.equal(sent.length, 0);
  });
});

describe('initBoardInteractions — context menu', () => {
  let board;
  let sent;

  beforeEach(() => {
    board = document.getElementById('battlefield');
    sent = [];
    initBoardInteractions(board, (message) => sent.push(message));
  });

  it('opens a Flip/Bow/Remove menu on a card and suppresses the native menu', () => {
    const event = eventOnCard('c1');
    board._emit('contextmenu', event);

    assert.equal(event.defaultPrevented, true);
    const menu = activeMenu(board);
    assert.ok(menu);
    assert.deepEqual(
      menu.children.map((li) => li.textContent),
      ['Flip', 'Bow / Unbow', 'Remove'],
    );
  });

  it('does not open a menu on empty space', () => {
    const event = eventOnEmptySpace({
      preventDefault() {
        this._p = true;
      },
    });
    board._emit('contextmenu', event);
    assert.equal(activeMenu(board), undefined);
    assert.equal(event._p, undefined);
  });

  it('sends a REMOVE message and closes the menu on item click', () => {
    board._emit('contextmenu', eventOnCard('c1'));
    activeMenu(board).children[2]._emit('click', {});

    assert.deepEqual(sent, [{ type: 'REMOVE', remove: { id: 'c1' } }]);
    assert.equal(activeMenu(board), undefined, 'menu is removed after a selection');
  });

  it('sends UNBOW for a card that is already bowed', () => {
    board._emit('contextmenu', eventOnCard('c1', { bowed: true }));
    activeMenu(board).children[1]._emit('click', {}); // Bow / Unbow
    assert.equal(sent[0].intent.op, 'UNBOW');
  });

  it('replaces a previously open menu rather than stacking', () => {
    board._emit('contextmenu', eventOnCard('c1'));
    board._emit('contextmenu', eventOnCard('c2'));
    assert.equal(board.children.filter((c) => c.className === 'board-menu').length, 1);
  });
});
