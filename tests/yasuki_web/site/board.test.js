import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { resetDOM } from '../deck_builder/dom-shim.js';
import {
  renderBoard,
  renderTableau,
  renderHand,
  renderPanel,
  dragPosition,
  intentMessage,
  spawnMessage,
  removeMessage,
  moveIntent,
  flipIntent,
  bowIntent,
  drawIntent,
  initBoardInteractions,
  highlightCard,
  placeUnplacedCards,
  clampMenuPosition,
  setBackArt,
  backArtBySide,
} from '../../../src/yasuki_web/static/site/board.js';

beforeEach(() => {
  resetDOM();
  setBackArt({});
});

// A fake card element as the drag and context-menu handlers read it: a dataset matching what tagCard
// stamps, a settable style, a classList, geometry, and a `closest` that reports a province ancestor
// when one is supplied. onBattlefield decides whether a battlefield drop repositions or plays the card.
function fakeCard(
  id,
  {
    bowed = false,
    onBattlefield = true,
    side = '',
    owner = '',
    faceUp = true,
    hidden = false,
    doubleFaced = false,
    province = null,
  } = {},
) {
  const classes = new Set([onBattlefield ? 'board-card' : 'zone-card']);
  const dataset = {
    cardId: id,
    bowed: bowed ? '1' : '',
    side,
    owner,
    faceUp: faceUp ? '1' : '',
    hidden: hidden ? '1' : '',
  };
  if (doubleFaced) dataset.doubleFaced = '1';
  return {
    dataset,
    style: {},
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      contains: (c) => classes.has(c),
    },
    getBoundingClientRect: () => ({ left: 10, top: 20 }),
    closest: (sel) => (sel === '[data-zone="province"]' && province ? province : null),
  };
}

// A pointer/context event whose target resolves to `card` for the card selector.
function onCard(card, overrides = {}) {
  let prevented = false;
  return {
    button: 0,
    clientX: 30,
    clientY: 50,
    target: { closest: (sel) => (sel === '[data-card-id]' ? card : null) },
    preventDefault: () => {
      prevented = true;
    },
    get defaultPrevented() {
      return prevented;
    },
    ...overrides,
  };
}

// A pointer-up event over a drop zone described by `attrs` (the zone element's dataset).
function onZone(attrs, overrides = {}) {
  const el = { dataset: attrs };
  return {
    clientX: 120,
    clientY: 140,
    target: { closest: (sel) => (sel === '[data-zone]' ? el : null) },
    ...overrides,
  };
}

const offCard = (overrides = {}) => ({
  button: 0,
  clientX: 5,
  clientY: 5,
  target: { closest: () => null },
  preventDefault() {},
  ...overrides,
});

// The menu mounts on the board stage (the root), not the battlefield, so it floats above the hand.
const activeMenu = (stage) => stage.children.find((c) => c.className === 'board-menu');

// The non-separator menu labels, in order.
const menuLabels = (stage) =>
  activeMenu(stage)
    .children.filter((li) => li.className !== 'menu-sep')
    .map((li) => li.textContent);

function clickMenuItem(stage, label) {
  activeMenu(stage)
    .children.find((li) => li.textContent === label)
    ._emit('click', {});
}

// A right-click event resolving to a zone element and/or a card element, as menuItemsFor reads them.
function rightClick({ zone = null, card = null } = {}) {
  let prevented = false;
  const zoneEl = zone ? { dataset: zone } : null;
  return {
    clientX: 30,
    clientY: 50,
    target: {
      closest: (sel) => {
        if (sel === '[data-zone]') return zoneEl;
        if (sel === '[data-card-id]') return card;
        return null;
      },
    },
    preventDefault: () => {
      prevented = true;
    },
    get defaultPrevented() {
      return prevented;
    },
  };
}

