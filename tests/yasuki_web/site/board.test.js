import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { resetDOM } from '../deck_builder/dom-shim.js';
import {
  renderBoard,
  renderTableau,
  renderHand,
  renderPanel,
  dragPosition,
  dragVisualPosition,
  grabOffset,
  handDropIndex,
  listDropIndex,
  reorderPileIntent,
  deckDest,
  intentMessage,
  spawnMessage,
  removeMessage,
  moveIntent,
  moveGroupIntent,
  flipIntent,
  bowIntent,
  setNoteIntent,
  showIntent,
  unshowIntent,
  peekIntent,
  unpeekIntent,
  drawIntent,
  honorIntent,
  initBoardInteractions,
  initPanelHonor,
  highlightCard,
  placeUnplacedCards,
  clampMenuPosition,
  setBackArt,
  backArtBySide,
  artSpec,
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
    token = false,
    shown = false,
    peeked = false,
    province = null,
    inHand = false,
    inDiscard = false,
    img = null,
    note = '',
    name = '',
    pregame = false,
    x = null,
    y = null,
  } = {},
) {
  const hand = inHand ? { dataset: { zone: 'hand', owner } } : null;
  const discard = inDiscard ? { dataset: { zone: 'discard', owner } } : null;
  const classes = new Set([onBattlefield ? 'board-card' : 'zone-card']);
  if (bowed) classes.add('bowed');
  if (!faceUp || hidden) classes.add('face-down');
  const dataset = {
    cardId: id,
    bowed: bowed ? '1' : '',
    side,
    owner,
    faceUp: faceUp ? '1' : '',
    hidden: hidden ? '1' : '',
    token: token ? '1' : '',
    shown: shown ? '1' : '',
    peeked: peeked ? '1' : '',
    note,
    name,
    img: img ?? '',
    pregame: pregame ? '1' : '',
  };
  if (doubleFaced) dataset.doubleFaced = '1';
  const style = {};
  if (x != null) style.left = `${x}px`;
  if (y != null) style.top = `${y}px`;
  return {
    dataset,
    style,
    classList: {
      add: (c) => classes.add(c),
      remove: (c) => classes.delete(c),
      contains: (c) => classes.has(c),
      toggle: (c, force) => (force ? classes.add(c) : classes.delete(c)),
    },
    getBoundingClientRect: () => ({ left: 10, top: 20, width: 81, height: 115, right: 91, bottom: 135 }),
    closest: (sel) => {
      if (sel === '[data-zone="province"]') return province;
      if (sel === '[data-zone="hand"]') return hand;
      if (sel === '[data-zone="discard"]') return discard;
      return null;
    },
    querySelector: (sel) => (sel === 'img' && img ? { src: img } : null),
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

// A pointer-down on a deck pile: `attrs` is the deck tile's dataset (owner + side). The pile shows a
// hidden back, so it resolves as a [data-zone="deck"] with no [data-card-id] beneath the pointer.
function onDeck(attrs, overrides = {}) {
  const el = {
    dataset: attrs,
    style: {},
    classList: { add() {}, remove() {}, contains: () => false },
    getBoundingClientRect: () => ({ left: 0, top: 0 }),
    querySelector: () => null,
  };
  return {
    button: 0,
    clientX: 30,
    clientY: 50,
    target: { closest: (sel) => (sel === '[data-zone="deck"]' ? el : null) },
    ...overrides,
  };
}

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

  it('overlays a note over a face-up card, verbatim', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ note: 'dead' })], '/images');
    const noteEl = board.children[0].children.find((c) => c.className === 'card-note');
    assert.equal(noteEl?.textContent, 'dead');
    assert.equal(board.children[0].dataset.note, 'dead');
  });

  it('draws no note on a face-down card (its front, and the note, stay hidden)', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ face_up: false, note: 'dead' })], '/images');
    assert.ok(!board.children[0].children.some((c) => c.className === 'card-note'));
  });

  it('tags a token card so the menu can gate Remove on it, and a real card as non-token', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ id: 'tok', token: true }), card({ id: 'real' })], '/images');
    assert.equal(board.children[0].dataset.token, '1');
    assert.equal(board.children[1].dataset.token, '');
  });

  it('tags and classes a shown card so the public indicator and menu can read it', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ shown: true })], '/images');
    assert.ok(board.children[0].classList.contains('shown'));
    assert.equal(board.children[0].dataset.shown, '1');
    assert.equal(board.children[0].dataset.peeked, '');
  });

  it('tags and classes a peeked card so the private-peek cue and menu can read it', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ peeked: true })], '/images');
    assert.ok(board.children[0].classList.contains('peeked'));
    assert.equal(board.children[0].dataset.peeked, '1');
    assert.equal(board.children[0].dataset.shown, '');
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

  it('renders the base print for a card with borrowed art (the swap composites best-effort)', () => {
    const hand = document.createElement('div');
    const swapped = card({ id: 'h1', art: { donor_img: 'sets/le/ambush.png', era: '2016+', layout: 'Personality', keywords: [], donor_era: '1995-99', donor_layout: 'Strategy' } });
    renderHand(hand, [swapped], '/images');
    // The base printing shows immediately; the canvas recomposite (untestable in the fake DOM) only
    // upgrades the src later, so the render never blocks on it.
    assert.equal(hand.children[0].children[0].src, '/images/sets/imperial_edition/hida_kisada.jpg');
  });
});

