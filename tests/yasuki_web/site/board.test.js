import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { resetDOM } from '../deck_builder/dom-shim.js';
import { renderBoard, addCardFrame } from '../../../src/yasuki_web/static/site/board.js';

beforeEach(() => {
  resetDOM();
});

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