const card = (overrides = {}) => ({
  id: 'c1',
  name: 'Hida Kisada',
  img: 'sets/imperial_edition/hida_kisada.jpg',
  x: 10,
  y: 20,
  bowed: false,
  face_up: true,
  hidden: false,
  inverted: false,
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

  it('marks inverted cards', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ inverted: true })], '/images');
    assert.ok(board.children[0].classList.contains('inverted'));
    assert.ok(!board.children[0].classList.contains('bowed'));
  });

  it('marks a card that is both bowed and inverted', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ bowed: true, inverted: true })], '/images');
    assert.ok(board.children[0].classList.contains('bowed'));
    assert.ok(board.children[0].classList.contains('inverted'));
  });

  it('draws the side-specific back for a face-down card, strongholds using the dynasty back', () => {
    setBackArt({
      FATE: '/img/sets/backs/fate_new.jpg',
      DYNASTY: '/img/sets/backs/dynasty_new.jpg',
      STRONGHOLD: '/img/sets/backs/dynasty_new.jpg',
    });
    const board = document.getElementById('battlefield');
    renderBoard(
      board,
      [
        { id: 'f', hidden: true, side: 'FATE', x: 0, y: 0 },
        { id: 'd', hidden: true, side: 'DYNASTY', x: 0, y: 0 },
        { id: 'sh', hidden: true, side: 'STRONGHOLD', x: 0, y: 0 },
      ],
      '/images',
    );
    assert.equal(board.children[0].children[0].src, '/img/sets/backs/fate_new.jpg');
    assert.equal(board.children[1].children[0].src, '/img/sets/backs/dynasty_new.jpg');
    assert.equal(board.children[2].children[0].src, '/img/sets/backs/dynasty_new.jpg');
  });

  it('draws the token back for a face-down spawned token', () => {
    setBackArt({
      DYNASTY: '/img/sets/backs/dynasty_new.jpg',
      TOKEN: '/img/sets/backs/dynasty_token.jpg',
    });
    const board = document.getElementById('battlefield');
    renderBoard(board, [{ id: 'spawn-3', hidden: true, side: 'DYNASTY', x: 0, y: 0 }], '/images');
    assert.equal(board.children[0].children[0].src, '/img/sets/backs/dynasty_token.jpg');
  });

  it('draws the side back for a known card lying face-down, not its front art', () => {
    setBackArt({ DYNASTY: '/img/sets/backs/dynasty_new.jpg' });
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ side: 'DYNASTY', face_up: false })], '/images');
    assert.equal(board.children[0].children[0].src, '/img/sets/backs/dynasty_new.jpg');
  });

  it('falls back to the gradient when no back art is loaded for the side', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [{ id: 'f', hidden: true, side: 'FATE', x: 0, y: 0 }], '/images');
    assert.ok(board.children[0].classList.contains('face-down'));
    assert.equal(board.children[0].children.length, 0);
  });

  it('renders the active (back) face of a flipped double-faced card via the normal art path', () => {
    const board = document.getElementById('battlefield');
    renderBoard(
      board,
      [card({ img: 'sets/x/sh__back.jpg', back_card_id: 'sh__back', showing_back: true })],
      '/images',
    );
    assert.equal(board.children[0].children[0].src, '/images/sets/x/sh__back.jpg');
    assert.equal(board.children[0].dataset.doubleFaced, '1');
  });
});

describe('backArtBySide', () => {
  const backs = {
    Fate: { old: 'sets/backs/fate_old.jpg', new: 'sets/backs/fate_new.jpg' },
    Dynasty: {
      old: 'sets/backs/dynasty_old.jpg',
      new: 'sets/backs/dynasty_new.jpg',
      token: 'sets/backs/dynasty_token.jpg',
    },
  };

  it('maps each side to its canonical generic back, strongholds to dynasty and tokens to the token back', () => {
    assert.deepEqual(backArtBySide(backs, '/img'), {
      FATE: '/img/sets/backs/fate_new.jpg',
      DYNASTY: '/img/sets/backs/dynasty_new.jpg',
      STRONGHOLD: '/img/sets/backs/dynasty_new.jpg',
      TOKEN: '/img/sets/backs/dynasty_token.jpg',
    });
  });

  it('leaves a key undefined when its back is absent', () => {
    assert.deepEqual(backArtBySide({}, '/img'), {
      FATE: undefined,
      DYNASTY: undefined,
      STRONGHOLD: undefined,
      TOKEN: undefined,
    });
  });
});

// A representative redacted snapshot for seat P1: two decks with counts, a two-card hand, four
// provinces (the first holding a face-down card), and an opponent whose hand is a back stub.
function seatSnapshot() {
  return {
    your_seat: 'P1',
    seats: {
      P1: { name: 'Ada', honor: 10, connected: true },
      P2: { name: 'Kenji', honor: 8, connected: true },
    },
    decks: {
      'P1:dynasty': { count: 38, top: null },
      'P1:fate': { count: 39, top: null },
    },
    zones: {
      'P1:hand': [card({ id: 'h1' }), card({ id: 'h2' })],
      'P1:province:0': [{ id: 'pv0', hidden: true }],
      'P1:province:1': [],
      'P1:province:2': [],
      'P1:province:3': [],
      'P2:hand': [{ id: 'oh1', hidden: true }],
    },
    battlefield: [],
  };
}