// artSpec is the pure data seam: a snapshot card + its art donor payload → the compositor's spec.
// The canvas itself is browser-only and deliberately not exercised through the fake DOM.
describe('artSpec', () => {
  it('maps a card and its donor payload to the deck-builder compositor spec', () => {
    const c = {
      img: 'sets/pe/kuni_yori.png',
      art: {
        donor_img: 'sets/le/ambush.png',
        era: '2016+',
        layout: 'Personality',
        keywords: ['Shadowlands', 'Berserker'],
        donor_era: '1995-99',
        donor_layout: 'Strategy',
      },
    };
    assert.deepEqual(artSpec(c), {
      recipientImagePath: 'sets/pe/kuni_yori.png',
      recipientEra: '2016+',
      recipientLayout: 'Personality',
      recipientKeywords: ['Shadowlands', 'Berserker'],
      donorImagePath: 'sets/le/ambush.png',
      donorEra: '1995-99',
      donorLayout: 'Strategy',
    });
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

  it('marks the local honor editable and the opponent honor read-only', () => {
    const self = document.createElement('div');
    const opp = document.createElement('div');
    renderPanel(self, { name: 'Ada', honor: 10 }, { editable: true });
    renderPanel(opp, { name: 'Kenji', honor: 8 }, { editable: false });
    assert.ok(self.children[1].children[1].classList.contains('is-editable'));
    assert.ok(opp.children[1].children[1].classList.contains('read-only'));
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

  it('wraps a SET_NOTE carrying the card id and text', () => {
    assert.deepEqual(setNoteIntent('c1', 'dead').intent, {
      op: 'SET_NOTE',
      card_id: 'c1',
      text: 'dead',
    });
  });

  it('wraps a REORDER_PILE carrying the pile dest and top-first index', () => {
    assert.deepEqual(reorderPileIntent(deckDest('P1', 'FATE'), 'c1', 2).intent, {
      op: 'REORDER_PILE',
      to: { kind: 'deck', deck: { owner: 'P1', side: 'FATE' } },
      card_id: 'c1',
      value: 2,
    });
  });

  it('wraps a batched SET_CARD_POSITIONS group move', () => {
    const moves = [
      { id: 'c1', x: 5, y: 6 },
      { id: 'c2', x: 7, y: 8 },
    ];
    assert.deepEqual(moveGroupIntent(moves), {
      type: 'INTENT',
      intent: { op: 'SET_CARD_POSITIONS', moves },
    });
  });

  it('pick BOW or UNBOW from the card current state', () => {
    assert.equal(bowIntent('c1', false).intent.op, 'BOW');
    assert.equal(bowIntent('c1', true).intent.op, 'UNBOW');
  });

  it('builds single-card SHOW/UNSHOW/PEEK/UNPEEK intents', () => {
    assert.deepEqual(showIntent('c1'), { type: 'INTENT', intent: { op: 'SHOW', card_id: 'c1' } });
    assert.deepEqual(unshowIntent('c1'), { type: 'INTENT', intent: { op: 'UNSHOW', card_id: 'c1' } });
    assert.deepEqual(peekIntent('c1'), { type: 'INTENT', intent: { op: 'PEEK', card_id: 'c1' } });
    assert.deepEqual(unpeekIntent('c1'), { type: 'INTENT', intent: { op: 'UNPEEK', card_id: 'c1' } });
  });

  it('builds a DRAW intent for a seat deck', () => {
    assert.deepEqual(drawIntent('P1', 'FATE'), {
      type: 'INTENT',
      intent: { op: 'DRAW', deck: { owner: 'P1', side: 'FATE' } },
    });
  });

  it('wraps a signed SET_HONOR delta', () => {
    assert.deepEqual(honorIntent(1), { type: 'INTENT', intent: { op: 'SET_HONOR', delta: 1 } });
    assert.deepEqual(honorIntent(-1), { type: 'INTENT', intent: { op: 'SET_HONOR', delta: -1 } });
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

describe('grabOffset', () => {
  it('measures from the box top-left for an upright card (rect equals box)', () => {
    assert.deepEqual(grabOffset({ left: 100, top: 200, width: 81, height: 115 }, 120, 230), {
      x: 20,
      y: 30,
    });
  });

  it('compensates for a bowed card whose bounding rect has swapped axes', () => {
    // A bowed card's rect is 115x81, centred on the same point as its unrotated 81x115 box, whose
    // top-left is therefore (117, 183). A pointer at (137, 213) is offset (20, 30) into that box, so
    // the drag (which sets style.left/top on the unrotated box) keeps it under the pointer — no pop.
    assert.deepEqual(grabOffset({ left: 100, top: 200, width: 115, height: 81 }, 137, 213), {
      x: 20,
      y: 30,
    });
  });
});

describe('dragVisualPosition', () => {
  const board = { left: 0, top: 0, width: 500, height: 400 };

  it('clamps x and the top but leaves the bottom free, so a card can head for the hand', () => {
    // Far below the board: y follows the pointer (unclamped), x still pinned on-board.
    assert.deepEqual(dragVisualPosition(9999, 600, board, { x: 0, y: 0 }), { x: 419, y: 600 });
    assert.deepEqual(dragVisualPosition(0, -50, board, { x: 0, y: 0 }), { x: 0, y: 0 });
  });
});

describe('handDropIndex', () => {
  // Three 80px-wide hand cards at x = 0, 100, 200 (centres 40, 140, 240).
  const handCard = (id, left) => ({ dataset: { cardId: id }, getBoundingClientRect: () => ({ left, width: 80 }) });
  const hand = { children: [handCard('a', 0), handCard('b', 100), handCard('c', 200)] };

  it('counts the cards whose centre the pointer has crossed', () => {
    assert.equal(handDropIndex(hand, 30, 'x'), 0); // left of every centre
    assert.equal(handDropIndex(hand, 150, 'x'), 2); // past a and b
    assert.equal(handDropIndex(hand, 999, 'x'), 3); // past all → the end
  });

  it('skips the dragged card so the slot is relative to the others', () => {
    assert.equal(handDropIndex(hand, 250, 'b'), 2); // a, then c — b excluded
  });
});

describe('listDropIndex', () => {
  // Three 20px-tall rows at y = 0, 100, 200 (centres 10, 110, 210).
  const row = (id, top) => ({ dataset: { cardId: id }, getBoundingClientRect: () => ({ top, height: 20 }) });
  const list = { children: [row('a', 0), row('b', 100), row('c', 200)] };

  it('counts the rows whose centre the pointer has crossed', () => {
    assert.equal(listDropIndex(list, 5, 'x'), 0); // above every centre
    assert.equal(listDropIndex(list, 150, 'x'), 2); // past a and b
    assert.equal(listDropIndex(list, 999, 'x'), 3); // past all → the end
  });

  it('skips the dragged row so the slot is relative to the others', () => {
    assert.equal(listDropIndex(list, 250, 'b'), 2); // a, then c — b excluded
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

  it('anchors a fate card to the fate deck and fans the two sides independently', () => {
    const anchorBySide = (owner, isViewer, side) =>
      side === 'FATE' ? { x: 100, y: 200 } : { x: 20, y: 300 };
    const cards = [
      { id: 'f1', owner: 'P1', side: 'FATE', x: -1, y: -1 },
      { id: 'd1', owner: 'P1', side: 'DYNASTY', x: -1, y: -1 },
      { id: 'f2', owner: 'P1', side: 'FATE', x: -1, y: -1 },
    ];
    const placed = placeUnplacedCards(cards, 'P1', anchorBySide);
    assert.deepEqual([placed[0].x, placed[0].y], [100, 200]); // fate, first
    assert.deepEqual([placed[1].x, placed[1].y], [20, 300]); // dynasty, first — fans right
    assert.deepEqual([placed[2].x, placed[2].y], [80, 200]); // fate, second — fans left, toward centre
  });

  it('groups a pre-game card by its pre-game role, not its side (a fate sensei)', () => {
    const anchorByGroup = (owner, isViewer, group) =>
      ({ PREGAME: { x: 200, y: 50 }, FATE: { x: 100, y: 200 }, DYNASTY: { x: 20, y: 300 } })[group];
    const cards = [
      { id: 'sensei', pregame: true, side: 'FATE', owner: 'P1', x: -1, y: -1 },
      { id: 'stronghold', pregame: true, side: 'DYNASTY', owner: 'P1', x: -1, y: -1 },
    ];
    const placed = placeUnplacedCards(cards, 'P1', anchorByGroup);
    assert.deepEqual([placed[0].x, placed[0].y], [200, 50]); // fate sensei → pre-game stack, first
    assert.deepEqual([placed[1].x, placed[1].y], [220, 50]); // stronghold → same stack, fans right
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

  it('lifts a card out of hit-testing only once it moves, so a plain press stays clickable', () => {
    const cardEl = fakeCard('c1', { onBattlefield: true });
    root._emit('pointerdown', onCard(cardEl));
    assert.notEqual(cardEl.style.pointerEvents, 'none', 'a press alone leaves the card interactive');
    root._emit('pointermove', { clientX: 80, clientY: 90 });
    assert.equal(cardEl.style.pointerEvents, 'none', 'a real drag lifts it out of hit-testing');
  });

  it('moves a battlefield card locally during the drag without streaming, committing on drop', () => {
    const cardEl = fakeCard('c1', { onBattlefield: true });
    root._emit('pointerdown', onCard(cardEl));
    root._emit('pointermove', { clientX: 60, clientY: 70 });
    root._emit('pointermove', { clientX: 80, clientY: 90 });

    // grab offset is (30-10, 50-20) = (20, 30); the card follows locally but nothing is sent yet —
    // streaming would echo a snapshot that snaps it back from the hand it may be crossing into.
    assert.equal(cardEl.style.left, '60px');
    assert.equal(sent.length, 0, 'no live stream during the drag');

    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    assert.equal(sent.length, 1, 'the move is sent once, on drop');
    assert.equal(sent[0].intent.op, 'SET_CARD_POS');
  });

  it('does nothing on pointermove when no drag is active', () => {
    root._emit('pointermove', { clientX: 60, clientY: 70 });
    assert.equal(sent.length, 0);
  });

  it('repositions on a drop onto the battlefield, then ends the drag', () => {
    root._emit('pointerdown', onCard(fakeCard('c1', { onBattlefield: true })));
    root._emit('pointermove', { clientX: 70, clientY: 80 });
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

  it('drags a face-up hand card with a ghost showing its front art', () => {
    root._emit(
      'pointerdown',
      onCard(fakeCard('h1', { onBattlefield: false, img: '/images/foo.jpg' })),
    );
    root._emit('pointermove', { clientX: 90, clientY: 90 });
    const ghost = board.children.find((c) => c.className?.includes('dragging'));
    assert.ok(ghost, 'a ghost follows the dragged hand card');
    assert.equal(ghost.style.pointerEvents, 'none', 'the ghost must not intercept the drop');
    assert.equal(ghost.children[0]?.src, '/images/foo.jpg', 'the ghost mirrors the card front');
    assert.ok(!ghost.classList.contains('face-down'));
  });

  it('lets a ghost-dragged card follow the pointer below the board edge too', () => {
    root._emit('pointerdown', onCard(fakeCard('h1', { onBattlefield: false, side: 'FATE', img: '/images/foo.jpg' })));
    root._emit('pointermove', { clientX: 90, clientY: 300 }); // below the 200-tall fixture board
    const ghost = board.children.find((c) => c.className?.includes('dragging'));
    assert.equal(ghost.style.top, '270px', 'the ghost crosses the board edge like a battlefield card');
  });

  it('drags a face-down province card with a face-down ghost, not its art', () => {
    const province = { dataset: { zone: 'province', owner: 'P1', idx: '0' } };
    root._emit(
      'pointerdown',
      onCard(fakeCard('p1', { onBattlefield: false, faceUp: false, province })),
    );
    root._emit('pointermove', { clientX: 90, clientY: 90 });
    const ghost = board.children.find((c) => c.className?.includes('dragging'));
    assert.ok(ghost.classList.contains('face-down'), 'a face-down card drags a back');
    assert.equal(ghost.children.length, 0, 'no front art leaks from a face-down card');
  });

  it('hides the source card once its ghost appears', () => {
    const handCard = fakeCard('h1', { onBattlefield: false });
    root._emit('pointerdown', onCard(handCard));
    assert.notEqual(handCard.style.visibility, 'hidden', 'a plain press leaves it visible');
    root._emit('pointermove', { clientX: 90, clientY: 90 });
    assert.equal(handCard.style.visibility, 'hidden', 'the source vanishes once the ghost appears');
  });

  it('mirrors the orientation of a bowed card onto its ghost', () => {
    root._emit(
      'pointerdown',
      onCard(fakeCard('h1', { onBattlefield: false, bowed: true, img: '/images/foo.jpg' })),
    );
    root._emit('pointermove', { clientX: 90, clientY: 90 });
    const ghost = board.children.find((c) => c.className?.includes('dragging'));
    assert.ok(ghost.classList.contains('bowed'), 'the ghost is bowed like the card it stands in for');
  });

  it('keeps a dragged battlefield card visible — it is the moving element, not a ghost', () => {
    const boardCard = fakeCard('c1', { onBattlefield: true });
    root._emit('pointerdown', onCard(boardCard));
    root._emit('pointermove', { clientX: 90, clientY: 90 });
    assert.notEqual(boardCard.style.visibility, 'hidden');
    assert.ok(!board.children.some((c) => c.className?.includes('dragging')), 'no ghost on the board');
  });

  it('restores the source if the drag is cancelled before a drop', () => {
    const handCard = fakeCard('h1', { onBattlefield: false });
    root._emit('pointerdown', onCard(handCard));
    root._emit('pointermove', { clientX: 90, clientY: 90 });
    root._emit('pointercancel', {});
    assert.equal(handCard.style.visibility, '', 'a cancelled drag leaves the card visible');
  });

  it('keeps the source hidden after a committed drop, letting the snapshot rebuild it', () => {
    const handCard = fakeCard('h1', { onBattlefield: false });
    root._emit('pointerdown', onCard(handCard));
    root._emit('pointermove', { clientX: 90, clientY: 90 });
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    assert.equal(handCard.style.visibility, 'hidden', 'no flash back into the source zone');
  });

  it('restores the source when a drop commits no move', () => {
    const handCard = fakeCard('h1', { onBattlefield: false });
    root._emit('pointerdown', onCard(handCard));
    root._emit('pointermove', { clientX: 90, clientY: 90 });
    root._emit('pointerup', { clientX: 300, clientY: 300, target: { closest: () => null } });
    assert.equal(handCard.style.visibility, '', 'a drop onto nothing brings the card back');
  });

  it('keeps the source hidden when committed to a zone destination, not just the battlefield', () => {
    const handCard = fakeCard('h1', { onBattlefield: false });
    root._emit('pointerdown', onCard(handCard));
    root._emit('pointermove', { clientX: 90, clientY: 90 });
    root._emit('pointerup', onZone({ zone: 'deck', owner: 'P1', side: 'FATE' }));
    assert.equal(sent.at(-1).intent.op, 'MOVE_CARD');
    assert.equal(handCard.style.visibility, 'hidden', 'a zone-dest drop commits too');
  });

  // A fake hand strip: a Set-backed classList for the drop-target glow, ordered children, and the
  // insertBefore the gap logic reorders by.
  const fakeHand = (owner, cards = []) => {
    const classes = new Set();
    const children = [...cards];
    const hand = {
      dataset: { zone: 'hand', owner },
      classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), has: (c) => classes.has(c) },
      get children() {
        return children;
      },
      insertBefore(child, ref) {
        const from = children.indexOf(child);
        if (from >= 0) children.splice(from, 1);
        children.splice(ref ? children.indexOf(ref) : children.length, 0, child);
        child.parentNode = hand;
      },
    };
    return hand;
  };
  const handCardEl = (id, left) => ({
    dataset: { cardId: id },
    getBoundingClientRect: () => ({ left, width: 80 }),
  });
  const overHand = (hand, clientY = 300) => ({
    target: { closest: (s) => (s === '[data-zone="hand"]' ? hand : null) },
    clientX: 90,
    clientY,
  });

  it('lets a board card follow the pointer below the board edge, toward the hand', () => {
    const cardEl = fakeCard('c1', { onBattlefield: true, side: 'FATE' });
    root._emit('pointerdown', onCard(cardEl));
    root._emit('pointermove', { clientX: 90, clientY: 300 }); // far below the 200-tall fixture board
    assert.equal(cardEl.style.top, '270px', 'the card follows the pointer down past the board edge');
    assert.equal(sent.length, 0, 'nothing is streamed mid-drag to snap it back');
  });

  it('lifts the board clip while dragging so a card can cross into the hand, restoring it on drop', () => {
    root._emit('pointerdown', onCard(fakeCard('c1', { onBattlefield: true, side: 'FATE' })));
    assert.ok(!board.classList.contains('is-dragging'), 'a plain press does not lift the clip');
    root._emit('pointermove', { clientX: 90, clientY: 300 });
    assert.ok(board.classList.contains('is-dragging'), 'a real drag lifts it');
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    assert.ok(!board.classList.contains('is-dragging'), 'and it is restored on release');
  });

  it('drops a board card into the hand as a MOVE_CARD landing at the previewed slot', () => {
    root._emit('pointerdown', onCard(fakeCard('c1', { onBattlefield: true, side: 'FATE' })));
    root._emit('pointermove', { clientX: 90, clientY: 300 });
    root._emit('pointerup', onZone({ zone: 'hand', owner: 'P1' }));
    assert.deepEqual(sent.at(-1).intent, {
      op: 'MOVE_CARD',
      card_id: 'c1',
      to: { kind: 'zone', zone: { owner: 'P1', role: 'hand', idx: null } },
      position: null,
      value: 0, // an empty drop target → slot 0
    });
  });

  it('opens a placeholder gap for an incoming card so the hand makes room', () => {
    root.dataset.viewerSeat = 'P1';
    const handEl = fakeHand('P1', [handCardEl('h1', 0), handCardEl('h3', 200)]);
    root._emit('pointerdown', onCard(fakeCard('b1', { onBattlefield: true, side: 'FATE' })));
    root._emit('pointermove', { clientX: 250, clientY: 300, target: { closest: () => handEl } });
    const gap = handEl.children.find((c) => c.className?.includes('hand-gap'));
    assert.ok(gap, 'a placeholder gap opens in the hand');
    assert.equal(handEl.children.indexOf(gap), 2, 'at the landing slot, past both cards');
  });

  it('lands an incoming card at the previewed slot, not just the end', () => {
    root.dataset.viewerSeat = 'P1';
    const handEl = fakeHand('P1', [handCardEl('h1', 0), handCardEl('h3', 200)]);
    root._emit('pointerdown', onCard(fakeCard('b1', { onBattlefield: true, side: 'FATE' })));
    root._emit('pointermove', { clientX: 150, clientY: 300, target: { closest: () => handEl } });
    root._emit('pointerup', { clientX: 150, clientY: 140, target: { closest: () => handEl } });
    assert.deepEqual(sent.at(-1).intent, {
      op: 'MOVE_CARD',
      card_id: 'b1',
      to: { kind: 'zone', zone: { owner: 'P1', role: 'hand', idx: null } },
      position: null,
      value: 1, // between h1 and h3
    });
  });

  it('removes the incoming-card placeholder when the drag is abandoned', () => {
    root.dataset.viewerSeat = 'P1';
    const handEl = fakeHand('P1', [handCardEl('h1', 0), handCardEl('h3', 200)]);
    root._emit('pointerdown', onCard(fakeCard('b1', { onBattlefield: true, side: 'FATE' })));
    root._emit('pointermove', { clientX: 150, clientY: 300, target: { closest: () => handEl } });
    assert.ok(handEl.children.some((c) => c.className?.includes('hand-gap')), 'the gap opened');
    root._emit('pointercancel', {});
    assert.ok(!handEl.children.some((c) => c.className?.includes('hand-gap')), 'and is gone on cancel');
  });

  it('glows the viewer hand as a drop target while a card is over it, clearing on release', () => {
    root.dataset.viewerSeat = 'P1';
    const hand = fakeHand('P1');
    root._emit('pointerdown', onCard(fakeCard('c1', { onBattlefield: true, side: 'FATE' })));
    root._emit('pointermove', overHand(hand));
    assert.ok(hand.classList.has('drop-active'), 'the hand glows while hovered');
    root._emit('pointermove', { clientX: 90, clientY: 90 }); // back over the board
    assert.ok(!hand.classList.has('drop-active'), 'and stops glowing once the card leaves it');
    root._emit('pointermove', overHand(hand));
    root._emit('pointerup', onZone({ zone: 'hand', owner: 'P1' }));
    assert.ok(!hand.classList.has('drop-active'), 'and on release');
  });

  it('never glows the opponent hand, which is not a valid drop target', () => {
    root.dataset.viewerSeat = 'P1';
    const hand = fakeHand('P2');
    root._emit('pointerdown', onCard(fakeCard('c1', { onBattlefield: true, side: 'FATE' })));
    root._emit('pointermove', overHand(hand));
    assert.ok(!hand.classList.has('drop-active'));
  });

  it('reorders a hand card within the hand instead of re-moving it to the zone it occupies', () => {
    root.dataset.viewerSeat = 'P1';
    const handEl = fakeHand('P1', [handCardEl('h1', 0), handCardEl('h2', 100), handCardEl('h3', 200)]);
    const dragged = fakeCard('h2', { onBattlefield: false, side: 'FATE', inHand: true });
    root._emit('pointerdown', onCard(dragged));
    root._emit('pointermove', { clientX: 250, clientY: 300 });
    root._emit('pointerup', { clientX: 250, clientY: 140, target: { closest: () => handEl } });
    // Dropped past h3 with h2 itself skipped → slot 2 (the end).
    assert.deepEqual(sent.at(-1).intent, { op: 'REORDER_HAND', card_id: 'h2', value: 2 });
  });

  it('slides the hidden source to the landing slot, opening a gap while re-arranging', () => {
    root.dataset.viewerSeat = 'P1';
    const dragged = fakeCard('h2', { onBattlefield: false, side: 'FATE', inHand: true });
    const handEl = fakeHand('P1', [handCardEl('h1', 0), dragged, handCardEl('h3', 200)]);
    dragged.parentNode = handEl;
    root._emit('pointerdown', onCard(dragged));
    root._emit('pointermove', { clientX: 250, clientY: 300, target: { closest: () => handEl } });
    assert.equal(handEl.children.indexOf(dragged), 2, 'the gap follows the pointer to the end slot');
  });

  it('returns a re-arranged hand card to its home slot if the drag is abandoned', () => {
    root.dataset.viewerSeat = 'P1';
    const dragged = fakeCard('h2', { onBattlefield: false, side: 'FATE', inHand: true });
    const handEl = fakeHand('P1', [handCardEl('h1', 0), dragged, handCardEl('h3', 200)]);
    dragged.parentNode = handEl;
    root._emit('pointerdown', onCard(dragged));
    root._emit('pointermove', { clientX: 250, clientY: 300, target: { closest: () => handEl } });
    assert.equal(handEl.children.indexOf(dragged), 2, 'the gap opened at the end');
    root._emit('pointercancel', {});
    assert.equal(handEl.children.indexOf(dragged), 1, 'the source snaps back home on cancel');
  });

  it('barriers a dynasty card from the hand — no glow, stays clamped, settles on the board', () => {
    root.dataset.viewerSeat = 'P1';
    const hand = fakeHand('P1');
    const card = fakeCard('c1', { onBattlefield: true, side: 'DYNASTY' });
    root._emit('pointerdown', onCard(card));
    root._emit('pointermove', overHand(hand)); // far below the board, over the hand
    assert.ok(!hand.classList.has('drop-active'), 'a dynasty card never lights the hand');
    assert.equal(card.style.top, '85px', 'it stays clamped to the board, bumping the hand edge');
    root._emit('pointerup', onZone({ zone: 'hand', owner: 'P1' }));
    assert.equal(sent.at(-1).intent.op, 'SET_CARD_POS', 'it settles on the board, not into the hand');
  });

  it('drags a discard top card with a ghost and drops it as a MOVE_CARD', () => {
    // A discard pile's top renders as a zone-card, so it drags through the same ghost path as a hand
    // or province card.
    const discardTop = fakeCard('d1', { onBattlefield: false, img: '/images/bar.jpg' });
    root._emit('pointerdown', onCard(discardTop));
    root._emit('pointermove', { clientX: 90, clientY: 90 });
    const ghost = board.children.find((c) => c.className?.includes('dragging'));
    assert.equal(ghost.children[0]?.src, '/images/bar.jpg');
    assert.equal(discardTop.style.visibility, 'hidden');
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    assert.equal(sent.at(-1).intent.op, 'MOVE_CARD');
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

describe('initBoardInteractions — deck top, ownership, raise', () => {
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

  it('drags a deck top onto the battlefield as a MOVE_DECK_TOP with a position', () => {
    root._emit('pointerdown', onDeck({ owner: 'P1', side: 'FATE' }));
    root._emit('pointermove', { clientX: 90, clientY: 90 });
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    const move = sent.at(-1).intent;
    assert.equal(move.op, 'MOVE_DECK_TOP');
    assert.deepEqual(move.deck, { owner: 'P1', side: 'FATE' });
    assert.deepEqual(move.to, { kind: 'battlefield' });
    assert.ok(Array.isArray(move.position));
  });

  it('drags a face-down ghost that is non-interactive, so the drop hits the zone beneath', () => {
    root._emit('pointerdown', onDeck({ owner: 'P1', side: 'FATE' }));
    root._emit('pointermove', { clientX: 90, clientY: 90 });
    const ghost = board.children.find((c) => c.className?.includes('dragging'));
    assert.ok(ghost, 'a ghost appears while dragging the deck top');
    assert.equal(ghost.style.pointerEvents, 'none', 'the ghost must not intercept the drop');
  });

  it('drops a deck top onto another zone as a MOVE_DECK_TOP with no position', () => {
    root._emit('pointerdown', onDeck({ owner: 'P1', side: 'DYNASTY' }));
    root._emit('pointermove', { clientX: 90, clientY: 90 });
    root._emit('pointerup', onZone({ zone: 'discard', owner: 'P1', role: 'dynasty_discard' }));
    assert.deepEqual(sent.at(-1), {
      type: 'INTENT',
      intent: {
        op: 'MOVE_DECK_TOP',
        deck: { owner: 'P1', side: 'DYNASTY' },
        to: { kind: 'zone', zone: { owner: 'P1', role: 'dynasty_discard', idx: null } },
        position: null,
      },
    });
  });

  it('does not let a player drag the opponent deck top', () => {
    root._emit('pointerdown', onDeck({ owner: 'P2', side: 'FATE' }));
    root._emit('pointermove', { clientX: 90, clientY: 90 });
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    assert.equal(sent.length, 0);
  });

  it('does not start a drag — and so sends nothing — for an opponent card', () => {
    root._emit('pointerdown', onCard(fakeCard('c1', { onBattlefield: true, owner: 'P2' })));
    root._emit('pointermove', { clientX: 90, clientY: 90 });
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    assert.equal(sent.length, 0);
  });

  it('still moves a neutral (ownerless) card', () => {
    root._emit('pointerdown', onCard(fakeCard('tok', { onBattlefield: true, owner: '' })));
    root._emit('pointermove', { clientX: 90, clientY: 90 });
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    assert.equal(sent.at(-1).intent.op, 'SET_CARD_POS');
  });

  it('raises an owned card on a select-without-move when it is not already topmost', () => {
    const c1 = fakeCard('c1', { onBattlefield: true, owner: 'P1' });
    const c2 = fakeCard('c2', { onBattlefield: true, owner: 'P1' });
    board.querySelectorAll = (sel) => (sel === '.board-card' ? [c1, c2] : []);
    root._emit('pointerdown', onCard(c1)); // c1 is below c2 in z-order
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    assert.deepEqual(sent, [{ type: 'INTENT', intent: { op: 'RAISE', card_id: 'c1' } }]);
  });

  it('does not raise a select on the already-topmost card', () => {
    const c1 = fakeCard('c1', { onBattlefield: true, owner: 'P1' });
    const c2 = fakeCard('c2', { onBattlefield: true, owner: 'P1' });
    board.querySelectorAll = (sel) => (sel === '.board-card' ? [c1, c2] : []);
    root._emit('pointerdown', onCard(c2)); // c2 is topmost
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    assert.equal(sent.length, 0);
  });

  it('raises via SET_CARD_POS on a real drag, not a separate RAISE', () => {
    const c1 = fakeCard('c1', { onBattlefield: true, owner: 'P1' });
    const c2 = fakeCard('c2', { onBattlefield: true, owner: 'P1' });
    board.querySelectorAll = (sel) => (sel === '.board-card' ? [c1, c2] : []);
    root._emit('pointerdown', onCard(c1));
    root._emit('pointermove', { clientX: 90, clientY: 90 });
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    assert.ok(sent.every((m) => m.intent.op !== 'RAISE'), 'a drag does not emit RAISE');
    assert.equal(sent.at(-1).intent.op, 'SET_CARD_POS');
  });
});

// Position a fake battlefield card by its inline style, as renderBoard does, so the marquee and
// group-drag maths can read it back.
function placedCard(id, x, y) {
  const el = fakeCard(id, { onBattlefield: true });
  el.style.left = `${x}px`;
  el.style.top = `${y}px`;
  return el;
}

describe('initBoardInteractions — selection', () => {
  let root;
  let board;
  let sent;
  let interactions;

  beforeEach(() => {
    root = document.getElementById('boardStage');
    root.dataset.viewerSeat = 'P1';
    board = document.getElementById('battlefield');
    sent = [];
    interactions = initBoardInteractions(root, board, (message) => sent.push(message));
  });

  it('selects a battlefield card on a plain click and clears it on an empty click', () => {
    const c1 = fakeCard('c1', { onBattlefield: true });
    board.querySelectorAll = (sel) => (sel === '.board-card' ? [c1] : []);

    root._emit('pointerdown', onCard(c1));
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    assert.ok(c1.classList.contains('selected'));

    root._emit('pointerdown', offCard());
    root._emit('pointerup', offCard());
    assert.ok(!c1.classList.contains('selected'), 'an empty click clears the selection');
  });

  it('adds a second card with Ctrl-click and keeps the first', () => {
    const c1 = fakeCard('c1', { onBattlefield: true });
    const c2 = fakeCard('c2', { onBattlefield: true });
    board.querySelectorAll = (sel) => (sel === '.board-card' ? [c1, c2] : []);

    root._emit('pointerdown', onCard(c1));
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    root._emit('pointerdown', onCard(c2, { ctrlKey: true }));
    root._emit('pointerup', onZone({ zone: 'battlefield' }));

    assert.ok(c1.classList.contains('selected'));
    assert.ok(c2.classList.contains('selected'));
  });

  it('reattaches the outline to fresh elements after a re-render via markSelection', () => {
    const c1 = fakeCard('c1', { onBattlefield: true });
    board.querySelectorAll = (sel) => (sel === '.board-card' ? [c1] : []);
    root._emit('pointerdown', onCard(c1));
    root._emit('pointerup', onZone({ zone: 'battlefield' }));

    // A SNAPSHOT re-render rebuilds the card element; the id-keyed selection must survive it.
    const fresh = fakeCard('c1', { onBattlefield: true });
    board.querySelectorAll = (sel) => (sel === '.board-card' ? [fresh] : []);
    interactions.markSelection();
    assert.ok(fresh.classList.contains('selected'));
  });

  // Build a two-card selection (click c1, Ctrl-click c2) and return the elements. Per-card overrides
  // (e.g. a side) let a test exercise the mixed-selection routing. The selecting clicks emit a RAISE
  // for the owned non-topmost card, so a test that asserts on a later menu action should clear `sent`.
  const selectTwo = (opts1 = {}, opts2 = {}) => {
    const c1 = fakeCard('c1', { onBattlefield: true, owner: 'P1', ...opts1 });
    const c2 = fakeCard('c2', { onBattlefield: true, owner: 'P1', ...opts2 });
    board.querySelectorAll = (sel) => (sel === '.board-card' ? [c1, c2] : []);
    root._emit('pointerdown', onCard(c1));
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    root._emit('pointerdown', onCard(c2, { ctrlKey: true }));
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    return [c1, c2];
  };

  it('applies a context-menu flag op to the whole selection when a selected card is clicked', () => {
    const [c1] = selectTwo();
    sent.length = 0;
    root._emit('contextmenu', rightClick({ card: c1 }));
    clickMenuItem(root, 'Flip');
    assert.deepEqual(sent.at(-1).intent, { op: 'FLIP', card_ids: ['c1', 'c2'] });
  });

  it('targets only the clicked card when it is not part of the selection', () => {
    selectTwo();
    const c3 = fakeCard('c3', { onBattlefield: true, owner: 'P1' });
    root._emit('contextmenu', rightClick({ card: c3 }));
    clickMenuItem(root, 'Flip');
    assert.deepEqual(sent.at(-1).intent, { op: 'FLIP', card_ids: ['c3'] });
  });

  it('fans "Send to Hand" out over the whole selection, one MOVE_CARD per card', () => {
    root.dataset.viewerSeat = 'P1';
    const [c1] = selectTwo({ side: 'FATE' }, { side: 'FATE' });
    sent.length = 0;
    root._emit('contextmenu', rightClick({ card: c1 }));
    clickMenuItem(root, 'Send to Hand');
    assert.deepEqual(
      sent.map((m) => [m.intent.op, m.intent.card_id, m.intent.to.zone.role]),
      [
        ['MOVE_CARD', 'c1', 'hand'],
        ['MOVE_CARD', 'c2', 'hand'],
      ],
    );
  });

  it("routes a mixed-side selection to each card's own discard", () => {
    root.dataset.viewerSeat = 'P1';
    const [c1] = selectTwo({ side: 'FATE' }, { side: 'DYNASTY' });
    sent.length = 0;
    root._emit('contextmenu', rightClick({ card: c1 }));
    clickMenuItem(root, 'Send to Discard');
    assert.deepEqual(
      sent.map((m) => [m.intent.card_id, m.intent.to.zone.role]),
      [
        ['c1', 'fate_discard'],
        ['c2', 'dynasty_discard'],
      ],
    );
  });

  it('skips a sideless card when a side-routed action fans out over the selection', () => {
    root.dataset.viewerSeat = 'P1';
    const [c1] = selectTwo({ side: 'FATE' }, { side: '' }); // c2 is a sideless token
    sent.length = 0;
    root._emit('contextmenu', rightClick({ card: c1 }));
    clickMenuItem(root, 'Send to Discard');
    assert.deepEqual(
      sent.map((m) => [m.intent.card_id, m.intent.to.zone.role]),
      [['c1', 'fate_discard']],
    );
  });

  it('removes every selected card from a group "Remove"', () => {
    const [c1] = selectTwo({ token: true }, { token: true });
    sent.length = 0;
    root._emit('contextmenu', rightClick({ card: c1 }));
    clickMenuItem(root, 'Remove');
    assert.deepEqual(sent, [
      { type: 'REMOVE', remove: { id: 'c1' } },
      { type: 'REMOVE', remove: { id: 'c2' } },
    ]);
  });
});

describe('initBoardInteractions — marquee and group drag', () => {
  let root;
  let board;
  let sent;

  beforeEach(() => {
    root = document.getElementById('boardStage');
    board = document.getElementById('battlefield');
    sent = [];
    initBoardInteractions(root, board, (message) => sent.push(message));
  });

  it('selects every card a marquee covers and skips those outside it', () => {
    const inside = placedCard('in', 50, 50);
    const outside = placedCard('out', 400, 400);
    board.querySelectorAll = (sel) => (sel === '.board-card' ? [inside, outside] : []);

    // The fake battlefield is 200×200; this marquee from (0,0) to (150,150) covers only `inside`.
    root._emit('pointerdown', offCard({ clientX: 0, clientY: 0 }));
    root._emit('pointermove', { clientX: 150, clientY: 150, target: { closest: () => null } });
    root._emit('pointerup', offCard({ clientX: 150, clientY: 150 }));

    assert.ok(inside.classList.contains('selected'));
    assert.ok(!outside.classList.contains('selected'));
  });

  it('moves the whole selection together in a single batched intent', () => {
    const c1 = placedCard('c1', 0, 0);
    const c2 = placedCard('c2', 50, 0);
    board.querySelectorAll = (sel) => (sel === '.board-card' ? [c1, c2] : []);

    root._emit('pointerdown', onCard(c1));
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    root._emit('pointerdown', onCard(c2, { ctrlKey: true }));
    root._emit('pointerup', onZone({ zone: 'battlefield' }));

    sent.length = 0;
    const realNow = Date.now;
    Date.now = () => 1000;
    try {
      root._emit('pointerdown', onCard(c1)); // c1 is part of the multi-selection → group drag
      root._emit('pointermove', { clientX: 60, clientY: 50 });
    } finally {
      Date.now = realNow;
    }

    // One message regardless of group size: per-member messages would multiply the wire rate and
    // trip the server's connection throttle.
    assert.equal(sent.length, 1, 'a group move is one message, not one per card');
    assert.equal(sent[0].intent.op, 'SET_CARD_POSITIONS');
    assert.deepEqual(
      sent[0].intent.moves.map((m) => m.id).sort(),
      ['c1', 'c2'],
    );
  });
});

describe('initBoardInteractions — double-click shortcuts', () => {
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

  // A double-click event whose target resolves to a deck pile or a card, as the handler reads them.
  const dblClick = ({ card = null, deck = null } = {}) => ({
    target: {
      closest: (sel) => {
        if (sel === '[data-zone="deck"]') return deck;
        if (sel === '[data-card-id]') return card;
        return null;
      },
    },
  });
  const deckTile = (owner, side) => ({ dataset: { zone: 'deck', owner, side } });

  it('draws the top card when you double-click your own deck', () => {
    root._emit('dblclick', dblClick({ deck: deckTile('P1', 'FATE') }));
    assert.deepEqual(sent.at(-1).intent, { op: 'DRAW', deck: { owner: 'P1', side: 'FATE' } });
  });

  it("ignores a double-click on the opponent's deck", () => {
    root._emit('dblclick', dblClick({ deck: deckTile('P2', 'FATE') }));
    assert.equal(sent.length, 0);
  });

  it('flips a face-down card you own up, in a province too', () => {
    root._emit('dblclick', dblClick({ card: fakeCard('c1', { owner: 'P1', faceUp: false }) }));
    assert.deepEqual(sent.at(-1).intent, { op: 'FLIP', card_ids: ['c1'] });

    const province = { dataset: { zone: 'province', owner: 'P1', idx: '0' } };
    root._emit('dblclick', dblClick({ card: fakeCard('c2', { owner: 'P1', faceUp: false, province }) }));
    assert.deepEqual(sent.at(-1).intent, { op: 'FLIP', card_ids: ['c2'] });
  });

  it('flips a face-down double-faced card to its other face (FLIP_FACE)', () => {
    const card = fakeCard('c1', { owner: 'P1', faceUp: false, doubleFaced: true });
    root._emit('dblclick', dblClick({ card }));
    assert.deepEqual(sent.at(-1).intent, { op: 'FLIP_FACE', card_ids: ['c1'] });
  });

  it('bows a face-up card you own, and unbows a bowed one', () => {
    root._emit('dblclick', dblClick({ card: fakeCard('c1', { owner: 'P1', faceUp: true }) }));
    assert.deepEqual(sent.at(-1).intent, { op: 'BOW', card_ids: ['c1'] });

    root._emit('dblclick', dblClick({ card: fakeCard('c2', { owner: 'P1', faceUp: true, bowed: true }) }));
    assert.deepEqual(sent.at(-1).intent, { op: 'UNBOW', card_ids: ['c2'] });
  });

  it('leaves a face-up card in a province alone (bowing there is meaningless)', () => {
    const province = { dataset: { zone: 'province', owner: 'P1', idx: '0' } };
    root._emit('dblclick', dblClick({ card: fakeCard('c1', { owner: 'P1', faceUp: true, province }) }));
    assert.equal(sent.length, 0);
  });

  it('plays a hand card into the viewer half, clear of the provinces, on double-click', () => {
    const card = fakeCard('h1', { owner: 'P1', onBattlefield: false, inHand: true });
    root._emit('dblclick', dblClick({ card }));
    const move = sent.at(-1).intent;
    assert.equal(move.op, 'MOVE_CARD');
    assert.deepEqual(move.to, { kind: 'battlefield' });
    // 200×200 board: centred horizontally, set above the bottom-edge provinces.
    assert.deepEqual(move.position, [60, 63]);
  });

  it('fans successive hand plays so they do not land in a perfect stack', () => {
    const play = (cardId) =>
      root._emit('dblclick', dblClick({ card: fakeCard(cardId, { owner: 'P1', inHand: true }) }));
    play('h1');
    play('h2');
    play('h3');
    const xs = sent.map((m) => m.intent.position[0]);
    assert.deepEqual(xs, [60, 80, 100], 'each play steps one fan slot right');
  });

  it('keeps fanned plays on the board no matter how many are played', () => {
    const play = (n) =>
      root._emit('dblclick', dblClick({ card: fakeCard(`h${n}`, { owner: 'P1', inHand: true }) }));
    for (let n = 0; n < 15; n++) play(n);
    const maxX = 200 - 81; // board width − card width (CARD_W) on the 200×200 fixture
    assert.ok(
      sent.every((m) => m.intent.position[0] >= 0 && m.intent.position[0] <= maxX),
      'the fan never runs off the board',
    );
  });

  it("ignores a double-click on an opponent's card", () => {
    root._emit('dblclick', dblClick({ card: fakeCard('c1', { owner: 'P2', faceUp: true }) }));
    assert.equal(sent.length, 0);
  });

  it('acts on a neutral (ownerless) card, bowing it like one of your own', () => {
    root._emit('dblclick', dblClick({ card: fakeCard('c1', { owner: '', faceUp: true }) }));
    assert.deepEqual(sent.at(-1).intent, { op: 'BOW', card_ids: ['c1'] });
  });
});

describe('initBoardInteractions — keyboard shortcuts', () => {
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

  // Hover an element (sets the hotkey target), then press a key as a non-typing keydown on the
  // document. Returns the event so callers can assert its default was (or wasn't) consumed.
  const press = (key, hoverTarget, keyTarget = { tagName: 'DIV' }) => {
    root._emit('pointermove', { target: hoverTarget });
    const event = { key, target: keyTarget, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
    document._emit('keydown', event);
    return event;
  };
  // A pointer target whose `closest` resolves to a card (with its dataset) but not a deck.
  const overCard = (opts) => {
    const card = fakeCard('c1', opts);
    return { closest: (sel) => (sel === '[data-card-id]' ? card : null) };
  };
  const overDeck = (owner, side) => ({
    closest: (sel) => (sel === '[data-zone="deck"]' ? { dataset: { owner, side } } : null),
  });

  it('F flips, B bows, I inverts the hovered card you own', () => {
    press('f', overCard({ owner: 'P1', faceUp: false }));
    assert.deepEqual(sent.at(-1).intent, { op: 'FLIP', card_ids: ['c1'] });
    press('b', overCard({ owner: 'P1', faceUp: true }));
    assert.deepEqual(sent.at(-1).intent, { op: 'BOW', card_ids: ['c1'] });
    press('i', overCard({ owner: 'P1', faceUp: true }));
    assert.deepEqual(sent.at(-1).intent, { op: 'INVERT', card_ids: ['c1'] });
  });

  it('B unbows a bowed card and is case-insensitive', () => {
    press('B', overCard({ owner: 'P1', faceUp: true, bowed: true }));
    assert.deepEqual(sent.at(-1).intent, { op: 'UNBOW', card_ids: ['c1'] });
  });

  it('F flips a double-faced card by its face, not as a hidden card', () => {
    press('f', overCard({ owner: 'P1', faceUp: false, doubleFaced: true }));
    assert.deepEqual(sent.at(-1).intent, { op: 'FLIP_FACE', card_ids: ['c1'] });
  });

  it('ignores a card hotkey on a card sitting on a deck', () => {
    const card = fakeCard('c1', { owner: 'P1', faceUp: true });
    card.closest = (sel) => (sel === '[data-zone="deck"]' ? { dataset: {} } : null);
    press('f', { closest: (sel) => (sel === '[data-card-id]' ? card : null) });
    assert.equal(sent.length, 0);
  });

  it('lets modifier combos through so browser shortcuts still work', () => {
    root._emit('pointermove', { target: overCard({ owner: 'P1', faceUp: false }) });
    const event = { key: 'f', target: { tagName: 'DIV' }, ctrlKey: true, defaultPrevented: false, preventDefault() { this.defaultPrevented = true; } };
    document._emit('keydown', event);
    assert.equal(sent.length, 0);
    assert.equal(event.defaultPrevented, false);
  });

  it('D draws from the hovered deck you own', () => {
    press('d', overDeck('P1', 'FATE'));
    assert.deepEqual(sent.at(-1).intent, { op: 'DRAW', deck: { owner: 'P1', side: 'FATE' } });
  });

  it('S opens the search chooser for the hovered deck', () => {
    press('s', overDeck('P1', 'DYNASTY'));
    const overlay = document
      .querySelector('.room')
      .children.find((c) => c.className === 'deck-dialog-overlay');
    assert.ok(overlay, 'the search chooser opened');
  });

  it('consumes the keystroke so S does not leak into the chooser input', () => {
    const event = press('s', overDeck('P1', 'DYNASTY'));
    assert.equal(event.defaultPrevented, true);
  });

  it('leaves the keystroke alone when no hotkey applies', () => {
    const event = press('d', overDeck('P2', 'FATE'));
    assert.equal(event.defaultPrevented, false);
  });

  it('ignores a card hotkey on an opponent card', () => {
    press('b', overCard({ owner: 'P2', faceUp: true }));
    assert.equal(sent.length, 0);
  });

  it('ignores a deck hotkey on the opponent deck', () => {
    press('d', overDeck('P2', 'FATE'));
    assert.equal(sent.length, 0);
  });

  it('stays out of the way while typing in an input', () => {
    press('b', overCard({ owner: 'P1', faceUp: true }), { tagName: 'INPUT' });
    assert.equal(sent.length, 0);
  });

  it('does nothing when the pointer is not over a card or deck', () => {
    press('f', { closest: () => null });
    assert.equal(sent.length, 0);
  });

  it('skips bowing a face-up card in a province', () => {
    const province = { dataset: { zone: 'province', owner: 'P1', idx: '0' } };
    const card = fakeCard('c1', { owner: 'P1', faceUp: true, province });
    press('b', { closest: (sel) => (sel === '[data-card-id]' ? card : null) });
    assert.equal(sent.length, 0);
  });

  it('skips bowing a card in a discard pile', () => {
    const card = fakeCard('c1', { owner: 'P1', faceUp: true, inDiscard: true });
    press('b', { closest: (sel) => (sel === '[data-card-id]' ? card : null) });
    assert.equal(sent.length, 0);
  });

  it('skips flipping a card in a discard pile but still inverts it', () => {
    const card = fakeCard('c1', { owner: 'P1', faceUp: true, inDiscard: true });
    const hover = { closest: (sel) => (sel === '[data-card-id]' ? card : null) };
    press('f', hover);
    assert.equal(sent.length, 0);
    press('i', hover);
    assert.deepEqual(sent.at(-1).intent, { op: 'INVERT', card_ids: ['c1'] });
  });

  it('applies a card hotkey to the whole selection when the hovered card is selected', () => {
    const c1 = fakeCard('c1', { onBattlefield: true, owner: 'P1', faceUp: true });
    const c2 = fakeCard('c2', { onBattlefield: true, owner: 'P1', faceUp: true });
    board.querySelectorAll = (sel) => (sel === '.board-card' ? [c1, c2] : []);
    root._emit('pointerdown', onCard(c1));
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    root._emit('pointerdown', onCard(c2, { ctrlKey: true }));
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    sent.length = 0;

    press('b', { closest: (sel) => (sel === '[data-card-id]' ? c1 : null) });
    assert.deepEqual(sent.at(-1).intent, { op: 'BOW', card_ids: ['c1', 'c2'] });
  });

  it('forgets its target once the pointer leaves the board', () => {
    root._emit('pointermove', { target: overCard({ owner: 'P1', faceUp: true }) });
    root._emit('pointerleave', {});
    document._emit('keydown', { key: 'b', target: { tagName: 'DIV' } });
    assert.equal(sent.length, 0);
  });
});

describe('initBoardInteractions — card view', () => {
  beforeEach(() => {
    const root = document.getElementById('boardStage');
    const board = document.getElementById('battlefield');
    initBoardInteractions(root, board, () => {});
  });

  const overCard = (opts) => {
    const cardEl = fakeCard('c1', opts);
    return { closest: (sel) => (sel === '[data-card-id]' ? cardEl : null) };
  };
  // Hover a card, then press V to open its preview.
  const viewByHotkey = (opts) => {
    const root = document.getElementById('boardStage');
    root._emit('pointermove', { target: overCard(opts) });
    document._emit('keydown', { key: 'v', target: { tagName: 'DIV' }, preventDefault() {} });
  };
  const previews = () =>
    document.querySelector('.room').children.filter((c) => c.className === 'card-view');

  it('V opens a card-sized preview of the hovered card face', () => {
    viewByHotkey({ img: '/images/foo.jpg' });
    const [preview] = previews();
    assert.ok(preview);
    assert.equal(preview.src, '/images/foo.jpg');
  });

  it('opens the same preview from the View menu item', () => {
    const card = fakeCard('c1', { owner: 'P1', img: '/images/foo.jpg' });
    const root = document.getElementById('boardStage');
    root.dataset.viewerSeat = 'P1';
    root._emit('contextmenu', rightClick({ card }));
    clickMenuItem(root, 'View');
    const [preview] = previews();
    assert.ok(preview);
    assert.equal(preview.src, '/images/foo.jpg');
  });

  it('does not open a preview for a card with no rendered face', () => {
    viewByHotkey({});
    assert.equal(previews().length, 0);
  });

  it('dismisses smoothly on the next keypress: fades, then removes on transition end', () => {
    viewByHotkey({ img: '/images/foo.jpg' });
    const [preview] = previews();
    document._emit('keydown', { key: 'x', target: { tagName: 'DIV' }, preventDefault() {} });
    assert.ok(preview.classList.contains('closing'));
    assert.equal(previews().length, 1, 'stays mounted while fading out');
    preview._emit('transitionend');
    assert.equal(previews().length, 0);
  });

  it('dismisses on the next pointer action', () => {
    viewByHotkey({ img: '/images/foo.jpg' });
    const [preview] = previews();
    document._emit('pointerdown', {});
    assert.ok(preview.classList.contains('closing'));
  });

  it('re-pressing V over another card supersedes the previous preview', () => {
    viewByHotkey({ img: '/images/a.jpg' });
    viewByHotkey({ img: '/images/b.jpg' });
    const live = previews().find((c) => !c.classList.contains('closing'));
    assert.ok(live);
    assert.equal(live.src, '/images/b.jpg');
    assert.ok(previews().find((c) => c.src === '/images/a.jpg').classList.contains('closing'));
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

  // The underlined accelerator letter of the open menu's item labelled `label`.
  const accelOf = (label) =>
    activeMenu(root)
      .children.find((li) => li.textContent === label)
      .children.find((c) => c.className === 'menu-key').textContent;

  const pressKey = (key) => document._emit('keydown', { key, preventDefault() {} });

  it("opens the full card menu on the viewer's own face-up card and suppresses the native menu", () => {
    const event = rightClick({ card: fakeCard('c1', { side: 'FATE', owner: 'P1' }) });
    root._emit('contextmenu', event);

    assert.equal(event.defaultPrevented, true);
    // A face-up own card on the board: the opponent already sees it, so no "Show opponent" and no
    // Peek; no "Remove" either (only tokens remove).
    assert.deepEqual(menuLabels(root), [
      'View',
      'Flip',
      'Bow',
      'Invert',
      'Add note…',
      'Duplicate',
      'Give control',
      'Send to Hand',
      'Send to Discard',
      'Send to Deck (top)',
      'Send to Deck (bottom)',
    ]);
  });

  it('duplicates a face-up battlefield card as a token dropped down-right of the original', () => {
    const cardEl = fakeCard('c1', {
      owner: 'P1',
      side: 'DYNASTY',
      name: 'Hida Kisada',
      img: 'sets/hk.jpg',
      x: 10,
      y: 20,
    });
    root._emit('contextmenu', rightClick({ card: cardEl }));
    assert.equal(accelOf('Duplicate'), 'p');
    clickMenuItem(root, 'Duplicate');
    assert.deepEqual(sent.at(-1), {
      type: 'SPAWN',
      spawn: { name: 'Hida Kisada', img: 'sets/hk.jpg', side: 'DYNASTY', x: 28, y: 38 },
    });
  });

  it('gives control of an own card to the opponent via the menu and accelerator g', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { owner: 'P1' }) }));
    assert.equal(accelOf('Give control'), 'G');
    pressKey('g');
    assert.deepEqual(sent.at(-1).intent, { op: 'GIVE_CONTROL', card_id: 'c1' });
  });

  it('omits Give control on the opponent\'s card', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { owner: 'P2' }) }));
    assert.ok(!menuLabels(root).includes('Give control'));
  });

  it('omits Give control on a public (owner-less) card', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { owner: '' }) }));
    assert.ok(!menuLabels(root).includes('Give control'));
  });

  it('omits Give control on an own pregame card (stronghold/sensei/wind)', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { owner: 'P1', pregame: true }) }));
    const labels = menuLabels(root);
    assert.ok(!labels.includes('Give control'));
    assert.ok(labels.includes('Duplicate'), 'other face-up actions still appear');
  });

  it('omits Duplicate on a face-down battlefield card', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { owner: 'P1', faceUp: false }) }));
    assert.ok(!menuLabels(root).includes('Duplicate'));
  });

  it("labels the note action 'Add note' with no note and 'Edit note' once one exists", () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { owner: 'P1' }) }));
    assert.ok(menuLabels(root).includes('Add note…'));
    root._emit('contextmenu', rightClick({ card: fakeCard('c2', { owner: 'P1', note: 'dead' }) }));
    assert.ok(menuLabels(root).includes('Edit note…'));
  });

  it('omits the note action on a face-down battlefield card', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { owner: 'P1', faceUp: false }) }));
    assert.ok(!menuLabels(root).some((label) => label.startsWith('Add note') || label.startsWith('Edit note')));
  });

  it('opens a note box from the menu and saves the typed text as a SET_NOTE', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { owner: 'P1' }) }));
    clickMenuItem(root, 'Add note…');
    const overlay = document
      .querySelector('.room')
      .children.find((child) => child.className === 'deck-dialog-overlay');
    const modal = overlay.children[0]; // [header, textarea, footer]
    modal.children[1].value = 'dead';
    modal.children[2].children[0]._emit('click', {}); // footer > Save
    assert.deepEqual(sent.at(-1).intent, { op: 'SET_NOTE', card_id: 'c1', text: 'dead' });
  });

  it('offers "Stop showing" on an already-shown own card', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { owner: 'P1', shown: true }) }));
    const labels = menuLabels(root);
    assert.ok(labels.includes('Stop showing') && !labels.includes('Show opponent'));
    clickMenuItem(root, 'Stop showing');
    assert.deepEqual(sent[0].intent, { op: 'UNSHOW', card_id: 'c1' });
  });

  it('opens a hand card menu mounted on the stage, not the clipped battlefield', () => {
    const event = rightClick({
      zone: { zone: 'hand', owner: 'P1' },
      card: fakeCard('h1', { side: 'FATE', owner: 'P1', onBattlefield: false, inHand: true }),
    });
    root._emit('contextmenu', event);

    assert.ok(activeMenu(root), 'menu mounts on the board stage');
    assert.equal(activeMenu(board), undefined, 'menu is not trapped in the battlefield');
  });

  it('trims a hand card menu: no in-play manipulation, no Send to Hand, but reveal and disposal', () => {
    const card = fakeCard('h1', { side: 'FATE', owner: 'P1', onBattlefield: false, inHand: true });
    root._emit('contextmenu', rightClick({ zone: { zone: 'hand', owner: 'P1' }, card }));
    assert.deepEqual(menuLabels(root), [
      'View', // available on every card
      'Show opponent', // a hand card is hidden from the opponent, so reveal is offered
      'Send to Discard',
      'Send to Deck (top)',
      'Send to Deck (bottom)',
    ]);
  });

  it('offers Show opponent and Peek on an own face-down card and omits the bow toggle in a province', () => {
    const province = { dataset: { zone: 'province', owner: 'P1', idx: '0' } };
    const card = fakeCard('c1', { side: 'DYNASTY', owner: 'P1', faceUp: false, province });
    // Right-clicking the province card resolves both the card and its province ancestor.
    root._emit('contextmenu', rightClick({ zone: province.dataset, card }));

    const labels = menuLabels(root);
    // Own card: it can be shown to the opponent; face-down to the viewer, it can also be peeked.
    assert.ok(labels.includes('Show opponent') && !labels.includes('Stop showing'));
    assert.ok(labels.includes('Peek') && !labels.includes('Stop peeking'), 'face-down offers Peek');
    assert.ok(!labels.includes('Bow') && !labels.includes('Unbow'), 'no bow toggle in a province');
    // The province lifecycle ops are appended after the card menu.
    assert.deepEqual(labels.slice(-3), ['Fill', 'Discard', 'Destroy']);
  });

  it('peeks an opponent card cross-owner: no Show, but Peek is offered and sends one id', () => {
    // A hidden opponent card: the viewer does not own it, so no show, but anyone may peek it.
    const card = fakeCard('c1', { side: 'DYNASTY', owner: 'P2', hidden: true });
    root._emit('contextmenu', rightClick({ card }));
    const labels = menuLabels(root);
    assert.ok(!labels.includes('Show opponent') && !labels.includes('Stop showing'));
    assert.ok(labels.includes('Peek'));
    clickMenuItem(root, 'Peek');
    assert.deepEqual(sent[0].intent, { op: 'PEEK', card_id: 'c1' });
  });

  it('offers "Stop peeking" on a card the viewer is peeking, sending UNPEEK', () => {
    const card = fakeCard('c1', { side: 'DYNASTY', owner: 'P2', faceUp: false, peeked: true });
    root._emit('contextmenu', rightClick({ card }));
    const labels = menuLabels(root);
    assert.ok(labels.includes('Stop peeking') && !labels.includes('Peek'));
    clickMenuItem(root, 'Stop peeking');
    assert.deepEqual(sent[0].intent, { op: 'UNPEEK', card_id: 'c1' });
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

  it('omits "Send to Hand" on a dynasty card, which never lives in a hand', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { side: 'DYNASTY', owner: 'P1' }) }));
    const labels = menuLabels(root);
    assert.ok(!labels.includes('Send to Hand'), 'dynasty cards do not go to hand');
    assert.ok(labels.includes('Send to Discard'), 'but they can still be discarded');
  });

  it('omits "Send to Discard" on a card already in a discard pile', () => {
    const discard = { dataset: { zone: 'discard', owner: 'P1', role: 'fate_discard' } };
    const card = fakeCard('c1', { side: 'FATE', owner: 'P1', inDiscard: true });
    root._emit('contextmenu', rightClick({ zone: discard.dataset, card }));
    const labels = menuLabels(root);
    assert.ok(!labels.includes('Send to Discard'), 'it is already in the discard');
    assert.ok(labels.includes('Send to Deck (top)'), 'but it can still go back to the deck');
  });

  it('offers only invert (no flip or bow) on a card in a discard pile', () => {
    // A discard is always public and squared up, so flip and bow are gone; invert stays to mark a
    // dishonourable death.
    const discard = { dataset: { zone: 'discard', owner: 'P1', role: 'fate_discard' } };
    const card = fakeCard('c1', { side: 'FATE', owner: 'P1', inDiscard: true, bowed: true });
    root._emit('contextmenu', rightClick({ zone: discard.dataset, card }));
    const labels = menuLabels(root);
    assert.ok(!labels.includes('Flip'), 'no flip in a public discard');
    assert.ok(!labels.includes('Bow') && !labels.includes('Unbow'), 'no bow toggle in a discard');
    assert.ok(labels.includes('Invert'), 'invert still marks a dishonourable death');
  });

  it('omits the Send-to group, show, and peek on a visible opponent (non-token) card', () => {
    // A face-up opponent card: not owned (no show), already visible (no peek), not a token (no remove).
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { side: 'FATE', owner: 'P2' }) }));
    const labels = menuLabels(root);
    // Note and Duplicate work on any face-up battlefield card, owned or not.
    assert.deepEqual(labels, ['View', 'Flip', 'Bow', 'Invert', 'Add note…', 'Duplicate']);
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
    assert.deepEqual(menuLabels(root), [
      'Draw',
      'Shuffle',
      'Flip Top',
      'Search…',
      'Create Province',
    ]);
  });

  it('keeps Draw and Search on D and S, matching the bare deck hover hotkeys', () => {
    root._emit('contextmenu', rightClick({ zone: { zone: 'deck', owner: 'P1', side: 'FATE' } }));
    assert.equal(accelOf('Draw'), 'D');
    assert.equal(accelOf('Search…'), 'S');
    assert.equal(accelOf('Shuffle'), 'h', 'Shuffle yields S to Search and takes its second letter');
  });

  // The Search chooser mounts in `.room`, not the board stage; its modal is overlay > .deck-scope >
  // [header, row(input, "Search top N"), "Whole deck"].
  const searchScope = () =>
    document.querySelector('.room').children.find((c) => c.className === 'deck-dialog-overlay');

  it('opens the Search chooser, whose "Whole deck" requests the entire deck', () => {
    root._emit('contextmenu', rightClick({ zone: { zone: 'deck', owner: 'P1', side: 'FATE' } }));
    clickMenuItem(root, 'Search…');
    const overlay = searchScope();
    assert.ok(overlay, 'the Search item opens a chooser instead of sending immediately');
    overlay.children[0].children[2]._emit('click', {}); // "Whole deck"
    assert.deepEqual(sent[0], {
      type: 'INTENT',
      intent: { op: 'SEARCH_DECK', deck: { owner: 'P1', side: 'FATE' }, value: null },
    });
  });

  it('requests the top N from the Search chooser on Enter', () => {
    root._emit('contextmenu', rightClick({ zone: { zone: 'deck', owner: 'P1', side: 'FATE' } }));
    clickMenuItem(root, 'Search…');
    const input = searchScope().children[0].children[1].children[0];
    input.value = '5';
    input._emit('keydown', { key: 'Enter' });
    assert.deepEqual(sent[0], {
      type: 'INTENT',
      intent: { op: 'SEARCH_DECK', deck: { owner: 'P1', side: 'FATE' }, value: 5 },
    });
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

  it('sends a REMOVE message and closes the menu on a token item click', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { owner: 'P1', token: true }) }));
    clickMenuItem(root, 'Remove');

    assert.deepEqual(sent, [{ type: 'REMOVE', remove: { id: 'c1' } }]);
    assert.equal(activeMenu(root), undefined, 'menu is removed after a selection');
  });

  it('offers Remove only on a token, never on a real card', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('real', { owner: 'P1' }) }));
    assert.ok(!menuLabels(root).includes('Remove'), 'a real card cannot be removed');
    root._emit('contextmenu', rightClick({ card: fakeCard('tok', { owner: 'P1', token: true }) }));
    assert.ok(menuLabels(root).includes('Remove'), 'a token can be removed');
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

  it('fires a menu item by its underlined accelerator and closes the menu', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { owner: 'P1' }) }));
    pressKey('f');
    assert.deepEqual(sent[0].intent, { op: 'FLIP', card_ids: ['c1'] });
    assert.equal(activeMenu(root), undefined, 'the menu closes once an accelerator fires');
  });

  it('reaches a destructive action by accelerator, running its onClick', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { side: 'FATE', owner: 'P1' }) }));
    pressKey('t'); // Send to Deck (top), an onClick item rather than a plain message
    assert.equal(sent[0].intent.op, 'MOVE_CARD');
    assert.deepEqual(sent[0].intent.to, { kind: 'deck', deck: { owner: 'P1', side: 'FATE' } });
  });

  it('lets a modifier combo through, never firing a menu accelerator', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { owner: 'P1' }) }));
    document._emit('keydown', { key: 'f', ctrlKey: true, preventDefault() {} });
    assert.equal(sent.length, 0);
    assert.ok(activeMenu(root), 'the menu stays open');
  });

  it('underlines the existing hover-hotkey letters and falls back when a letter is taken', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { side: 'FATE', owner: 'P1' }) }));
    assert.equal(accelOf('Flip'), 'F', 'F coincides with the bare flip hotkey');
    assert.equal(accelOf('Send to Deck (top)'), 't');
    assert.equal(accelOf('Send to Deck (bottom)'), 'o', "bottom's first letter B is taken by Bow");
  });

  it('dismisses the menu on Escape without acting', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { owner: 'P1' }) }));
    pressKey('Escape');
    assert.equal(activeMenu(root), undefined);
    assert.equal(sent.length, 0);
  });

  it('keeps every accelerator unique across a province card combined menu', () => {
    const province = { dataset: { zone: 'province', owner: 'P1', idx: '0' } };
    const card = fakeCard('c1', { side: 'DYNASTY', owner: 'P1', faceUp: false, province });
    root._emit('contextmenu', rightClick({ zone: province.dataset, card }));
    const keys = activeMenu(root)
      .children.filter((li) => li.className !== 'menu-sep')
      .map((li) => li.children.find((c) => c.className === 'menu-key')?.textContent?.toLowerCase());
    assert.ok(keys.every(Boolean), 'every item has an accelerator');
    assert.equal(new Set(keys).size, keys.length, 'no two items share one');
  });

  it('suppresses hover hotkeys while a menu is open, so a key fires only the menu item', () => {
    const card = fakeCard('c1', { owner: 'P1', faceUp: false });
    root._emit('pointermove', { target: { closest: (s) => (s === '[data-card-id]' ? card : null) } });
    root._emit('contextmenu', rightClick({ card }));
    sent.length = 0;
    pressKey('f'); // both the hover hotkey and the menu accelerator are F; only the menu may act
    assert.equal(sent.length, 1, 'one flip, from the menu accelerator, not also the hover hotkey');
  });

  it('offers Unbow all on the empty battlefield, on the W accelerator', () => {
    root._emit('contextmenu', rightClick({ zone: { zone: 'battlefield' } }));
    assert.deepEqual(menuLabels(root), ['Unbow all']);
    assert.equal(accelOf('Unbow all'), 'w');
  });

  it('unbows only the viewer own and owner-less bowed cards, never the opponent batch', () => {
    const cards = [
      { dataset: { cardId: 'mine', bowed: '1', owner: 'P1' } },
      { dataset: { cardId: 'fresh', bowed: '', owner: 'P1' } },
      { dataset: { cardId: 'theirs', bowed: '1', owner: 'P2' } },
      { dataset: { cardId: 'token', bowed: '1', owner: '' } },
    ];
    root.querySelectorAll = (sel) => (sel === '.board-card' ? cards : []);
    root._emit('contextmenu', rightClick({ zone: { zone: 'battlefield' } }));
    clickMenuItem(root, 'Unbow all');
    assert.deepEqual(sent.at(-1).intent, { op: 'UNBOW', card_ids: ['mine', 'token'] });
  });

  it('sends nothing from Unbow all when no own card is bowed', () => {
    root.querySelectorAll = () => [{ dataset: { cardId: 'theirs', bowed: '1', owner: 'P2' } }];
    root._emit('contextmenu', rightClick({ zone: { zone: 'battlefield' } }));
    sent.length = 0;
    clickMenuItem(root, 'Unbow all');
    assert.equal(sent.length, 0);
  });
});

