import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { resetDOM } from '../deck_builder/dom-shim.js';
import {
  renderBoard,
  addCardFrame,
  dragPosition,
  moveAction,
  flagAction,
  removeAction,
  initBoardInteractions,
} from '../../../src/yasuki_web/static/site/board.js';

beforeEach(() => {
  resetDOM();
});

// A pointer/context event as initBoardInteractions reads it: cardUnder() resolves the target via
// closest('.board-card'), so a synthetic target exposes that plus the card geometry.
function eventOnCard(cardId, { clientX = 30, clientY = 50, button = 0, pointerId = 1 } = {}) {
  const cardEl = { dataset: { cardId }, getBoundingClientRect: () => ({ left: 10, top: 20 }) };
  let prevented = false;
  const event = {
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
  return event;
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
  ...overrides,
});

describe('renderBoard', () => {
  it('renders one positioned element per card', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ id: 'a', x: 10, y: 20 }), card({ id: 'b', x: 30, y: 40 })], '/images');
    assert.equal(board.children.length, 2);
    assert.equal(board.children[0].dataset.cardId, 'a');
    assert.equal(board.children[0].style.left, '10px');
    assert.equal(board.children[0].style.top, '20px');
  });

  it('shows the front image when face up', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card()], '/images');
    const img = board.children[0].children[0];
    assert.equal(img.src, '/images/sets/imperial_edition/hida_kisada.jpg');
  });

  it('hides the front and marks face-down cards', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ face_up: false })], '/images');
    assert.ok(board.children[0].classList.contains('face-down'));
    assert.equal(board.children[0].children.length, 0);
  });

  it('marks bowed cards', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ bowed: true })], '/images');
    assert.ok(board.children[0].classList.contains('bowed'));
  });

  it('clears prior cards on re-render', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ id: 'a' }), card({ id: 'b' })], '/images');
    renderBoard(board, [card({ id: 'c' })], '/images');
    assert.equal(board.children.length, 1);
    assert.equal(board.children[0].dataset.cardId, 'c');
  });
});

describe('addCardFrame', () => {
  it('builds an ADD_CARD board message for the room', () => {
    const frame = addCardFrame('r1', { id: 'c1', name: 'X', img: 'a.jpg', x: 10, y: 20 });
    assert.deepEqual(frame, {
      type: 'BOARD',
      room: 'r1',
      board: { kind: 'ADD_CARD', id: 'c1', name: 'X', img: 'a.jpg', x: 10, y: 20 },
    });
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

  it('clamps a card to the top-left corner', () => {
    assert.deepEqual(dragPosition(0, 0, board, { x: 50, y: 50 }), { x: 0, y: 0 });
  });

  it('clamps a card so it stays fully on the board', () => {
    assert.deepEqual(dragPosition(9999, 9999, board, { x: 0, y: 0 }), { x: 410, y: 272 });
  });
});

describe('board action builders', () => {
  it('build SET_CARD_POS, CARD_FLAG, and REMOVE_CARD actions', () => {
    assert.deepEqual(moveAction('c1', 5, 6), { kind: 'SET_CARD_POS', id: 'c1', x: 5, y: 6 });
    assert.deepEqual(flagAction('c1', 'bowed'), { kind: 'CARD_FLAG', id: 'c1', flag: 'bowed' });
    assert.deepEqual(removeAction('c1'), { kind: 'REMOVE_CARD', id: 'c1' });
  });
});

describe('initBoardInteractions — dragging', () => {
  let board;
  let sent;

  beforeEach(() => {
    board = document.getElementById('battlefield');
    sent = [];
    initBoardInteractions(board, (action) => sent.push(action));
  });

  it('ignores a non-left button press', () => {
    let captured = null;
    board.setPointerCapture = (id) => {
      captured = id;
    };
    board._emit('pointerdown', eventOnCard('c1', { button: 2 }));
    board._emit('pointermove', { clientX: 99, clientY: 99 });
    assert.equal(captured, null);
    assert.equal(sent.length, 0);
  });

  it('ignores a press that lands off any card', () => {
    board._emit('pointerdown', eventOnEmptySpace());
    board._emit('pointermove', { clientX: 99, clientY: 99 });
    assert.equal(sent.length, 0);
  });

  it('captures the pointer and sends a throttled position on drag', () => {
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
    assert.deepEqual(sent[0], { kind: 'SET_CARD_POS', id: 'c1', x: 40, y: 40 });
  });

  it('does nothing on pointermove when no drag is active', () => {
    board._emit('pointermove', { clientX: 60, clientY: 70 });
    assert.equal(sent.length, 0);
  });

  it('sends a final position on pointerup and ends the drag', () => {
    board._emit('pointerdown', eventOnCard('c1'));
    board._emit('pointerup', { clientX: 120, clientY: 140 });
    assert.equal(sent.at(-1).kind, 'SET_CARD_POS');

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
    initBoardInteractions(board, (action) => sent.push(action));
  });

  it('opens a Flip/Bow/Remove menu on a card and suppresses the native menu', () => {
    const event = eventOnCard('c1');
    board._emit('contextmenu', event);

    assert.equal(event.defaultPrevented, true);
    const menu = activeMenu(board);
    assert.ok(menu, 'a menu is appended to the board');
    assert.deepEqual(
      menu.children.map((li) => li.textContent),
      ['Flip', 'Bow / Unbow', 'Remove'],
    );
  });

  it('does not open a menu on empty space', () => {
    const event = eventOnEmptySpace({ preventDefault() { this._p = true; } });
    board._emit('contextmenu', event);
    assert.equal(activeMenu(board), undefined);
    assert.equal(event._p, undefined);
  });

  it('sends the chosen action and closes the menu on item click', () => {
    board._emit('contextmenu', eventOnCard('c1'));
    const remove = activeMenu(board).children[2];
    remove._emit('click', {});

    assert.deepEqual(sent, [{ kind: 'REMOVE_CARD', id: 'c1' }]);
    assert.equal(activeMenu(board), undefined, 'menu is removed after a selection');
  });

  it('replaces a previously open menu rather than stacking', () => {
    board._emit('contextmenu', eventOnCard('c1'));
    board._emit('contextmenu', eventOnCard('c2'));
    assert.equal(board.children.filter((c) => c.className === 'board-menu').length, 1);
  });
});