describe('renderTableau', () => {
  // The tableau is [left decks, provinces, right decks]; pre-game cards are loose on the battlefield.
  it('places the drawable dynasty deck and its count on the left', () => {
    const area = document.createElement('div');
    renderTableau(area, 'P1', seatSnapshot(), '/images');
    const dynasty = area.children[0].children[0];
    assert.ok(dynasty.className.includes('deck'));
    assert.equal(dynasty.dataset.owner, 'P1');
    assert.equal(dynasty.dataset.side, 'DYNASTY');
    assert.equal(dynasty.children[0].textContent, '38'); // face-down deck: count then label
  });

  it('lays out four provinces in the centre and the fate deck on the right', () => {
    const area = document.createElement('div');
    renderTableau(area, 'P1', seatSnapshot(), '/images');
    assert.equal(area.children[1].children.length, 4);
    const fate = area.children[2].children[1];
    assert.ok(fate.className.includes('deck'));
    assert.equal(fate.dataset.side, 'FATE');
  });

  it("shows each deck's side card back when its backs are loaded", () => {
    setBackArt({
      DYNASTY: '/img/sets/backs/dynasty_new.jpg',
      FATE: '/img/sets/backs/fate_new.jpg',
    });
    const area = document.createElement('div');
    renderTableau(area, 'P1', seatSnapshot(), '/images');
    // The back image is the pile's first child, ahead of the count and label spans.
    const dynastyBack = area.children[0].children[0].children[0];
    const fateBack = area.children[2].children[1].children[0];
    assert.equal(dynastyBack.className, 'pile-back');
    assert.equal(dynastyBack.src, '/img/sets/backs/dynasty_new.jpg');
    assert.equal(fateBack.src, '/img/sets/backs/fate_new.jpg');
  });
});

describe('renderHand', () => {
  it('renders the hand face up for the owner', () => {
    const hand = document.createElement('div');
    renderHand(hand, [card({ id: 'h1' }), card({ id: 'h2' })], '/images');
    assert.equal(hand.children.length, 2);
    assert.equal(hand.children[0].children[0].src, '/images/sets/imperial_edition/hida_kisada.jpg');
  });

  it('renders a hidden hand card as a back, never reaching for art', () => {
    const hand = document.createElement('div');
    renderHand(hand, [{ id: 'oh1', hidden: true }], '/images');
    assert.ok(hand.children[0].classList.contains('face-down'));
    assert.equal(hand.children[0].children.length, 0);
  });
});