describe('initBoardInteractions — discard search', () => {
  let root;
  let searches;

  beforeEach(() => {
    root = document.getElementById('boardStage');
    root.dataset.viewerSeat = 'P1';
    searches = [];
    initBoardInteractions(root, document.getElementById('battlefield'), () => {}, {
      onSearchDiscard: (owner, role) => searches.push([owner, role]),
    });
  });

  const discardZone = (owner) => ({ zone: 'discard', owner, role: 'fate_discard' });

  it('offers Search on an empty discard and routes it to onSearchDiscard', () => {
    root._emit('contextmenu', rightClick({ zone: discardZone('P1') }));
    assert.deepEqual(menuLabels(root), ['Search…']);
    clickMenuItem(root, 'Search…');
    assert.deepEqual(searches, [['P1', 'fate_discard']]);
  });

  it('lets a player search the opponent discard too', () => {
    root._emit('contextmenu', rightClick({ zone: discardZone('P2') }));
    clickMenuItem(root, 'Search…');
    assert.deepEqual(searches, [['P2', 'fate_discard']]);
  });

  it('keeps the top card menu and adds Search on a non-empty discard', () => {
    const card = fakeCard('c1', { side: 'FATE', owner: 'P1', inDiscard: true });
    root._emit('contextmenu', rightClick({ zone: discardZone('P1'), card }));
    const labels = menuLabels(root);
    assert.ok(labels.includes('View'), 'the top card menu is still there');
    assert.ok(labels.includes('Search…'), 'and Search is appended');
  });
});

