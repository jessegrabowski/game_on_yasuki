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
  layoutAttachments,
  ATTACH_STACK_OFFSET,
  patchCard,
  canonicalToView,
  viewToCanonical,
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

  it('reuses a card element across renders instead of rebuilding it', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ id: 'a', x: 10 })], '/images');
    const first = board.children[0];
    renderBoard(board, [card({ id: 'a', x: 99, bowed: true })], '/images');
    assert.equal(board.children[0], first, 'same element instance reused');
    assert.equal(first.style.left, '99px', 'patched in place');
    assert.ok(first.classList.contains('bowed'));
  });

  it('keeps each card element when only the order changes', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ id: 'a' }), card({ id: 'b' }), card({ id: 'c' })], '/images');
    const elA = board.children[0];
    const elC = board.children[2];
    renderBoard(board, [card({ id: 'c' }), card({ id: 'a' }), card({ id: 'b' })], '/images');
    assert.deepEqual(
      board.children.map((el) => el.dataset.cardId),
      ['c', 'a', 'b'],
    );
    assert.equal(board.children[0], elC, 'the moved card keeps its element');
    assert.equal(board.children[1], elA, 'reused, not rebuilt');
  });

  it('drops a departed card and adds a new one', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ id: 'a' }), card({ id: 'b' })], '/images');
    renderBoard(board, [card({ id: 'a' }), card({ id: 'd' })], '/images');
    assert.deepEqual(
      board.children.map((el) => el.dataset.cardId),
      ['a', 'd'],
    );
  });

  it('reuses the element but strips the front identity when a card becomes a hidden stub', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ id: 'a' })], '/images');
    const el = board.children[0];
    const front = el.children[0]?.src;
    assert.equal(el.dataset.name, 'Hida Kisada');
    renderBoard(board, [{ id: 'a', side: 'DYNASTY', hidden: true, x: 10, y: 20 }], '/images');
    assert.equal(board.children[0], el, 'same element reused');
    assert.ok(el.classList.contains('face-down'));
    assert.equal(el.dataset.name, '', 'no stale front identity on the reused element');
    assert.ok(!el.children.some((c) => c.src === front), 'the front image is gone');
  });

  it('keeps the .selected outline on a card across a reconciling re-render', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ id: 'a' })], '/images');
    const el = board.children[0];
    el.classList.add('selected'); // as a user selection would
    renderBoard(board, [card({ id: 'a', x: 99 })], '/images');
    assert.equal(board.children[0], el, 'same element reused');
    assert.ok(el.classList.contains('selected'), 'selection survives without re-applying it');
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

  it('reveals the front of a peeked face-down card, tagged with the private-peek cue', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ face_up: false, peeked: true })], '/images');
    const el = board.children[0];
    assert.ok(el.classList.contains('peeked'));
    assert.equal(el.dataset.peeked, '1');
    assert.equal(el.dataset.shown, '');
    // The viewer peeked it, so they privately see the front (at reduced opacity), not a back.
    assert.ok(!el.classList.contains('face-down'));
    assert.equal(el.children[0]?.src, '/images/sets/imperial_edition/hida_kisada.jpg');
  });

  it('reveals the front of a face-down card shown to this viewer', () => {
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ face_up: false, shown: true })], '/images');
    const el = board.children[0];
    assert.ok(!el.classList.contains('face-down'), 'the opponent may identify a shown card');
    assert.equal(el.children[0]?.src, '/images/sets/imperial_edition/hida_kisada.jpg');
  });

  it('keeps the reveal outline on a hidden card its owner has shown, still drawn as a back', () => {
    // The owner's own shown face-down card is a hidden stub carrying shown: it stays a back to them
    // but wears the reveal outline so they can tell they have disclosed it to the opponent.
    const board = document.getElementById('battlefield');
    renderBoard(board, [card({ hidden: true, shown: true })], '/images');
    const el = board.children[0];
    assert.ok(el.classList.contains('shown'), 'the reveal outline draws');
    assert.ok(el.classList.contains('face-down'), 'but the card stays a back to its owner');
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

  it('reuses a province card element across renders, patching it in place', () => {
    const area = document.createElement('div');
    const snap = seatSnapshot();
    const slot = () => area.children[1].children[1]; // provinces wrapper -> province idx 1
    snap.zones['P1:province:1'] = [card({ id: 'pv1' })];
    renderTableau(area, 'P1', snap, '/images');
    const first = slot().children[0];
    snap.zones['P1:province:1'] = [card({ id: 'pv1', bowed: true })];
    renderTableau(area, 'P1', snap, '/images');
    assert.equal(area.children[1].children.length, 4, 'still four provinces after re-render');
    assert.equal(slot().children[0], first, 'same element reused');
    assert.ok(first.classList.contains('bowed'), 'patched in place');
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

  it('reuses a hand card element across renders and reorders it in place', () => {
    const hand = document.createElement('div');
    renderHand(hand, [card({ id: 'h1' }), card({ id: 'h2' })], '/images');
    const h1 = hand.children[0];
    renderHand(hand, [card({ id: 'h2' }), card({ id: 'h1' })], '/images');
    assert.deepEqual(
      hand.children.map((el) => el.dataset.cardId),
      ['h2', 'h1'],
    );
    assert.equal(hand.children[1], h1, 'h1 keeps its element after the reorder');
  });

  it('clears a drag-hidden source when its card is reconciled back into the zone', () => {
    const hand = document.createElement('div');
    renderHand(hand, [card({ id: 'h1' }), card({ id: 'h2' })], '/images');
    // A dragged card's source is hidden while its ghost follows the pointer; the next render reuses
    // that same node, so it must come back visible.
    hand.children[0].style.visibility = 'hidden';
    renderHand(hand, [card({ id: 'h2' }), card({ id: 'h1' })], '/images');
    const reused = hand.children.find((el) => el.dataset.cardId === 'h1');
    assert.equal(reused.style.visibility, '', 'the reused element is visible again, not vanished');
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

  it('draws a card-crop canvas when the seat has an avatar', () => {
    const panel = document.createElement('div');
    const avatar = { image_path: 'sets/x/doji.jpg', crop: { left: 0.1, top: 0.1, right: 0.4, bottom: 0.4 } };
    renderPanel(panel, { name: 'Ada', honor: 0, avatar }, { imgBase: '/images' });
    assert.equal(panel.children[0].tagName, 'CANVAS');
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

  it('build SPAWN_CARD and REMOVE_CARD intents', () => {
    assert.deepEqual(spawnMessage({ name: 'X', img: 'a.jpg', side: 'FATE', x: 1, y: 2 }), {
      type: 'INTENT',
      intent: { op: 'SPAWN_CARD', name: 'X', img: 'a.jpg', side: 'FATE', position: [1, 2] },
    });
    assert.deepEqual(removeMessage('c1'), {
      type: 'INTENT',
      intent: { op: 'REMOVE_CARD', card_id: 'c1' },
    });
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

describe('patchCard', () => {
  const view = (over = {}) => ({
    id: 'c1', name: 'Hida', img: 'a.jpg', side: 'DYNASTY', owner: 'P1',
    bowed: false, inverted: false, face_up: true, shown: false, peeked: false,
    hidden: false, token: false, pregame: false, ...over,
  });

  it('applies classes, dataset, and a single face on first build', () => {
    const el = document.createElement('div');
    patchCard(el, view({ bowed: true }), null, '/img');
    assert.ok(el.classList.contains('bowed'));
    assert.equal(el.dataset.cardId, 'c1');
    assert.equal(el.dataset.name, 'Hida');
    assert.equal(el.children.length, 1, 'exactly one face child');
  });

  it('re-patching with the same view does not duplicate the face', () => {
    const el = document.createElement('div');
    const v = view();
    patchCard(el, v, null, '/img');
    patchCard(el, v, v, '/img');
    assert.equal(el.children.length, 1);
  });

  it('clears a flag that goes false and swaps the face in place on a state change', () => {
    setBackArt({ DYNASTY: '/back.jpg' });
    const el = document.createElement('div');
    const up = view({ bowed: true });
    patchCard(el, up, null, '/img');
    patchCard(el, view({ bowed: false, face_up: false }), up, '/img');
    assert.equal(el.dataset.bowed, '', 'bowed dataset cleared');
    assert.ok(!el.classList.contains('bowed'), 'bowed class cleared');
    assert.ok(el.classList.contains('face-down'), 'now face-down');
    assert.equal(el.children.length, 1, 'face replaced, not appended');
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

  it('converts an already-placed card (x >= 0) from canonical to this viewer\'s pixels', () => {
    const W = 800;
    const H = 600;
    const card = { id: 'c1', pregame: false, owner: 'P1', x: 0.4, y: 0.7 };
    const [asP1] = placeUnplacedCards([card], 'P1', anchorFor, W, H);
    const [asP2] = placeUnplacedCards([card], 'P2', anchorFor, W, H);
    assert.deepEqual(asP1, { ...card, ...canonicalToView(0.4, 0.7, true, W, H) });
    assert.deepEqual(asP2, { ...card, ...canonicalToView(0.4, 0.7, false, W, H) });
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

describe('battlefield perspective transform', () => {
  const W = 1000;
  const H = 800;

  it('round-trips a drop back to the same pixels for each seat', () => {
    for (const viewerIsP1 of [true, false]) {
      const canon = viewToCanonical(300, 240, viewerIsP1, W, H);
      const back = canonicalToView(canon.x, canon.y, viewerIsP1, W, H);
      assert.ok(Math.abs(back.x - 300) <= 1 && Math.abs(back.y - 240) <= 1);
    }
  });

  it('shows P2 the 180°-rotated view of a canonical position', () => {
    const p2px = canonicalToView(0.3, 0.25, false, W, H);
    const inP1Frame = viewToCanonical(p2px.x, p2px.y, true, W, H);
    assert.ok(Math.abs(inP1Frame.x - 0.7) < 0.02 && Math.abs(inP1Frame.y - 0.75) < 0.02);
  });

  it('puts a low canonical card on opposite halves for the two seats', () => {
    const canon = { x: 0.2, y: 0.9 };
    const p1 = canonicalToView(canon.x, canon.y, true, W, H);
    const p2 = canonicalToView(canon.x, canon.y, false, W, H);
    assert.ok(p1.y > H / 2, 'P1 (canonical) sees it low');
    assert.ok(p2.y < H / 2, 'P2 sees the same card mirrored to the top');
  });

  it('is size-independent: the same canonical position maps to the same fraction on any board', () => {
    const small = canonicalToView(0.6, 0.4, true, 400, 300);
    const large = canonicalToView(0.6, 0.4, true, 1600, 1200);
    const fracSmall = viewToCanonical(small.x, small.y, true, 400, 300);
    const fracLarge = viewToCanonical(large.x, large.y, true, 1600, 1200);
    assert.ok(Math.abs(fracSmall.x - fracLarge.x) < 0.01 && Math.abs(fracSmall.y - fracLarge.y) < 0.01);
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

  beforeEach(() => {
    root = document.getElementById('boardStage');
    root.dataset.viewerSeat = 'P1';
    board = document.getElementById('battlefield');
    sent = [];
    initBoardInteractions(root, board, (message) => sent.push(message));
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

  // Like selectTwo but three cards, so a test can mix ownership/face into one selection. Selection is
  // not owner-gated, so an opponent card can ride the selection and exercise a per-card action's filter.
  const selectThree = (opts1 = {}, opts2 = {}, opts3 = {}) => {
    const c1 = fakeCard('c1', { onBattlefield: true, owner: 'P1', ...opts1 });
    const c2 = fakeCard('c2', { onBattlefield: true, owner: 'P1', ...opts2 });
    const c3 = fakeCard('c3', { onBattlefield: true, owner: 'P1', ...opts3 });
    board.querySelectorAll = (sel) => (sel === '.board-card' ? [c1, c2, c3] : []);
    root._emit('pointerdown', onCard(c1));
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    root._emit('pointerdown', onCard(c2, { ctrlKey: true }));
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    root._emit('pointerdown', onCard(c3, { ctrlKey: true }));
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    return [c1, c2, c3];
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
      { type: 'INTENT', intent: { op: 'REMOVE_CARD', card_id: 'c1' } },
      { type: 'INTENT', intent: { op: 'REMOVE_CARD', card_id: 'c2' } },
    ]);
  });

  it('peeks every face-down card in the selection, one PEEK per card', () => {
    const [c1] = selectTwo({ faceUp: false }, { faceUp: false });
    sent.length = 0;
    root._emit('contextmenu', rightClick({ card: c1 }));
    clickMenuItem(root, 'Peek');
    assert.deepEqual(
      sent.map((m) => [m.intent.op, m.intent.card_id]),
      [
        ['PEEK', 'c1'],
        ['PEEK', 'c2'],
      ],
    );
  });

  it("group Peek skips cards that are already peeked or the opponent's", () => {
    // c1 is a fresh face-down own card; c2 is already peeked (nothing to do); c3 is the opponent's.
    const [c1] = selectThree(
      { faceUp: false },
      { faceUp: false, peeked: true },
      { faceUp: false, owner: 'P2', hidden: true },
    );
    sent.length = 0;
    root._emit('contextmenu', rightClick({ card: c1 }));
    clickMenuItem(root, 'Peek');
    assert.deepEqual(
      sent.map((m) => m.intent.card_id),
      ['c1'],
    );
  });

  it('drops the peek on every peeked card in the selection from "Stop peeking"', () => {
    const [c1] = selectTwo({ faceUp: false, peeked: true }, { faceUp: false, peeked: true });
    sent.length = 0;
    root._emit('contextmenu', rightClick({ card: c1 }));
    clickMenuItem(root, 'Stop peeking');
    assert.deepEqual(
      sent.map((m) => [m.intent.op, m.intent.card_id]),
      [
        ['UNPEEK', 'c1'],
        ['UNPEEK', 'c2'],
      ],
    );
  });

  it('shows every face-down card in the selection, one SHOW per card', () => {
    const [c1] = selectTwo({ faceUp: false }, { faceUp: false });
    sent.length = 0;
    root._emit('contextmenu', rightClick({ card: c1 }));
    clickMenuItem(root, 'Show opponent');
    assert.deepEqual(
      sent.map((m) => [m.intent.op, m.intent.card_id]),
      [
        ['SHOW', 'c1'],
        ['SHOW', 'c2'],
      ],
    );
  });

  it('group Show skips cards already shown, face-up, or the opponent\'s', () => {
    // c1 is a fresh face-down own card; c2 is already shown; c3 is a face-up own card (public
    // already); c4 is the opponent's face-down card.
    const c1 = fakeCard('c1', { onBattlefield: true, owner: 'P1', faceUp: false });
    const c2 = fakeCard('c2', { onBattlefield: true, owner: 'P1', faceUp: false, shown: true });
    const c3 = fakeCard('c3', { onBattlefield: true, owner: 'P1', faceUp: true });
    const c4 = fakeCard('c4', { onBattlefield: true, owner: 'P2', faceUp: false, hidden: true });
    board.querySelectorAll = (sel) => (sel === '.board-card' ? [c1, c2, c3, c4] : []);
    for (const c of [c1, c2, c3, c4]) {
      root._emit('pointerdown', onCard(c, { ctrlKey: true }));
      root._emit('pointerup', onZone({ zone: 'battlefield' }));
    }
    sent.length = 0;
    root._emit('contextmenu', rightClick({ card: c1 }));
    clickMenuItem(root, 'Show opponent');
    assert.deepEqual(
      sent.map((m) => m.intent.card_id),
      ['c1'],
    );
  });

  it('stops showing every shown card in the selection from "Stop showing"', () => {
    const [c1] = selectTwo({ faceUp: false, shown: true }, { faceUp: false, shown: true });
    sent.length = 0;
    root._emit('contextmenu', rightClick({ card: c1 }));
    clickMenuItem(root, 'Stop showing');
    assert.deepEqual(
      sent.map((m) => [m.intent.op, m.intent.card_id]),
      [
        ['UNSHOW', 'c1'],
        ['UNSHOW', 'c2'],
      ],
    );
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
    // A normalized canonical position (centre fraction, P1 frame) in the viewer's lower half. Exact
    // geometry is covered by the real-browser e2e; the fake DOM only checks the decision.
    const [x, y] = move.position;
    assert.ok(x > 0 && x < 1 && y > 0.5 && y < 1);
  });

  it('fans successive hand plays so they do not land in a perfect stack', () => {
    const play = (cardId) =>
      root._emit('dblclick', dblClick({ card: fakeCard(cardId, { owner: 'P1', inHand: true }) }));
    play('h1');
    play('h2');
    play('h3');
    const xs = sent.map((m) => m.intent.position[0]);
    assert.ok(xs[0] < xs[1] && xs[1] < xs[2], 'each play steps one fan slot right');
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
      'Attach',
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
    const dup = sent.at(-1).intent;
    assert.equal(dup.op, 'SPAWN_CARD');
    assert.deepEqual([dup.name, dup.img, dup.side], ['Hida Kisada', 'sets/hk.jpg', 'DYNASTY']);
    // Spawned at a canonical centre fraction down-right of the original; exact geometry is e2e's job.
    const [x, y] = dup.position;
    assert.ok(x > 0 && x < 1 && y > 0 && y < 1);
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

  it('trims a hand card menu: no in-play manipulation, no Send to Hand, but play, reveal and disposal', () => {
    const card = fakeCard('h1', { side: 'FATE', owner: 'P1', onBattlefield: false, inHand: true });
    root._emit('contextmenu', rightClick({ zone: { zone: 'hand', owner: 'P1' }, card }));
    assert.deepEqual(menuLabels(root), [
      'View', // available on every card
      'Play face down', // play a hand card onto the board face down (focusing in a duel)
      'Show opponent', // a hand card is hidden from the opponent, so reveal is offered
      'Attach', // arm a two-step attach: this hand card, then the parent to play-and-attach it to
      'Send to Discard',
      'Send to Deck (top)',
      'Send to Deck (bottom)',
    ]);
  });

  it('sends a face-down MOVE_CARD into the viewer half when playing a hand card face down', () => {
    const card = fakeCard('h1', { side: 'FATE', owner: 'P1', onBattlefield: false, inHand: true });
    root._emit('contextmenu', rightClick({ zone: { zone: 'hand', owner: 'P1' }, card }));
    clickMenuItem(root, 'Play face down');
    const move = sent.at(-1).intent;
    assert.equal(move.op, 'MOVE_CARD');
    assert.deepEqual(move.to, { kind: 'battlefield' });
    assert.equal(move.face_down, true);
    // Landed in the viewer's half like a double-click play, so the card sits clear of the provinces.
    const [x, y] = move.position;
    assert.ok(x > 0 && x < 1 && y > 0.5 && y < 1);
  });

  it('omits "Play face down" on an opponent hand card — not yours to play', () => {
    // An opponent's hand card is a hidden stub owned by them; you cannot play it.
    const card = fakeCard('h9', { side: 'FATE', owner: 'P2', onBattlefield: false, inHand: true, hidden: true });
    root._emit('contextmenu', rightClick({ zone: { zone: 'hand', owner: 'P2' }, card }));
    assert.ok(!menuLabels(root).includes('Play face down'));
  });

  it('shows a single hand card to the opponent, though it is face-up to its owner', () => {
    // A hand card is not face-down, so "Show opponent" must cover the clicked card directly rather
    // than relying on the face-down gate the group fan-out uses for battlefield cards.
    const card = fakeCard('h1', { side: 'FATE', owner: 'P1', onBattlefield: false, inHand: true });
    root._emit('contextmenu', rightClick({ zone: { zone: 'hand', owner: 'P1' }, card }));
    clickMenuItem(root, 'Show opponent');
    assert.deepEqual(sent.at(-1).intent, { op: 'SHOW', card_id: 'h1' });
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

  it('offers no Peek on an opponent hidden card — you cannot look at their cards', () => {
    // A hidden opponent card: not yours to peek (they must Show it), and not yours to show either.
    const card = fakeCard('c1', { side: 'DYNASTY', owner: 'P2', hidden: true });
    root._emit('contextmenu', rightClick({ card }));
    const labels = menuLabels(root);
    assert.ok(!labels.includes('Peek'), 'no peeking the opponent');
    assert.ok(!labels.includes('Show opponent') && !labels.includes('Stop showing'));
  });

  it('peeks your own hidden card, sending one PEEK id', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { side: 'DYNASTY', owner: 'P1', hidden: true }) }));
    assert.ok(menuLabels(root).includes('Peek'));
    clickMenuItem(root, 'Peek');
    assert.deepEqual(sent[0].intent, { op: 'PEEK', card_id: 'c1' });
  });

  it('offers "Stop peeking" on a card the viewer is peeking, sending UNPEEK', () => {
    const card = fakeCard('c1', { side: 'DYNASTY', owner: 'P1', faceUp: false, peeked: true });
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

  it('trims a visible opponent card to just View and Duplicate', () => {
    // Manipulating a card you don't control is server-rejected, so an opponent's face-up card offers
    // only the two owner-agnostic actions: View (look) and Duplicate (make your own token copy).
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { side: 'FATE', owner: 'P2' }) }));
    assert.deepEqual(menuLabels(root), ['View', 'Duplicate']);
  });

  it('keeps the in-play actions on an owner-less public card (anyone may manipulate it)', () => {
    // A public token is shared, so the server lets either seat flip/bow/invert and note it.
    root._emit('contextmenu', rightClick({ card: fakeCard('c1', { side: 'FATE', owner: '' }) }));
    const labels = menuLabels(root);
    for (const action of ['Flip', 'Bow', 'Invert', 'Add note…']) {
      assert.ok(labels.includes(action), `public card keeps ${action}`);
    }
    assert.ok(!labels.includes('Give control'), 'but a public card has no controller to give away');
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

    assert.deepEqual(sent, [{ type: 'INTENT', intent: { op: 'REMOVE_CARD', card_id: 'c1' } }]);
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
    // The click point is recorded as a canonical centre fraction; exact geometry is covered by e2e.
    assert.equal(created.length, 1);
    const { x, y } = created[0];
    assert.ok(x > 0 && x < 1 && y > 0 && y < 1);
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

describe('layoutAttachments', () => {
  it('returns the same array untouched when there are no attachments', () => {
    const cards = [{ id: 'a', x: 0, y: 0 }, { id: 'b', x: 10, y: 10 }];
    assert.equal(layoutAttachments(cards, {}), cards);
  });

  it('stacks a card-target child behind its parent, shifted up, and flags it attached', () => {
    const cards = [
      { id: 'child', x: 5, y: 5 },
      { id: 'parent', x: 40, y: 60 },
    ];
    const out = layoutAttachments(cards, { child: { card: 'parent' } });
    // The child is emitted before its parent so it draws underneath it.
    assert.deepEqual(out.map((c) => c.id), ['child', 'parent']);
    const child = out.find((c) => c.id === 'child');
    assert.deepEqual([child.x, child.y], [40, 60 - ATTACH_STACK_OFFSET]);
    assert.equal(child.attached, true);
    assert.equal(child.attachParent, 'parent', 'records its host for the drag-along stack');
    const parent = out.find((c) => c.id === 'parent');
    assert.deepEqual([parent.x, parent.y], [40, 60], 'the parent keeps its own position');
    assert.ok(!parent.attached);
  });

  it('fans several children of one parent progressively higher', () => {
    const cards = [
      { id: 'p', x: 0, y: 100 },
      { id: 'c1', x: 0, y: 0 },
      { id: 'c2', x: 0, y: 0 },
    ];
    const out = layoutAttachments(cards, { c1: { card: 'p' }, c2: { card: 'p' } });
    // The higher card (c2) draws behind the lower (c1), which draws behind the host (p, in front).
    assert.deepEqual(out.map((c) => c.id), ['c2', 'c1', 'p']);
    const y = (id) => out.find((c) => c.id === id).y;
    assert.equal(y('c1'), 100 - ATTACH_STACK_OFFSET);
    assert.equal(y('c2'), 100 - ATTACH_STACK_OFFSET * 2);
  });

  it('gives every card in a branched tower its own rung, none colliding', () => {
    // Host P carries items A and B; A itself carries C. The per-parent slot index would put B and C
    // on the same rung — the whole-tower count must keep all four distinct.
    const cards = [
      { id: 'P', x: 0, y: 300 },
      { id: 'A', x: 0, y: 0 },
      { id: 'B', x: 0, y: 0 },
      { id: 'C', x: 0, y: 0 },
    ];
    const out = layoutAttachments(cards, { A: { card: 'P' }, B: { card: 'P' }, C: { card: 'A' } });
    const y = (id) => out.find((c) => c.id === id).y;
    assert.equal(new Set(['A', 'B', 'C', 'P'].map(y)).size, 4, 'four distinct rungs, no collision');
    // DFS pre-order: A (rung 1), C under A (rung 2), then B (rung 3), each a step above the host.
    assert.equal(y('A'), 300 - ATTACH_STACK_OFFSET);
    assert.equal(y('C'), 300 - ATTACH_STACK_OFFSET * 2);
    assert.equal(y('B'), 300 - ATTACH_STACK_OFFSET * 3);
  });

  it('cascades a chain, the deepest child furthest behind and highest', () => {
    const cards = [
      { id: 'gp', x: 0, y: 200 },
      { id: 'p', x: 0, y: 0 },
      { id: 'c', x: 0, y: 0 },
    ];
    const out = layoutAttachments(cards, { p: { card: 'gp' }, c: { card: 'p' } });
    assert.deepEqual(out.map((c) => c.id), ['c', 'p', 'gp']);
    const at = (id) => out.find((c) => c.id === id);
    assert.equal(at('p').y, 200 - ATTACH_STACK_OFFSET);
    assert.equal(at('c').y, 200 - ATTACH_STACK_OFFSET * 2);
  });

  it('leaves a province-target child where it sits when no anchor resolver is given', () => {
    const cards = [{ id: 'fort', x: 12, y: 34 }];
    const out = layoutAttachments(cards, { fort: { province: 'P1:province:0' } });
    const fort = out.find((c) => c.id === 'fort');
    assert.equal(fort.attached, true);
    assert.deepEqual([fort.x, fort.y], [12, 34]);
  });

  it('anchors a province-target child on its slot, fanned inboard by the resolver direction', () => {
    const cards = [{ id: 'fort', x: 12, y: 34 }];
    const anchorFor = (key) => (key === 'P1:province:2' ? { x: 90, y: 200, dir: -1 } : null);
    const out = layoutAttachments(cards, { fort: { province: 'P1:province:2' } }, anchorFor);
    const fort = out.find((c) => c.id === 'fort');
    assert.equal(fort.attached, true);
    // x matches the slot; y is one offset inboard (up, dir -1) of the slot's top.
    assert.deepEqual([fort.x, fort.y], [90, 200 - ATTACH_STACK_OFFSET]);
  });

  it('fans several province-target children on one slot progressively inboard', () => {
    const cards = [
      { id: 'a', x: 0, y: 0 },
      { id: 'b', x: 0, y: 0 },
    ];
    const anchorFor = () => ({ x: 50, y: 10, dir: 1 }); // opponent slot: fans down
    const out = layoutAttachments(
      cards,
      { a: { province: 'P2:province:0' }, b: { province: 'P2:province:0' } },
      anchorFor,
    );
    const y = (id) => out.find((c) => c.id === id).y;
    assert.equal(y('a'), 10 + ATTACH_STACK_OFFSET);
    assert.equal(y('b'), 10 + ATTACH_STACK_OFFSET * 2);
    // Fanning down, the nearest-slot card (a) draws behind the lower one (b), so it comes first.
    assert.deepEqual(out.map((c) => c.id), ['a', 'b']);
  });

  it('continues the province tower through a fort\'s own attachment', () => {
    // A card hung on a province-attached fort stacks in the same column, one step past the fort —
    // the fort's subtree continues the province's count rather than restarting from the fort.
    const cards = [
      { id: 'fort', x: 0, y: 0 },
      { id: 'item', x: 9, y: 9 },
    ];
    const anchorFor = () => ({ x: 40, y: 200, dir: -1 });
    const out = layoutAttachments(
      cards,
      { fort: { province: 'P1:province:0' }, item: { card: 'fort' } },
      anchorFor,
    );
    const at = (id) => out.find((c) => c.id === id);
    assert.deepEqual([at('fort').x, at('fort').y], [40, 200 - ATTACH_STACK_OFFSET]);
    assert.deepEqual([at('item').x, at('item').y], [40, 200 - ATTACH_STACK_OFFSET * 2]);
    assert.equal(at('item').attachParent, 'fort', 'the sub-attachment carries with the fort');
  });

  it('falls back to the child position when the resolver has no anchor for the slot', () => {
    const cards = [{ id: 'fort', x: 12, y: 34 }];
    const out = layoutAttachments(cards, { fort: { province: 'P1:province:0' } }, () => null);
    assert.deepEqual([out[0].x, out[0].y], [12, 34]);
  });

  it('ignores an attachment whose parent card has left the board', () => {
    const cards = [{ id: 'child', x: 5, y: 5 }];
    const out = layoutAttachments(cards, { child: { card: 'gone' } });
    // The child is still flagged attached (its relationship stands) but keeps its own position.
    assert.equal(out[0].attached, true);
    assert.deepEqual([out[0].x, out[0].y], [5, 5]);
  });
});

describe('initBoardInteractions — attach', () => {
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

  // A pointer event whose target resolves to a province slot (and no card beneath it).
  const onProvince = (dataset, overrides = {}) => ({
    button: 0,
    clientX: 30,
    clientY: 50,
    target: { closest: (sel) => (sel === '[data-zone="province"]' ? { dataset } : null) },
    ...overrides,
  });

  // Arm an attach on `childEl` through its context menu, then clear `sent` so the test asserts only
  // the messages the target click produces.
  const armAttach = (childEl, zone = null) => {
    root._emit('contextmenu', rightClick({ zone, card: childEl }));
    clickMenuItem(root, 'Attach');
    sent.length = 0;
  };

  it('attaches a battlefield card to another card via the two-step pick', () => {
    armAttach(fakeCard('child', { owner: 'P1' }));
    root._emit('pointerdown', onCard(fakeCard('parent', { owner: 'P1' })));
    assert.deepEqual(sent, [
      { type: 'INTENT', intent: { op: 'ATTACH', card_id: 'child', to: { kind: 'card', card_id: 'parent' } } },
    ]);
  });

  it('attaches a card to a province slot', () => {
    armAttach(fakeCard('child', { owner: 'P1' }));
    root._emit('pointerdown', onProvince({ owner: 'P1', idx: '2' }));
    assert.deepEqual(sent, [
      {
        type: 'INTENT',
        intent: {
          op: 'ATTACH',
          card_id: 'child',
          to: { kind: 'zone', zone: { owner: 'P1', role: 'province', idx: 2 } },
        },
      },
    ]);
  });

  it('plays a hand card onto the board then attaches it (move + attach)', () => {
    const child = fakeCard('h1', { side: 'FATE', owner: 'P1', onBattlefield: false, inHand: true });
    armAttach(child, { zone: 'hand', owner: 'P1' });
    root._emit('pointerdown', onCard(fakeCard('parent', { owner: 'P1', x: 40, y: 50 })));
    assert.deepEqual(sent.map((m) => m.intent.op), ['MOVE_CARD', 'ATTACH']);
    assert.equal(sent[0].intent.card_id, 'h1');
    assert.deepEqual(sent[0].intent.to, { kind: 'battlefield' });
    assert.deepEqual(sent[1].intent, {
      op: 'ATTACH',
      card_id: 'h1',
      to: { kind: 'card', card_id: 'parent' },
    });
  });

  it('plays a hand card to mid-board then attaches it to a province', () => {
    // A province target carries no board position, so the play lands the card at the board centre
    // before attaching — the render then anchors it on the province slot.
    const child = fakeCard('h1', { side: 'FATE', owner: 'P1', onBattlefield: false, inHand: true });
    armAttach(child, { zone: 'hand', owner: 'P1' });
    root._emit('pointerdown', onProvince({ owner: 'P1', idx: '0' }));
    assert.deepEqual(sent.map((m) => m.intent.op), ['MOVE_CARD', 'ATTACH']);
    assert.deepEqual(sent[0].intent.position, [0.5, 0.5]);
    assert.deepEqual(sent[0].intent.to, { kind: 'battlefield' });
    assert.deepEqual(sent[1].intent.to, {
      kind: 'zone',
      zone: { owner: 'P1', role: 'province', idx: 0 },
    });
  });

  it('offers Attach on a card sitting in a province', () => {
    // The third initiation source the menu must serve (in play, in hand, in a province); a province
    // card reaches the menu through a different composition path than a plain battlefield card.
    const inProvince = fakeCard('pc', {
      owner: 'P1',
      onBattlefield: false,
      province: { dataset: { zone: 'province', owner: 'P1', idx: '0' } },
    });
    root._emit('contextmenu', rightClick({ zone: { zone: 'province', owner: 'P1', idx: '0' }, card: inProvince }));
    assert.ok(menuLabels(root).includes('Attach'));
  });

  it('offers Detach only on an attached card and sends DETACH', () => {
    const attached = fakeCard('child', { owner: 'P1' });
    attached.dataset.attached = '1';
    root._emit('contextmenu', rightClick({ card: attached }));
    assert.ok(menuLabels(root).includes('Detach'));
    clickMenuItem(root, 'Detach');
    assert.deepEqual(sent.at(-1).intent, { op: 'DETACH', card_id: 'child' });
  });

  it('omits Detach on a card that is not attached', () => {
    root._emit('contextmenu', rightClick({ card: fakeCard('child', { owner: 'P1' }) }));
    assert.ok(!menuLabels(root).includes('Detach'));
  });

  it('cancels an armed attach on Escape, sending nothing on the next click', () => {
    armAttach(fakeCard('child', { owner: 'P1' }));
    document._emit('keydown', { key: 'Escape', preventDefault() {} });
    root._emit('pointerdown', onCard(fakeCard('parent', { owner: 'P1' })));
    assert.equal(sent.length, 0);
  });

  it('cancels without attaching when the armed card itself is clicked', () => {
    const child = fakeCard('child', { owner: 'P1' });
    armAttach(child);
    root._emit('pointerdown', onCard(child));
    assert.equal(sent.length, 0);
  });

  it('cancels on a click that lands on no card or province', () => {
    armAttach(fakeCard('child', { owner: 'P1' }));
    root._emit('pointerdown', offCard());
    assert.equal(sent.length, 0);
  });

  it('cancels rather than sending a doomed attach to a card not on the battlefield', () => {
    // The server only attaches to a battlefield card, so a hand/discard card is not a valid parent.
    armAttach(fakeCard('child', { owner: 'P1' }));
    root._emit(
      'pointerdown',
      onCard(fakeCard('h1', { owner: 'P1', onBattlefield: false, inHand: true })),
    );
    assert.equal(sent.length, 0);
  });
});

describe('initBoardInteractions — dragging an attached stack', () => {
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

  // A host card with one child glued behind it at offset (+8, -24), both reported by the battlefield.
  const stack = () => {
    const host = placedCard('host', 100, 100);
    host.dataset.owner = 'P1';
    const child = placedCard('child', 108, 76);
    child.dataset.owner = 'P1';
    child.dataset.attached = '1';
    child.dataset.attachParent = 'host';
    board.querySelectorAll = (sel) => (sel === '.board-card' ? [child, host] : []);
    return { host, child };
  };

  const offset = (a, b) => [
    parseFloat(a.style.left) - parseFloat(b.style.left),
    parseFloat(a.style.top) - parseFloat(b.style.top),
  ];

  it('carries the attached child in formation and lifted while the host is dragged', () => {
    const { host, child } = stack();
    root._emit('pointerdown', onCard(host));
    root._emit('pointermove', { clientX: 160, clientY: 140, target: { closest: () => null } });
    assert.deepEqual(offset(child, host), [8, -24]);
    assert.ok(child.classList.contains('dragging'));
  });

  it('sends only the host move and leaves the stack placed for the snapshot to re-glue', () => {
    const { host, child } = stack();
    root._emit('pointerdown', onCard(host));
    root._emit('pointermove', { clientX: 160, clientY: 140, target: { closest: () => null } });
    const draggedLeft = parseFloat(child.style.left);
    root._emit('pointerup', onZone({ zone: 'battlefield' }));
    assert.deepEqual(sent.map((m) => m.intent.op), ['SET_CARD_POS']);
    assert.equal(sent[0].intent.card_id, 'host');
    assert.equal(parseFloat(child.style.left), draggedLeft, 'the child stays where it was dragged');
    assert.ok(!child.classList.contains('dragging'));
  });

  it('snaps the stack home when the drag is cancelled', () => {
    const { host, child } = stack();
    root._emit('pointerdown', onCard(host));
    root._emit('pointermove', { clientX: 160, clientY: 140, target: { closest: () => null } });
    root._emit('pointercancel', {});
    assert.deepEqual([parseFloat(child.style.left), parseFloat(child.style.top)], [108, 76]);
    assert.ok(!child.classList.contains('dragging'));
  });

  it('gathers a whole chain, carrying grandchildren too', () => {
    const host = placedCard('host', 100, 100);
    host.dataset.owner = 'P1';
    const child = placedCard('child', 100, 76);
    child.dataset.attachParent = 'host';
    const grandchild = placedCard('grand', 100, 52);
    grandchild.dataset.attachParent = 'child';
    board.querySelectorAll = (sel) => (sel === '.board-card' ? [grandchild, child, host] : []);

    root._emit('pointerdown', onCard(host));
    root._emit('pointermove', { clientX: 160, clientY: 140, target: { closest: () => null } });

    // Both descendants ride lifted and keep their offset from the host.
    assert.deepEqual(offset(child, host), [0, -24]);
    assert.deepEqual(offset(grandchild, host), [0, -48]);
    assert.ok(child.classList.contains('dragging') && grandchild.classList.contains('dragging'));
  });
});