describe('renderPanel', () => {
  it('shows the avatar initials, name, and honor', () => {
    const panel = document.createElement('div');
    renderPanel(panel, { name: 'Ada Crane', honor: 10, connected: true });
    assert.equal(panel.children[0].textContent, 'AC');
    assert.equal(panel.children[1].children[0].textContent, 'Ada Crane');
    assert.equal(panel.children[1].children[1].textContent, '10');
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

  it('builds a DRAW intent for a seat deck', () => {
    assert.deepEqual(drawIntent('P1', 'FATE'), {
      type: 'INTENT',
      intent: { op: 'DRAW', deck: { owner: 'P1', side: 'FATE' } },
    });
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
    // 500 - 81 wide, 400 - 115 tall — a full card stays on the board.
    assert.deepEqual(dragPosition(9999, 9999, board, { x: 0, y: 0 }), { x: 419, y: 285 });
  });
});

describe('placeUnplacedCards', () => {
  const anchorFor = (owner) => (owner === 'P1' ? { x: 20, y: 300 } : { x: 30, y: 40 });

  it('fans an owner\'s unplaced pre-game cards out from their anchor', () => {
    const cards = [
      { id: 'sh', pregame: true, owner: 'P1', x: -1, y: -1 },
      { id: 'se', pregame: true, owner: 'P1', x: -1, y: -1 },
    ];
    const placed = placeUnplacedCards(cards, 'P1', anchorFor);
    assert.deepEqual(placed[0], { id: 'sh', pregame: true, owner: 'P1', x: 20, y: 300 });
    assert.deepEqual(placed[1], { id: 'se', pregame: true, owner: 'P1', x: 40, y: 300 });
  });

  it('leaves already-placed cards (x >= 0) untouched, pre-game or not', () => {
    const moved = { id: 'sh', pregame: true, owner: 'P1', x: 120, y: 90 };
    const loose = { id: 'c1', pregame: false, owner: 'P1', x: 5, y: 5 };
    const placed = placeUnplacedCards([moved, loose], 'P1', anchorFor);
    assert.deepEqual(placed, [moved, loose]);
  });

  it('lays out an unplaced non-pre-game card (a dynasty draw with full provinces)', () => {
    const drawn = { id: 'd9', pregame: false, owner: 'P1', x: -1, y: -1 };
    const placed = placeUnplacedCards([drawn], 'P1', anchorFor);
    assert.deepEqual(placed[0], { id: 'd9', pregame: false, owner: 'P1', x: 20, y: 300 });
  });

  it('fans each owner from their own anchor, counting independently', () => {
    const cards = [
      { id: 'p1a', pregame: true, owner: 'P1', x: -1, y: -1 },
      { id: 'p2a', pregame: true, owner: 'P2', x: -1, y: -1 },
      { id: 'p1b', pregame: true, owner: 'P1', x: -1, y: -1 },
    ];
    const placed = placeUnplacedCards(cards, 'P1', anchorFor);
    assert.deepEqual([placed[0].x, placed[0].y], [20, 300]); // P1 first, no offset
    assert.deepEqual([placed[1].x, placed[1].y], [30, 40]); // P2 first, no offset
    assert.deepEqual([placed[2].x, placed[2].y], [40, 300]); // P1 second, one step
  });

  it('keeps a card unplaced when its owner has no anchor yet', () => {
    const cards = [{ id: 'sh', pregame: true, owner: 'P1', x: -1, y: -1 }];
    const placed = placeUnplacedCards(cards, 'P1', () => null);
    assert.equal(placed[0].x, -1);
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
  let root;
  let board;
  let sent;

  beforeEach(() => {
    root = document.getElementById('boardStage');
    board = document.getElementById('battlefield');
    sent = [];
    initBoardInteractions(root, board, (message) => sent.push(message));
  });

  it('ignores a non-left button press', () => {
    root._emit('pointerdown', onCard(fakeCard('c1'), { button: 2 }));
    root._emit('pointermove', { clientX: 99, clientY: 99 });
    assert.equal(sent.length, 0);
  });

  it('ignores a press that lands off any card', () => {
    root._emit('pointerdown', offCard());
    root._emit('pointermove', { clientX: 99, clientY: 99 });
    assert.equal(sent.length, 0);
  });

  it('sends a throttled SET_CARD_POS while dragging a battlefield card', () => {
    const cardEl = fakeCard('c1', { onBattlefield: true });
    const realNow = Date.now;
    Date.now = () => 1000;
    try {
      root._emit('pointerdown', onCard(cardEl));
      root._emit('pointermove', { clientX: 60, clientY: 70 });
      root._emit('pointermove', { clientX: 80, clientY: 90 }); // same tick → throttled out
    } finally {
      Date.now = realNow;
    }

    // grab offset is (30-10, 50-20) = (20, 30); board origin is (0, 0).
    assert.equal(cardEl.style.left, '60px'); // last move still repositions locally, though unsent
    assert.equal(sent.length, 1);
    assert.deepEqual(sent[0], {
      type: 'INTENT',
      intent: { op: 'SET_CARD_POS', card_id: 'c1', x: 40, y: 40 },
    });
  });

  it('does nothing on pointermove when no drag is active', () => {
    root._emit('pointermove', { clientX: 60, clientY: 70 });
    assert.equal(sent.length, 0);
  });

  it('repositions on a drop onto the battlefield, then ends the drag', () => {
    root._emit('pointerdown', onCard(fakeCard('c1', { onBattlefield: true })));
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    assert.equal(sent.at(-1).intent.op, 'SET_CARD_POS');

    sent.length = 0;
    root._emit('pointermove', { clientX: 200, clientY: 200 });
    assert.equal(sent.length, 0, 'drag ended, later moves are ignored');
  });

  it('plays a hand card onto the battlefield as a MOVE_CARD with a position', () => {
    root._emit('pointerdown', onCard(fakeCard('h1', { onBattlefield: false })));
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    const move = sent.at(-1).intent;
    assert.equal(move.op, 'MOVE_CARD');
    assert.deepEqual(move.to, { kind: 'battlefield' });
    assert.ok(Array.isArray(move.position));
  });

  it('moves a card onto a deck as a MOVE_CARD', () => {
    root._emit('pointerdown', onCard(fakeCard('c1')));
    root._emit('pointerup', onZone({ zone: 'deck', owner: 'P1', side: 'FATE' }));
    assert.deepEqual(sent.at(-1).intent, {
      op: 'MOVE_CARD',
      card_id: 'c1',
      to: { kind: 'deck', deck: { owner: 'P1', side: 'FATE' } },
      position: null,
    });
  });

  it('moves a card into a province as a MOVE_CARD', () => {
    root._emit('pointerdown', onCard(fakeCard('c1', { onBattlefield: false })));
    root._emit('pointerup', onZone({ zone: 'province', owner: 'P1', idx: '2' }));
    assert.deepEqual(sent.at(-1).intent.to, {
      kind: 'zone',
      zone: { owner: 'P1', role: 'province', idx: 2 },
    });
  });

  it('cancels a drag on pointercancel', () => {
    root._emit('pointerdown', onCard(fakeCard('c1')));
    root._emit('pointercancel', {});
    root._emit('pointermove', { clientX: 200, clientY: 200 });
    assert.equal(sent.length, 0);
  });
});

describe('initBoardInteractions — context menu', () => {
  let root;
  let board;
  let sent;

  beforeEach(() => {
    root = document.getElementById('boardStage');
    root.dataset.viewerSeat = 'P1';
    board = document.getElementById('battlefield');
    sent = [];
    initBoardInteractions(root, board, (message) => sent.push(message));
  });

  it("opens the full card menu on the viewer's own face-up card and suppresses the native menu", () => {
    const event = rightClick({ card: fakeCard('c1', { side: 'FATE', owner: 'P1' }) });
    root._emit('contextmenu', event);

    assert.equal(event.defaultPrevented, true);
    assert.deepEqual(menuLabels(root), [
      'Flip',
      'Bow',
      'Invert',
      'Send to Hand',
      'Send to Discard',
      'Send to Deck (top)',
      'Send to Deck (bottom)',
      'Remove',
    ]);
  });

  it('opens a hand card menu mounted on the stage, not the clipped battlefield', () => {
    const event = rightClick({
      zone: { zone: 'hand', owner: 'P1' },
      card: fakeCard('h1', { side: 'FATE', owner: 'P1', onBattlefield: false }),
    });
    root._emit('contextmenu', event);

    assert.ok(activeMenu(root), 'menu mounts on the board stage');
    assert.equal(activeMenu(board), undefined, 'menu is not trapped in the battlefield');
    assert.ok(menuLabels(root).includes('Flip'));
  });

  it('offers reveal/hide on a face-down card and omits the bow toggle in a province', () => {
    const province = { dataset: { zone: 'province', owner: 'P1', idx: '0' } };
    const card = fakeCard('c1', { side: 'DYNASTY', owner: 'P1', faceUp: false, province });
    // Right-clicking the province card resolves both the card and its province ancestor.
    root._emit('contextmenu', rightClick({ zone: province.dataset, card }));

    const labels = menuLabels(root);
    assert.ok(labels.includes('Reveal') && labels.includes('Hide'));
    assert.ok(!labels.includes('Bow') && !labels.includes('Unbow'), 'no bow toggle in a province');
    // The province lifecycle ops are appended after the card menu.
    assert.deepEqual(labels.slice(-3), ['Fill', 'Discard', 'Destroy']);
  });

  it('flips a double-faced card to its other face (FLIP_FACE), with no separate Turn Over', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { owner: 'P1', doubleFaced: true }) }));
    const labels = menuLabels(root);
    assert.ok(labels.includes('Flip') && !labels.includes('Turn Over'));
    clickMenuItem(root, 'Flip');
    assert.deepEqual(sent[0].intent, { op: 'FLIP_FACE', card_ids: ['c1'] });
  });

  it('flips a single-faced card between its front and back (FLIP)', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { owner: 'P1' }) }));
    clickMenuItem(root, 'Flip');
    assert.deepEqual(sent[0].intent, { op: 'FLIP', card_ids: ['c1'] });
  });

  it('omits the Send-to group on an opponent card', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { side: 'FATE', owner: 'P2' }) }));
    const labels = menuLabels(root);
    assert.deepEqual(labels, ['Flip', 'Bow', 'Invert', 'Remove']);
  });

  it('sends MOVE_CARD to the bottom of the deck from "Send to Deck (bottom)"', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { side: 'FATE', owner: 'P1' }) }));
    clickMenuItem(root, 'Send to Deck (bottom)');
    assert.deepEqual(sent[0].intent, {
      op: 'MOVE_CARD',
      card_id: 'c1',
      to: { kind: 'deck', deck: { owner: 'P1', side: 'FATE' } },
      position: null,
      to_bottom: true,
    });
  });

  it('sends a discard routed to the card side', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { side: 'DYNASTY', owner: 'P1' }) }));
    clickMenuItem(root, 'Send to Discard');
    assert.equal(sent[0].intent.to.zone.role, 'dynasty_discard');
  });

  it("opens the deck menu on the owner's deck, not the top card's menu", () => {
    const deck = { zone: 'deck', owner: 'P1', side: 'DYNASTY' };
    root._emit('contextmenu', rightClick({ zone: deck, card: fakeCard('top') }));
    assert.deepEqual(menuLabels(root), ['Draw', 'Shuffle', 'Flip Top', 'Search', 'Create Province']);
  });

  it('emits FLIP_DECK_TOP from the deck menu', () => {
    root._emit('contextmenu', rightClick({ zone: { zone: 'deck', owner: 'P1', side: 'FATE' } }));
    clickMenuItem(root, 'Flip Top');
    assert.deepEqual(sent[0].intent, { op: 'FLIP_DECK_TOP', deck: { owner: 'P1', side: 'FATE' } });
  });

  it('shows no deck menu for the opponent deck', () => {
    root._emit('contextmenu', rightClick({ zone: { zone: 'deck', owner: 'P2', side: 'FATE' } }));
    assert.equal(activeMenu(root), undefined);
  });

  it('opens the province menu on an empty province slot', () => {
    root._emit('contextmenu', rightClick({ zone: { zone: 'province', owner: 'P1', idx: '2' } }));
    assert.deepEqual(menuLabels(root), ['Fill', 'Discard', 'Destroy']);
    clickMenuItem(root, 'Fill');
    assert.deepEqual(sent[0].intent, {
      op: 'FILL_PROVINCE',
      zone: { owner: 'P1', role: 'province', idx: 2 },
    });
  });

  it('does not open a menu on empty space', () => {
    const event = offCard({
      preventDefault() {
        this._p = true;
      },
    });
    root._emit('contextmenu', event);
    assert.equal(activeMenu(root), undefined);
    assert.equal(event._p, undefined);
  });

  it('sends a REMOVE message and closes the menu on item click', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { owner: 'P1' }) }));
    clickMenuItem(root, 'Remove');

    assert.deepEqual(sent, [{ type: 'REMOVE', remove: { id: 'c1' } }]);
    assert.equal(activeMenu(root), undefined, 'menu is removed after a selection');
  });

  it('sends UNBOW for a card that is already bowed', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { owner: 'P1', bowed: true }) }));
    clickMenuItem(root, 'Unbow');
    assert.equal(sent[0].intent.op, 'UNBOW');
  });

  it('replaces a previously open menu rather than stacking', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { owner: 'P1' }) }));
    root._emit('contextmenu', rightClick({ card: fakeCard('c2', { owner: 'P1' }) }));
    assert.equal(root.children.filter((c) => c.className === 'board-menu').length, 1);
  });
});

describe('clampMenuPosition', () => {
  // 80x100 menu inside a 200x200 stage, 4px margin.
  it('leaves a menu that fits where it was asked to open', () => {
    assert.deepEqual(clampMenuPosition(30, 40, 80, 100, 200, 200), { left: 30, top: 40 });
  });

  it('pulls a menu back from the right edge', () => {
    assert.deepEqual(clampMenuPosition(180, 40, 80, 100, 200, 200), { left: 116, top: 40 });
  });

  it('pulls a menu up from the bottom edge so its options are not cut off', () => {
    assert.deepEqual(clampMenuPosition(30, 190, 80, 100, 200, 200), { left: 30, top: 96 });
  });

  it('never pushes a menu past the top-left when it is larger than the stage', () => {
    assert.deepEqual(clampMenuPosition(0, 0, 300, 300, 200, 200), { left: 4, top: 4 });
  });
});