describe('initBoardInteractions — create token', () => {
  let root;
  let created;

  beforeEach(() => {
    root = document.getElementById('boardStage');
    root.dataset.viewerSeat = 'P1';
    created = [];
    initBoardInteractions(root, document.getElementById('battlefield'), () => {}, {
      onCreateToken: (position) => created.push(position),
    });
  });

  it('offers Create token on the empty battlefield, passing the board-local click point', () => {
    root._emit('contextmenu', rightClick({ zone: { zone: 'battlefield' } }));
    assert.ok(menuLabels(root).includes('Create token…'));
    clickMenuItem(root, 'Create token…');
    assert.deepEqual(created, [{ x: 30, y: 50 }]); // rightClick's clientX/Y, board rect at 0,0
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

describe('initPanelHonor', () => {
  let panel;
  let honorEl;
  let sent;

  // An event whose target resolves to the real rendered `.panel-honor` span, as the handler reads it.
  const onHonor = (overrides = {}) => {
    let prevented = false;
    return {
      target: { closest: (sel) => (sel === '.panel-honor' ? honorEl : null) },
      preventDefault: () => {
        prevented = true;
      },
      get defaultPrevented() {
        return prevented;
      },
      ...overrides,
    };
  };

  beforeEach(() => {
    panel = document.getElementById('selfPanel');
    renderPanel(panel, { name: 'Ada', honor: 10 }, { editable: true });
    honorEl = panel.children[1].children[1];
    sent = [];
    initPanelHonor(panel, (message) => sent.push(message));
  });

  it('adds honor on a left click', () => {
    const event = onHonor();
    panel._emit('click', event);
    assert.equal(event.defaultPrevented, true);
    assert.deepEqual(sent, [{ type: 'INTENT', intent: { op: 'SET_HONOR', delta: 1 } }]);
  });

  it('removes honor on a right click', () => {
    panel._emit('contextmenu', onHonor());
    assert.deepEqual(sent, [{ type: 'INTENT', intent: { op: 'SET_HONOR', delta: -1 } }]);
  });

  it('removes honor on a middle click', () => {
    panel._emit('auxclick', onHonor({ button: 1 }));
    assert.equal(sent.at(-1).intent.delta, -1);
  });

  it('adds honor scrolling up, removes it scrolling down', () => {
    panel._emit('wheel', onHonor({ deltaY: -3 }));
    panel._emit('wheel', onHonor({ deltaY: 3 }));
    assert.deepEqual(
      sent.map((m) => m.intent.delta),
      [1, -1],
    );
  });

  it('ignores clicks away from the honor span', () => {
    panel._emit('click', { target: { closest: () => null }, preventDefault() {} });
    assert.equal(sent.length, 0);
  });

  it('leaves a read-only opponent panel inert (no handlers wired)', () => {
    const opponent = document.getElementById('opponentPanel');
    renderPanel(opponent, { name: 'Kenji', honor: 8 }, { editable: false });
    let fired = false;
    opponent._emit('click', { target: { closest: () => true }, preventDefault: () => (fired = true) });
    assert.equal(fired, false);
    assert.equal(sent.length, 0);
  });
});
