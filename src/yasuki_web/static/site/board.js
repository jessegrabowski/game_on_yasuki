// Shared battlefield rendering and interaction for a play room. Cards are absolutely-positioned DOM
// elements built via createElement/CSSOM rather than innerHTML: the page CSP (style-src 'self')
// blocks inline style attributes, and property assignment needs no manual escaping.

export function node(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text != null) el.textContent = text;
  return el;
}

// A decorative, alt-less back image that fills its parent card or pile tile.
function backImage(src, className) {
  const img = node('img', className);
  img.src = src;
  img.alt = '';
  return img;
}

// The generic card back to draw per card side while a card is face-down, as absolute image URLs.
// Empty until the lobby loads /api/card-backs; an unset side falls back to the CSS gradient.
let backArt = {};

export function setBackArt(map) {
  backArt = map ?? {};
}

// Map the /api/card-backs payload ({deck: {era: path}}) to a back-image lookup as absolute URLs. A
// face-down card's era is itself hidden, so each deck side gets one canonical generic back; strongholds
// use the dynasty back (they are dynasty-side permanents, never tokens), and spawned tokens — keyed
// under TOKEN — use the dynasty token back.
export function backArtBySide(backs, imgBase) {
  const url = (path) => (path ? `${imgBase}/${path}` : undefined);
  return {
    FATE: url(backs?.Fate?.new),
    DYNASTY: url(backs?.Dynasty?.new),
    STRONGHOLD: url(backs?.Dynasty?.new),
    TOKEN: url(backs?.Dynasty?.token),
  };
}

// The back to draw for a face-down card: the token back for a spawned token (the server ids these
// "spawn-…"), otherwise the generic back for the card's side.
function backFor(card) {
  return card.id?.startsWith('spawn-') ? backArt.TOKEN : backArt[card.side];
}

// Show a card's face: its front art, or — while face-down — the generic back for its side. A hidden
// stub carries no front and a known card lying face-down must not reveal one, so both draw the back;
// with no back art loaded the CSS gradient stands in.
function applyFace(el, card, imgBase) {
  if (card.hidden || card.face_up === false) {
    el.classList.add('face-down');
    const back = backFor(card);
    if (back) el.appendChild(backImage(back));
    return;
  }
  const img = document.createElement('img');
  img.src = `${imgBase}/${card.img}`;
  img.alt = card.name;
  el.appendChild(img);
}

// Stamp the card state the context menu reads back off the DOM: identity, side and owner for routing
// "Send to…" intents and gating them by ownership, the token flag that gates the "Remove" item, and
// the flags whose toggle label depends on the current value. A hidden stub carries only id + side, so
// its other fields stay empty.
function tagCard(el, card) {
  el.dataset.cardId = card.id;
  el.dataset.bowed = card.bowed ? '1' : '';
  el.dataset.side = card.side ?? '';
  el.dataset.owner = card.owner ?? '';
  el.dataset.hidden = card.hidden ? '1' : '';
  el.dataset.faceUp = card.face_up ? '1' : '';
  el.dataset.token = card.token ? '1' : '';
  // shown: the card is public-facing (the menu offers "Stop showing"); peeked: this viewer sees it
  // only through their own private peek (rendered at reduced opacity, the menu offers "Stop peeking").
  el.dataset.shown = card.shown ? '1' : '';
  el.dataset.peeked = card.peeked ? '1' : '';
  if (card.back_card_id) el.dataset.doubleFaced = '1';
}

// An absolutely-positioned battlefield card.
function cardElement(card, imgBase) {
  const el = node('div', 'board-card');
  if (card.bowed) el.classList.add('bowed');
  if (card.inverted) el.classList.add('inverted');
  if (card.shown) el.classList.add('shown');
  if (card.peeked) el.classList.add('peeked');
  tagCard(el, card);
  el.style.left = `${card.x}px`;
  el.style.top = `${card.y}px`;
  applyFace(el, card, imgBase);
  return el;
}

// A card laid out in a zone (hand, province, pile) — flow-positioned, no x/y.
function zoneCard(card, imgBase) {
  const el = node('div', 'zone-card');
  if (card.bowed) el.classList.add('bowed');
  if (card.inverted) el.classList.add('inverted');
  if (card.shown) el.classList.add('shown');
  if (card.peeked) el.classList.add('peeked');
  tagCard(el, card);
  applyFace(el, card, imgBase);
  return el;
}

export function renderBoard(boardEl, cards, imgBase) {
  boardEl.replaceChildren(...cards.map((card) => cardElement(card, imgBase)));
}

// A card-sized pile (deck or discard) showing its top card or a back, with a count overlaid.
// A deck carries owner/side so a double-click can draw from it.
function pile(label, count, topCard, imgBase, deck) {
  const tile = node('div', deck ? 'pile deck' : 'pile');
  if (deck) {
    tile.dataset.zone = 'deck';
    tile.dataset.owner = deck.owner;
    tile.dataset.side = deck.side;
  }
  if (topCard) {
    tile.append(zoneCard(topCard, imgBase));
  } else if (deck && count > 0) {
    // A non-empty deck shows its side's card back; the gradient stands in until the backs load.
    const back = backArt[deck.side];
    if (back) tile.append(backImage(back, 'pile-back'));
    else tile.classList.add('is-back');
  }
  tile.append(node('span', 'pile-count', String(count)), node('span', 'pile-label', label));
  return tile;
}

// A discard pile drop zone showing its top (public) card and count.
function discard(label, cards, owner, role, imgBase) {
  const tile = pile(label, cards.length, cards.at(-1), imgBase);
  tile.dataset.zone = 'discard';
  tile.dataset.owner = owner;
  tile.dataset.role = role;
  return tile;
}

// A seat's tableau laid out on the battlefield like the desktop table: dynasty deck + discard at the
// left, the four provinces in the centre, fate discard + deck at the right. The stronghold/sensei/
// wind are not part of the tableau — they are loose battlefield cards the client lays out by the
// dynasty discard (see placeUnplacedCards).
export function renderTableau(container, seatName, snapshot, imgBase) {
  const zones = snapshot.zones ?? {};
  const decks = snapshot.decks ?? {};
  const zone = (role) => zones[`${seatName}:${role}`] ?? [];
  const deck = (side) => decks[`${seatName}:${side}`] ?? { count: 0, top: null };

  const left = node('div', 'tableau-decks');
  const dynasty = deck('dynasty');
  left.append(
    pile('Dynasty', dynasty.count, dynasty.top, imgBase, { owner: seatName, side: 'DYNASTY' }),
    discard('Discard', zone('dynasty_discard'), seatName, 'dynasty_discard', imgBase),
  );

  const provinces = node('div', 'provinces');
  for (const key of Object.keys(zones)
    .filter((k) => k.startsWith(`${seatName}:province:`))
    .sort()) {
    const slot = node('div', 'province');
    slot.dataset.zone = 'province';
    slot.dataset.owner = seatName;
    slot.dataset.idx = key.split(':')[2];
    for (const card of zones[key]) slot.append(zoneCard(card, imgBase));
    provinces.append(slot);
  }

  const right = node('div', 'tableau-decks');
  const fate = deck('fate');
  right.append(
    discard('Discard', zone('fate_discard'), seatName, 'fate_discard', imgBase),
    pile('Fate', fate.count, fate.top, imgBase, { owner: seatName, side: 'FATE' }),
  );

  container.replaceChildren(left, provinces, right);
}

// A seat's hand as a strip of full-size cards.
export function renderHand(container, cards, imgBase) {
  container.replaceChildren(...(cards ?? []).map((card) => zoneCard(card, imgBase)));
}

function initials(name) {
  return (
    (name ?? '')
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0].toUpperCase())
      .join('') || '?'
  );
}

// A seat's identity: avatar, name, and current honor. `editable` marks the honor with the local
// seat's editable cue; the opponent's gets the read-only cue instead.
export function renderPanel(container, info, { editable = false } = {}) {
  const avatar = node('div', 'avatar', initials(info.name));
  const meta = node('div', 'panel-meta');
  const honor = node('span', 'panel-honor', String(info.honor ?? 0));
  honor.classList.add(editable ? 'is-editable' : 'read-only');
  meta.append(node('span', 'panel-name', info.name ?? ''), honor);
  container.replaceChildren(avatar, meta);
  container.classList.toggle('is-away', info.connected === false);
}

const HIGHLIGHT_MS = 1200;

// Briefly flash the board card a log link points at. A no-op if the card is not on the board.
export function highlightCard(boardEl, cardId) {
  const el = boardEl.querySelector(`[data-card-id="${CSS.escape(cardId)}"]`);
  if (!el) return;
  el.classList.add('highlight');
  setTimeout(() => el.classList.remove('highlight'), HIGHLIGHT_MS);
}

// Client messages, with `room` injected by the caller. Card manipulation goes through real game
// intents; spawn/remove are separate messages the server turns into SpawnCard/RemoveCard intents.
export const intentMessage = (intent) => ({ type: 'INTENT', intent });
export const spawnMessage = (spawn) => ({ type: 'SPAWN', spawn });
export const removeMessage = (id) => ({ type: 'REMOVE', remove: { id } });

export const moveIntent = (id, x, y) => intentMessage({ op: 'SET_CARD_POS', card_id: id, x, y });
// Reposition a whole group in one message; sending one SET_CARD_POS per member instead would
// multiply the wire rate by the group size and trip the server's per-connection throttle.
export const moveGroupIntent = (moves) => intentMessage({ op: 'SET_CARD_POSITIONS', moves });
// The flag ops apply to a whole batch atomically; each builder takes one id or an array of them.
export const flipIntent = (ids) => intentMessage({ op: 'FLIP', card_ids: [].concat(ids) });
// BOW and UNBOW are distinct ops, so the toggle picks whichever one actually changes the card.
export const bowIntent = (ids, bowed) =>
  intentMessage({ op: bowed ? 'UNBOW' : 'BOW', card_ids: [].concat(ids) });
export const invertIntent = (ids) => intentMessage({ op: 'INVERT', card_ids: [].concat(ids) });
// Show/peek act on a single card: show is owner-gated (reveal your own card to your opponent), peek
// is not (any player may privately peek any card). Each carries one card id, not a batch.
export const showIntent = (id) => intentMessage({ op: 'SHOW', card_id: id });
export const unshowIntent = (id) => intentMessage({ op: 'UNSHOW', card_id: id });
export const peekIntent = (id) => intentMessage({ op: 'PEEK', card_id: id });
export const unpeekIntent = (id) => intentMessage({ op: 'UNPEEK', card_id: id });
// Turn a double-faced card (a flip stronghold) to its other printed face.
export const flipFaceIntent = (ids) => intentMessage({ op: 'FLIP_FACE', card_ids: [].concat(ids) });
// The flip a card wants: a double-faced card turns its printed face, anything else front↔deck-back.
const flipIntentFor = (doubleFaced, ids) => (doubleFaced ? flipFaceIntent(ids) : flipIntent(ids));
// A card the viewer currently sees as a back: an explicit hidden stub, or simply face-down.
const isFaceDown = (el) => el.dataset.hidden === '1' || el.dataset.faceUp !== '1';
// Whether a keystroke is the user typing into a field, where board hotkeys must stay out of the way.
const isTypingTarget = (el) =>
  !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable);
// Draw the top card of a seat's deck; the server routes it (fate → hand, dynasty → province).
export const drawIntent = (owner, side) => intentMessage({ op: 'DRAW', deck: { owner, side } });
// The 31-bit space the client samples a shuffle seed from, matching the server's getrandbits(31).
const SHUFFLE_SEED_SPACE = 2 ** 31;
// The client picks the shuffle seed so the resulting order is reproducible from the action log; the
// server reshuffles with it and the opponent only learns that a shuffle happened.
export const shuffleIntent = (owner, side) =>
  intentMessage({
    op: 'SHUFFLE',
    deck: { owner, side },
    seed: Math.floor(Math.random() * SHUFFLE_SEED_SPACE),
  });
export const flipDeckTopIntent = (owner, side) =>
  intentMessage({ op: 'FLIP_DECK_TOP', deck: { owner, side } });
// Reveal the deck to its owner: `value` carries the top-N count to log (null for a whole-deck search).
export const searchDeckIntent = (owner, side, value = null) =>
  intentMessage({ op: 'SEARCH_DECK', deck: { owner, side }, value });
// Bring a battlefield card to the top of the z-stack server-side, persisting a select-without-move.
export const raiseIntent = (id) => intentMessage({ op: 'RAISE', card_id: id });
// Move a seat's hidden deck top to a destination, keyed by the deck (its top carries no card id).
export const moveDeckTopIntent = (deck, to, position = null) =>
  intentMessage({ op: 'MOVE_DECK_TOP', deck, to, position });
const provinceZone = (owner, idx) => ({ owner, role: 'province', idx });
export const fillProvinceIntent = (owner, idx) =>
  intentMessage({ op: 'FILL_PROVINCE', zone: provinceZone(owner, idx) });
export const destroyProvinceIntent = (owner, idx) =>
  intentMessage({ op: 'DESTROY_PROVINCE', zone: provinceZone(owner, idx) });
export const discardProvinceIntent = (owner, idx) =>
  intentMessage({ op: 'DISCARD_PROVINCE', zone: provinceZone(owner, idx) });
export const createProvinceIntent = () => intentMessage({ op: 'CREATE_PROVINCE' });
// Move a card to a zone/deck/battlefield destination (position set only for the battlefield;
// to_bottom only for a deck, sliding the card under it instead of onto the top).
export const moveCardIntent = (id, to, position = null, toBottom = false, index = null) =>
  intentMessage({
    op: 'MOVE_CARD',
    card_id: id,
    to,
    position,
    ...(toBottom ? { to_bottom: true } : {}),
    ...(index == null ? {} : { value: index }),
  });
// Move a card already in the owner's hand to slot `index`, reordering the hand.
export const reorderHandIntent = (id, index) =>
  intentMessage({ op: 'REORDER_HAND', card_id: id, value: index });
// Negative-sentinel battlefield position for a card dealt without real coordinates; placeUnplacedCards
// recognizes x < 0 and lays the card out by the owner's deck (mirrors the server's _UNPLACED_BOARD_POS).
export const UNPLACED_POSITION = [-1, -1];
// Adjust the acting seat's honor by a signed amount; the server clamps the bounds.
export const honorIntent = (delta) => intentMessage({ op: 'SET_HONOR', delta });

// Build a MOVE_CARD destination from a drop target's data attributes (set on each drop zone).
function zoneDest(el) {
  const owner = el.dataset.owner;
  switch (el.dataset.zone) {
    case 'deck':
      return { kind: 'deck', deck: { owner, side: el.dataset.side } };
    case 'province':
      return { kind: 'zone', zone: { owner, role: 'province', idx: Number(el.dataset.idx) } };
    case 'hand':
      return { kind: 'zone', zone: { owner, role: 'hand', idx: null } };
    case 'discard':
      return { kind: 'zone', zone: { owner, role: el.dataset.role, idx: null } };
    default:
      return null;
  }
}

// Move `el` to slot `index` among its siblings (counting only the others), reordering in place.
function insertAt(parent, el, index) {
  const ref = [...(parent.children ?? [])].filter((c) => c !== el)[index] ?? null;
  parent.insertBefore(el, ref);
}

// The slot a card dropped at `clientX` lands in among a hand strip's cards — one past every card
// whose centre the pointer has crossed. The dragged card is skipped so the index is relative to the
// others, matching the server's reorder (which removes the card before inserting at the slot).
export function handDropIndex(handEl, clientX, draggedId) {
  let index = 0;
  for (const cardEl of handEl.children ?? []) {
    const id = cardEl.dataset?.cardId;
    if (!id || id === draggedId) continue; // skip the gap placeholder and the dragged card itself
    const rect = cardEl.getBoundingClientRect();
    if (clientX < rect.left + rect.width / 2) break;
    index += 1;
  }
  return index;
}

// MOVE_CARD destinations for the "Send to…" menu items and the deck-search deal buttons.
const handDest = (owner) => ({ kind: 'zone', zone: { owner, role: 'hand', idx: null } });
export const discardDest = (owner, side) => ({
  kind: 'zone',
  zone: { owner, role: side === 'FATE' ? 'fate_discard' : 'dynasty_discard', idx: null },
});
export const deckDest = (owner, side) => ({ kind: 'deck', deck: { owner, side } });

const SEP = { separator: true };

// The card branch of the menu. Items come from the clicked card's dataset: "Flip" turns a card to its
// other side — the other face of a double-faced card, or front↔deck-back for any other; a face-down
// card offers reveal/hide instead of a bow toggle it cannot evaluate; and "Send to…" appears only on a
// card the viewer owns. Every action applies to `targetIds` — the whole selection when the clicked card
// is part of one, else the clicked card alone. Flag ops go as a single batch intent; Send to…/Remove
// fan out one message per card, each routed by that card's own owner and side (`lookup` resolves a
// selected id to its dataset; the clicked card uses its own). The server re-checks every gate.
function cardMenuItems(el, viewer, targetIds = [el.dataset.cardId], lookup = () => null) {
  const id = el.dataset.cardId;
  const side = el.dataset.side || '';
  const owner = el.dataset.owner || '';
  const faceDown = isFaceDown(el);
  const shown = el.dataset.shown === '1';
  const peeked = el.dataset.peeked === '1';
  const bowed = el.dataset.bowed === '1';
  const doubleFaced = el.dataset.doubleFaced === '1';
  const inProvince = !!el.closest?.('[data-zone="province"]');
  const inHand = !!el.closest?.('[data-zone="hand"]');
  const inDiscard = !!el.closest?.('[data-zone="discard"]');
  const mine = owner === '' || owner === viewer;

  const dataFor = (cardId) => (cardId === id ? el.dataset : lookup(cardId) ?? el.dataset);
  // Send `build(id, dataset)` for each selected card, skipping any the builder declines (returns null).
  const fanOut = (send, build) => {
    for (const cardId of targetIds) {
      const message = build(cardId, dataFor(cardId));
      if (message) send(message);
    }
  };

  const items = [];
  // Append a separator-led group, but only when it has items and something precedes it — so the menu
  // never opens with a stray separator or doubles one up.
  const pushGroup = (group) => {
    if (!group.length) return;
    if (items.length) items.push(SEP);
    items.push(...group);
  };

  // View is a local zoom of whatever face the card shows, available on any card the viewer can see.
  items.push({ label: '&View', onClick: () => viewCard(el) });

  // Flip, Bow, and Invert manipulate a card in play; a card in hand is played, not turned in place.
  if (!inHand) {
    items.push({ label: '&Flip', message: flipIntentFor(doubleFaced, targetIds) });
    // Bowing a card sitting in a province is meaningless, matching the desktop client's gate.
    if (!inProvince) {
      items.push({ label: bowed ? 'Un&bow' : '&Bow', message: bowIntent(targetIds, bowed) });
    }
    items.push({ label: '&Invert', message: invertIntent(targetIds) });
  }
  // Show reveals to the opponent a card they cannot already see — one in your hand or lying face-down.
  // A face-up card on the shared board is already visible, so it only offers the toggle-off once shown.
  if (mine) {
    if (shown) items.push({ label: 'Stop &showing', message: unshowIntent(id) });
    else if (inHand || faceDown) items.push({ label: '&Show opponent', message: showIntent(id) });
  }
  // Peek is open to anyone, on a card the viewer cannot yet see, toggling to "Stop peeking" once they
  // can. Show and Peek carry the clicked card's single id, not the batch.
  if (peeked) items.push({ label: 'Stop &peeking', message: unpeekIntent(id) });
  else if (faceDown) items.push({ label: '&Peek', message: peekIntent(id) });

  if (mine) {
    const seatOf = (d) => d.owner || viewer;
    const sendItems = [];
    // Only fate cards live in a hand, and a card already there is never routed back to it.
    if (side === 'FATE' && !inHand) {
      sendItems.push({
        label: 'Send to &Hand',
        onClick: (e, send) => fanOut(send, (cid, d) => moveCardIntent(cid, handDest(seatOf(d)))),
      });
    }
    if (side) {
      // A card already in a discard pile has nowhere to be discarded to.
      if (!inDiscard) {
        sendItems.push({
          label: 'Send to &Discard',
          onClick: (e, send) =>
            fanOut(send, (cid, d) => d.side && moveCardIntent(cid, discardDest(seatOf(d), d.side))),
        });
      }
      sendItems.push(
        {
          label: 'Send to Deck (&top)',
          onClick: (e, send) =>
            fanOut(send, (cid, d) => d.side && moveCardIntent(cid, deckDest(seatOf(d), d.side))),
        },
        {
          label: 'Send to Deck (b&ottom)',
          onClick: (e, send) =>
            fanOut(send, (cid, d) => d.side && moveCardIntent(cid, deckDest(seatOf(d), d.side), null, true)),
        },
      );
    }
    pushGroup(sendItems);
  }
  // Only tokens can be removed: a real card from a deck/zone belongs to the game state, not the table.
  if (el.dataset.token === '1') {
    pushGroup([{ label: '&Remove', onClick: (e, send) => fanOut(send, (cid) => removeMessage(cid)) }]);
  }
  return items;
}

// The deck branch of the menu: draw, shuffle, reveal the top card in place, search the deck (a centered
// chooser picks the top N or the whole deck), and spin up a fresh province. Only the deck's owner may
// act, so a non-owner gets no menu. Search sends SEARCH_DECK — the only message that reveals deck
// order, and only to the owner — opening the deck dialog on the server's DECK_CONTENTS reply.
function deckMenuItems(el, viewer) {
  const owner = el.dataset.owner;
  const side = el.dataset.side;
  if (owner !== viewer) return [];
  // Shuffle takes its second letter so Draw and Search keep the D/S keys their bare hover hotkeys use.
  return [
    { label: '&Draw', message: drawIntent(owner, side) },
    { label: 'S&huffle', message: shuffleIntent(owner, side) },
    { label: '&Flip Top', message: flipDeckTopIntent(owner, side) },
    { label: '&Search…', onClick: (e, send) => openDeckSearchPrompt(owner, side, send) },
    SEP,
    { label: '&Create Province', message: createProvinceIntent() },
  ];
}

// The province branch: fill an empty province from the dynasty deck, or discard/destroy the province.
// When the slot holds a card the card's own menu opens instead, with these appended after a separator.
function provinceMenuItems(owner, idx, viewer) {
  if (owner !== viewer) return [];
  // Standalone, Fill and Discard take F and D; Destroy falls to E since Discard already took D.
  // Appended to a card's menu, the resolver shifts any that collide with the card's keys.
  return [
    { label: '&Fill', message: fillProvinceIntent(owner, idx) },
    { label: '&Discard', message: discardProvinceIntent(owner, idx) },
    { label: '&Destroy', message: destroyProvinceIntent(owner, idx) },
  ];
}

// Card footprint, matching --card-w/--card-h in play.css.
const CARD_W = 81;
const CARD_H = 115;
const DRAG_SEND_MS = 40;

const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

// Top-left position for a card being dragged, in battlefield-local coordinates, clamped so the card
// stays fully on the board. `grab` is the pointer's offset within the card at grab time.
export function dragPosition(clientX, clientY, boardRect, grab, card = { w: CARD_W, h: CARD_H }) {
  return {
    x: Math.round(clamp(clientX - boardRect.left - grab.x, 0, boardRect.width - card.w)),
    y: Math.round(clamp(clientY - boardRect.top - grab.y, 0, boardRect.height - card.h)),
  };
}

// The position to render a drag at, which leaves the bottom edge un-clamped so a card can be dragged
// down off the board toward the hand strip below it (the board's overflow clips the overhang, so it
// reads as the card tucking under the hand). A committed board drop still uses dragPosition, so a
// card released on the board never rests partly under the hand.
export function dragVisualPosition(clientX, clientY, boardRect, grab) {
  return {
    x: Math.round(clamp(clientX - boardRect.left - grab.x, 0, boardRect.width - CARD_W)),
    y: Math.round(Math.max(0, clientY - boardRect.top - grab.y)),
  };
}

// A normalized rectangle (top-left + size) spanning two battlefield-local corner points.
const rectBetween = (sx, sy, cx, cy) => ({
  x: Math.min(sx, cx),
  y: Math.min(sy, cy),
  w: Math.abs(cx - sx),
  h: Math.abs(cy - sy),
});

// Does a card footprint at (x, y) overlap the rectangle `r`?
const cardInRect = (r, x, y) =>
  x < r.x + r.w && x + CARD_W > r.x && y < r.y + r.h && y + CARD_H > r.y;

// Horizontal step between an owner's fanned-out loose battlefield cards, and the vertical gap a
// deck-anchored card leaves between itself and its deck, both in pixels.
const PREGAME_FAN = 20;
const PREGAME_DECK_GAP = 10;
// Successive hand cards played by double-click fan across this many slots before wrapping, so a flurry
// of plays spreads out instead of stacking yet never marches off the board.
const HAND_PLAY_FAN_SLOTS = 8;
// Fraction of the board height at which a double-clicked hand card lands — into the viewer's half,
// high enough above the bottom edge to clear the provinces that line it.
const HAND_PLAY_ROW = 0.6;

// Battlefield-local top-left next to a seat's `side` deck (FATE or DYNASTY), or null if the tableau is
// not laid out yet. The cards sit just inboard of the deck — above it for the bottom (viewer) seat,
// below it for the top seat — so they read as "by the deck" without covering it.
export function deckAnchor(tableau, battlefield, above, side) {
  const deckEl = tableau?.querySelector?.(`.pile.deck[data-side="${side}"]`);
  if (!deckEl) return null;
  const d = deckEl.getBoundingClientRect();
  const b = battlefield.getBoundingClientRect();
  const deckY = d.top - b.top;
  return {
    x: d.left - b.left,
    y: above ? deckY - CARD_H - PREGAME_DECK_GAP : deckY + CARD_H + PREGAME_DECK_GAP,
  };
}

// Battlefield-local top-left for a seat's loose pre-game permanents (stronghold/sensei/wind): one card
// width inboard of the dynasty discard so they start toward the centre of the play area, kept clear of
// the discard row by the same gap as a deck-anchored card — above it for the bottom (viewer) seat,
// below it for the top seat. Null if the tableau is not laid out yet.
export function pregameAnchor(tableau, battlefield, above) {
  const discardEl = tableau?.querySelector?.('.pile[data-role="dynasty_discard"]');
  if (!discardEl) return null;
  const d = discardEl.getBoundingClientRect();
  const b = battlefield.getBoundingClientRect();
  const discardY = d.top - b.top;
  return {
    x: d.left - b.left + CARD_W,
    y: above ? discardY - CARD_H - PREGAME_DECK_GAP : discardY + CARD_H + PREGAME_DECK_GAP,
  };
}

// Give each unplaced battlefield card (server x < 0 — a pre-game permanent, an overflow dynasty draw,
// or a card pulled from a deck search) a fanned-out position in one of three groups: a pre-game
// permanent (any side) starts by the dynasty discard with the others; otherwise a fate card anchors
// to the fate deck and a dynasty card to the dynasty deck. Cards already placed (x >= 0) keep their
// server position. `anchorFor(owner, isViewer, group)` returns that group's anchor or null. Each group
// fans toward the centre of the board — rightward off the left-hung dynasty side, leftward off the
// right-hung fate deck — so a growing stack stays on the play space instead of running off the edge.
// The groups fan independently so they don't overlap. Returns a new array.
export function placeUnplacedCards(cards, viewerSeat, anchorFor) {
  const placedPerStack = {};
  return cards.map((card) => {
    if (card.x >= 0) return card;
    const group = card.pregame ? 'PREGAME' : card.side === 'FATE' ? 'FATE' : 'DYNASTY';
    const anchor = anchorFor(card.owner, card.owner === viewerSeat, group);
    if (!anchor) return card;
    const stack = `${card.owner}:${group}`;
    const index = placedPerStack[stack] ?? 0;
    placedPerStack[stack] = index + 1;
    const step = group === 'FATE' ? -PREGAME_FAN : PREGAME_FAN;
    return { ...card, x: anchor.x + index * step, y: anchor.y };
  });
}

let activeMenu = null;
let menuKeyHandler = null;
let activeCardView = null;

function closeMenu() {
  if (menuKeyHandler) {
    document.removeEventListener?.('keydown', menuKeyHandler);
    menuKeyHandler = null;
  }
  activeMenu?.remove();
  activeMenu = null;
}

// Float a card-sized preview of the card's current face next to it on the board. The preview is
// non-modal — pointer-transparent and dismissed by the next key or pointer action anywhere — so it
// never blocks play. Viewing reads only what the card already renders, so it shows a face-down
// card's back, never its hidden front.
function viewCard(cardEl) {
  const face = cardEl?.querySelector?.('img');
  if (!face?.src) return;
  closeCardView();
  const room = document.querySelector('.room') ?? document.body;
  const preview = node('img', 'card-view');
  preview.src = face.src;
  preview.alt = face.alt ?? '';
  room.appendChild(preview);
  placeCardView(preview, cardEl, room);

  // Identity-guard the dismiss: a stale listener from a superseded preview must not close the
  // current one. Re-pressing V over another card replaces the preview rather than closing it.
  const token = {};
  const dismiss = () => {
    if (activeCardView?.token === token) closeCardView();
  };
  document.addEventListener?.('keydown', dismiss, { capture: true });
  document.addEventListener?.('pointerdown', dismiss, { capture: true });
  activeCardView = { preview, token, dismiss };
}

// Place the preview beside the card, flipping to its left side when it would overflow the room's
// right edge and clamping to stay fully on screen. Coordinates are room-local, matching the menu.
function placeCardView(preview, cardEl, room) {
  const cardRect = cardEl.getBoundingClientRect();
  const roomRect = room.getBoundingClientRect();
  // Measure the layout box, not getBoundingClientRect: the open animation scales the preview, and a
  // transformed rect would under-report its size so the clamp reserves too little and it spills off.
  const previewW = preview.offsetWidth;
  const previewH = preview.offsetHeight;
  const gap = 10;
  let left = cardRect.right - roomRect.left + gap;
  if (left + previewW > roomRect.width) left = cardRect.left - roomRect.left - gap - previewW;
  const top = cardRect.top - roomRect.top + cardRect.height / 2 - previewH / 2;
  const placed = clampMenuPosition(left, top, previewW, previewH, roomRect.width, roomRect.height);
  preview.style.left = `${placed.left}px`;
  preview.style.top = `${placed.top}px`;
}

function closeCardView() {
  if (!activeCardView) return;
  const { preview, dismiss } = activeCardView;
  document.removeEventListener?.('keydown', dismiss, { capture: true });
  document.removeEventListener?.('pointerdown', dismiss, { capture: true });
  activeCardView = null;
  preview.classList.add('closing');
  let timer;
  const drop = () => {
    clearTimeout(timer);
    preview.remove();
  };
  preview.addEventListener('transitionend', drop, { once: true });
  timer = setTimeout(drop, 250); // fall back if the fade-out transition never fires
}

// Split a label's "&" mnemonic into the clean display text and the preferred accelerator: the letter
// after the "&", at that position. No "&" means no preference (the first free letter is used instead).
function parseMnemonic(label) {
  const amp = label.indexOf('&');
  if (amp < 0 || amp === label.length - 1) return { text: label, key: null, at: -1 };
  const text = label.slice(0, amp) + label.slice(amp + 1);
  return { text, key: text[amp].toLowerCase(), at: amp };
}

// Give each item a unique single-key accelerator: its mnemonic letter when still free, else the first
// free letter of its label. Returns the display text and the underlined position alongside each item,
// so a combined menu (a province card's actions plus the province's own) never doubles up a key.
function assignAccelerators(items) {
  const used = new Set();
  return items.map((item) => {
    if (item.separator) return { item };
    const { text, key, at } = parseMnemonic(item.label);
    if (key && !used.has(key)) {
      used.add(key);
      return { item, text, key, at };
    }
    for (let i = 0; i < text.length; i++) {
      const ch = text[i].toLowerCase();
      if (ch >= 'a' && ch <= 'z' && !used.has(ch)) {
        used.add(ch);
        return { item, text, key: ch, at: i };
      }
    }
    return { item, text, key: null, at: -1 };
  });
}

// Container-local top-left for the menu, pulled back from any right/bottom edge it would overflow so
// the whole menu stays on screen; never pushed past the top/left. `margin` holds it off the edge.
export function clampMenuPosition(left, top, menuW, menuH, containerW, containerH, margin = 4) {
  return {
    left: Math.max(margin, Math.min(left, containerW - menuW - margin)),
    top: Math.max(margin, Math.min(top, containerH - menuH - margin)),
  };
}

// Open the context menu at the click point with a prebuilt item list. Each item is a separator, a
// `{label, message}` (clicking sends the message), or a `{label, onClick}` (clicking runs the handler
// with the click event, `send`, and the container — used to open a flyout). The menu mounts on
// `container` — the whole board stage, not the battlefield, whose `overflow: hidden` would clip it and
// whose stacking layer sits below the hand strip — then clampMenuPosition shifts it to stay on screen.
function openMenu(container, items, clientX, clientY, send) {
  closeMenu();
  const rect = container.getBoundingClientRect();
  const menu = document.createElement('ul');
  menu.className = 'board-menu';

  const trigger = (item, e) => {
    closeMenu();
    if (item.onClick) item.onClick(e, send, container);
    else send(item.message);
  };
  const byKey = new Map();

  for (const { item, text, key, at } of assignAccelerators(items)) {
    const li = document.createElement('li');
    if (item.separator) {
      li.className = 'menu-sep';
    } else {
      if (at >= 0) {
        if (at > 0) li.appendChild(node('span', null, text.slice(0, at)));
        li.appendChild(node('span', 'menu-key', text[at]));
        if (at + 1 < text.length) li.appendChild(node('span', null, text.slice(at + 1)));
      } else {
        li.textContent = text;
      }
      li.addEventListener('click', (e) => trigger(item, e));
      if (key) byKey.set(key, item);
    }
    menu.appendChild(li);
  }

  // A single key fires its underlined item; Escape dismisses. Accelerators reach even the "destructive"
  // actions, but only once the menu is open — they are never bare hover hotkeys.
  menuKeyHandler = (e) => {
    if (e.key === 'Escape') return closeMenu();
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const item = byKey.get(e.key.toLowerCase());
    if (!item) return;
    e.preventDefault();
    trigger(item, e);
  };
  document.addEventListener?.('keydown', menuKeyHandler);

  container.appendChild(menu);
  const menuRect = menu.getBoundingClientRect();
  const { left, top } = clampMenuPosition(
    clientX - rect.left,
    clientY - rect.top,
    menuRect.width,
    menuRect.height,
    rect.width,
    rect.height,
  );
  menu.style.left = `${left}px`;
  menu.style.top = `${top}px`;
  activeMenu = menu;
  // Defer so the contextmenu's own pointer event doesn't close the menu we just opened.
  setTimeout(() => {
    document.addEventListener(
      'pointerdown',
      (e) => {
        if (!menu.contains(e.target)) closeMenu();
      },
      { once: true },
    );
  }, 0);
}

// The deck-menu "Search…" prompt: a centered chooser for how much of the deck to reveal — the top N
// (typed) or all of it. Both send a SEARCH_DECK whose `value` carries the top-N count (null for the
// whole deck); the server logs it and caps the dialog its DECK_CONTENTS reply opens. Mounts inside
// `.room` for the board palette, and closes on a choice, the backdrop, the × button, or Escape.
function openDeckSearchPrompt(owner, side, send) {
  const overlay = node('div', 'deck-dialog-overlay');
  const modal = node('div', 'deck-scope');

  const close = () => {
    document.removeEventListener?.('keydown', onKey);
    overlay.remove();
  };
  const onKey = (e) => {
    if (e.key === 'Escape') close();
  };
  const choose = (value) => {
    send(searchDeckIntent(owner, side, value));
    close();
  };

  const closeBtn = node('button', 'deck-dialog-close', '×');
  closeBtn.type = 'button';
  closeBtn.title = 'Close';
  closeBtn.addEventListener('click', close);
  const header = node('div', 'deck-dialog-header');
  header.append(node('h2', 'deck-dialog-title', 'Search deck'), closeBtn);

  const input = node('input', 'deck-scope-input');
  input.type = 'number';
  input.min = '1';
  input.placeholder = 'N';
  const searchTop = () => {
    const n = Number.parseInt(input.value, 10);
    if (n > 0) choose(n);
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') searchTop();
  });
  const topBtn = node('button', 'deck-scope-btn', 'Search top N');
  topBtn.type = 'button';
  topBtn.addEventListener('click', searchTop);
  const topRow = node('div', 'deck-scope-row');
  topRow.append(input, topBtn);

  const whole = node('button', 'deck-scope-btn', 'Whole deck');
  whole.type = 'button';
  whole.addEventListener('click', () => choose(null));

  modal.append(header, topRow, whole);
  overlay.append(modal);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });
  (document.querySelector('.room') ?? document.body).appendChild(overlay);
  document.addEventListener?.('keydown', onKey);
  input.focus?.();
}

// Choose the menu for a right-click: a deck pile shows deck actions (even though its top card carries
// a card id); an occupied province shows the card's menu plus the province lifecycle ops; an empty
// province shows just those ops; any other card shows the card menu. Returns [] for an empty target.
function menuItemsFor(target, viewer, targetIds, lookup) {
  const zoneEl = target?.closest?.('[data-zone]');
  const zone = zoneEl?.dataset.zone;
  const cardEl = target?.closest?.('[data-card-id]');
  if (zone === 'deck') return deckMenuItems(zoneEl, viewer);
  if (zone === 'province') {
    const province = provinceMenuItems(zoneEl.dataset.owner, Number(zoneEl.dataset.idx), viewer);
    if (!cardEl) return province;
    const card = cardMenuItems(cardEl, viewer, targetIds, lookup);
    return province.length ? [...card, SEP, ...province] : card;
  }
  if (cardEl) return cardMenuItems(cardEl, viewer, targetIds, lookup);
  return [];
}

// A pointer-following clone shown while dragging a source that stays put in its zone (a deck top, or
// a hand/province card). It mirrors the card's current face — front art when face-up, the generic
// back when face-down — and its orientation, so the player drags a faithful image of what they are
// moving rather than a blank placeholder.
function dragGhost(sourceEl) {
  const ghost = node('div', 'board-card dragging');
  ghost.style.pointerEvents = 'none';
  for (const cls of ['face-down', 'bowed', 'inverted']) {
    if (sourceEl.classList.contains(cls)) ghost.classList.add(cls);
  }
  const face = sourceEl.querySelector('img');
  if (face) {
    const ghostFace = node('img');
    ghostFace.src = face.src;
    ghostFace.alt = '';
    ghost.appendChild(ghostFace);
  } else {
    ghost.classList.add('face-down');
  }
  return ghost;
}

// Wire dragging, selection, and the right-click menu once on the table `root` (which spans the
// battlefield and every seat zone), so delegation survives the full re-render each SNAPSHOT does.
// A card can be picked up anywhere and dropped on any zone: a drop on the battlefield repositions
// (SET_CARD_POS) or plays a card there, a drop on another zone is a MOVE_CARD. Clicking a
// battlefield card selects it; Ctrl/Cmd-click toggles it in a multi-selection; a marquee dragged
// across empty table picks every card it covers; dragging a card that is part of a multi-selection
// moves the whole group together. `boardEl` is the battlefield, used for position maths; `send`
// receives a room-less client message. Returns `{ markSelection }` so the caller can re-apply the
// selection outline after the board re-renders.
export function initBoardInteractions(root, boardEl, send) {
  let drag = null;
  let marquee = null;
  let lastSent = 0;
  // The element last under the pointer, so a hover-driven hotkey knows which card/deck it targets.
  let hovered = null;
  // The viewer's hand strip while a draggable card hovers it, glowing as a drop target.
  let handTarget = null;
  const setHandTarget = (el) => {
    if (handTarget === el) return;
    handTarget?.classList.remove('drop-active');
    handTarget = el;
    handTarget?.classList.add('drop-active');
  };
  // Counts hand cards played by double-click, to fan each across the board instead of stacking them.
  let handPlays = 0;
  // Selection is keyed by card id so it survives the element churn of each SNAPSHOT re-render.
  const selected = new Set();
  const battleRect = () => boardEl.getBoundingClientRect();
  // Battlefield-local top-left of a card element, read from its inline position.
  const cardX = (el) => parseFloat(el.style.left) || 0;
  const cardY = (el) => parseFloat(el.style.top) || 0;
  // The viewer may only move cards they own; a card with no owner (neutral/token) is everyone's. The
  // gate lives at the source so an opponent's card never mutates locally ahead of the server reject.
  const ownsCard = (el) => {
    const owner = el?.dataset?.owner || '';
    return !owner || owner === (root.dataset.viewerSeat || '');
  };
  // An owned zone (a deck or a hand) always has an owner, so — unlike a card — ownerless never shares.
  const ownsZone = (el) => el.dataset.owner === (root.dataset.viewerSeat || '');
  // Id of the topmost battlefield card (last in render/z order), or null when the board is empty.
  const topmostId = () => {
    const cards = boardEl.querySelectorAll('.board-card');
    return cards.length ? cards[cards.length - 1].dataset.cardId : null;
  };
  // A group-drag member's clamped position after shifting its origin by the pointer delta.
  const memberPos = (member, dx, dy, rect) => ({
    x: clamp(Math.round(member.originX + dx), 0, rect.width - CARD_W),
    y: clamp(Math.round(member.originY + dy), 0, rect.height - CARD_H),
  });

  // Paint the `.selected` outline onto the battlefield cards in the current selection. Idempotent,
  // so the caller re-runs it after every re-render to reattach the outline to the fresh elements.
  const markSelection = () => {
    for (const el of boardEl.querySelectorAll('.board-card')) {
      el.classList.toggle('selected', selected.has(el.dataset.cardId));
    }
  };

  // End the drag and clear its visuals. A committed ghost move keeps its hidden source hidden: the
  // card has "left", and the incoming SNAPSHOT rebuilds the source zone, so restoring it here would
  // only flash the card back in place for the server round-trip. Cancels and no-op drops restore it.
  const release = (restoreSource = true) => {
    setHandTarget(null);
    boardEl.classList.remove('is-dragging');
    if (!drag) return;
    drag.handGap?.remove(); // the incoming-card gap placeholder, if any
    // Return a re-arranged hand card to its home slot; the SNAPSHOT after a committed reorder/move
    // re-renders the hand anyway, so this only matters for an abandoned drag.
    if (drag.handParent) insertAt(drag.handParent, drag.el, drag.handHome);
    drag.el.style.pointerEvents = '';
    if (restoreSource) drag.el.style.visibility = '';
    drag.el.classList.remove('dragging');
    drag.ghost?.remove();
    drag = null;
  };

  const dropMarquee = () => {
    marquee?.box?.remove();
    marquee = null;
  };

  root.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    // A press that starts on a deck pile grabs that deck's hidden top card (no card id to move by);
    // only the deck's owner may, and the drop resolves to a MOVE_DECK_TOP keyed by the deck.
    const deckEl = e.target?.closest?.('[data-zone="deck"]');
    if (deckEl) {
      if (!ownsZone(deckEl)) return;
      const rect = deckEl.getBoundingClientRect();
      drag = {
        deck: { owner: deckEl.dataset.owner, side: deckEl.dataset.side },
        el: deckEl,
        onBattlefield: false,
        grab: { x: e.clientX - rect.left, y: e.clientY - rect.top },
        moved: false,
        canEnterHand: deckEl.dataset.side === 'FATE',
      };
      return;
    }
    const cardEl = e.target?.closest?.('[data-card-id]');
    if (!cardEl) {
      // A press on the open table (not a real drop zone) starts a marquee and, on release without a
      // drag, clears the selection.
      const zoneEl = e.target?.closest?.('[data-zone]');
      if (zoneEl && zoneEl.dataset.zone !== 'battlefield') return;
      const rect = battleRect();
      marquee = {
        startX: e.clientX - rect.left,
        startY: e.clientY - rect.top,
        moved: false,
        box: null,
      };
      return;
    }
    // Block a drag (and therefore any move) on a card the viewer does not own, at the source.
    if (!ownsCard(cardEl)) return;
    const rect = cardEl.getBoundingClientRect();
    const id = cardEl.dataset.cardId;
    const onBattlefield = cardEl.classList.contains('board-card');
    drag = {
      id,
      el: cardEl,
      onBattlefield,
      grab: { x: e.clientX - rect.left, y: e.clientY - rect.top },
      moved: false,
      additive: e.ctrlKey || e.metaKey,
      // Only fate cards live in a hand, so only they cross its boundary; others bump against it.
      canEnterHand: cardEl.dataset.side === 'FATE',
      fromHand: !!cardEl.closest?.('[data-zone="hand"]'),
    };
    // Remember a hand card's home slot so its gap can slide as it's re-arranged and snap back if the
    // drag is abandoned.
    if (drag.fromHand) {
      drag.handParent = cardEl.parentNode;
      drag.handHome = [...(cardEl.parentNode?.children ?? [])].indexOf(cardEl);
    }
    // Grabbing a card that is already part of a multi-selection drags the whole group by one delta.
    if (onBattlefield && selected.size > 1 && selected.has(id)) {
      drag.startX = e.clientX;
      drag.startY = e.clientY;
      drag.members = [];
      for (const el of boardEl.querySelectorAll('.board-card')) {
        // A marquee can sweep an opponent's card into the selection; never move one in a group drag.
        if (selected.has(el.dataset.cardId) && ownsCard(el)) {
          drag.members.push({ id: el.dataset.cardId, el, originX: cardX(el), originY: cardY(el) });
        }
      }
    }
  });

  root.addEventListener('pointermove', (e) => {
    hovered = e.target;
    if (marquee) {
      marquee.moved = true;
      const rect = battleRect();
      const cx = clamp(e.clientX - rect.left, 0, rect.width);
      const cy = clamp(e.clientY - rect.top, 0, rect.height);
      const box = rectBetween(marquee.startX, marquee.startY, cx, cy);
      if (!marquee.box) {
        marquee.box = node('div', 'marquee');
        boardEl.appendChild(marquee.box);
      }
      marquee.box.style.left = `${box.x}px`;
      marquee.box.style.top = `${box.y}px`;
      marquee.box.style.width = `${box.w}px`;
      marquee.box.style.height = `${box.h}px`;
      return;
    }
    if (!drag) return;
    // Glow the viewer's own hand when a card that can enter it is dragged over, as a drop target.
    const handUnder = drag.members || !drag.canEnterHand ? null : e.target?.closest?.('[data-zone="hand"]');
    setHandTarget(handUnder && ownsZone(handUnder) ? handUnder : null);
    // Over the hand, open a gap at the slot the card will land in so the others make room: a card
    // already in the hand slides its own hidden source there; an incoming card opens a placeholder.
    if (drag.canEnterHand && handTarget) {
      const index = handDropIndex(handTarget, e.clientX, drag.id);
      if (index !== drag.handIndex) {
        drag.handIndex = index;
        if (drag.fromHand) {
          insertAt(handTarget, drag.el, index);
        } else {
          drag.handGap ??= node('div', 'hand-gap');
          insertAt(handTarget, drag.handGap, index);
        }
      }
    }
    // On the first real move, pick the element that will follow the pointer (`drag.mover`) and lift it
    // so the drop lands on the zone beneath. A deck top or a card resting in a zone stays put while a
    // face-mirroring ghost moves instead; a battlefield card moves itself. Stop clipping the board so
    // the mover can cross the bottom edge into the hand strip below.
    if (!drag.moved) {
      drag.moved = true;
      boardEl.classList.add('is-dragging');
      if (drag.deck || !drag.onBattlefield) {
        drag.ghost = dragGhost(drag.el);
        boardEl.appendChild(drag.ghost);
        if (!drag.deck) drag.el.style.visibility = 'hidden'; // hide the source so the ghost is the card
        drag.mover = drag.ghost;
      } else {
        drag.el.style.pointerEvents = 'none';
        drag.el.classList.add('dragging');
        drag.mover = drag.el;
      }
    }
    if (drag.members) {
      const rect = battleRect();
      const dx = e.clientX - drag.startX;
      const dy = e.clientY - drag.startY;
      const now = Date.now();
      const flush = now - lastSent > DRAG_SEND_MS;
      const moves = flush ? [] : null;
      for (const member of drag.members) {
        const { x, y } = memberPos(member, dx, dy, rect);
        member.el.style.left = `${x}px`;
        member.el.style.top = `${y}px`;
        moves?.push({ id: member.id, x, y });
      }
      if (flush) {
        send(moveGroupIntent(moves));
        lastSent = now;
      }
      return;
    }
    // Move the mover locally and commit only on drop, never streaming each step. Streaming would echo
    // back a SNAPSHOT that re-renders the card at its clamped board position, snapping it back from the
    // hand it was crossing into. The drop sends the final move. A card that cannot enter the hand stays
    // clamped to the board, so it bumps against the hand's edge instead of crossing it.
    const place = drag.canEnterHand ? dragVisualPosition : dragPosition;
    const pos = place(e.clientX, e.clientY, battleRect(), drag.grab);
    drag.mover.style.left = `${pos.x}px`;
    drag.mover.style.top = `${pos.y}px`;
  });

  root.addEventListener('pointerup', (e) => {
    if (marquee) {
      const rect = battleRect();
      if (marquee.moved) {
        const cx = clamp(e.clientX - rect.left, 0, rect.width);
        const cy = clamp(e.clientY - rect.top, 0, rect.height);
        const box = rectBetween(marquee.startX, marquee.startY, cx, cy);
        selected.clear();
        for (const el of boardEl.querySelectorAll('.board-card')) {
          if (cardInRect(box, cardX(el), cardY(el))) selected.add(el.dataset.cardId);
        }
      } else {
        selected.clear();
      }
      markSelection();
      dropMarquee();
      return;
    }
    if (!drag) return;
    const card = drag;
    const target = e.target?.closest?.('[data-zone]');
    const zone = target?.dataset.zone;
    // The hand only accepts a card that can live there; a barriered card has no hand destination.
    const dropsInHand = zone === 'hand' && card.canEnterHand;
    const dest = zone && zone !== 'battlefield' && (zone !== 'hand' || dropsInHand) ? zoneDest(target) : null;
    // The clamped board position to land on, computed lazily so a drop that needs no coordinates
    // (a card sent to a zone, a deck top onto a pile) skips the layout read.
    const dropPos = () => dragPosition(e.clientX, e.clientY, battleRect(), card.grab);
    // A ghost-moved source (a hidden hand/province/discard card) stays hidden when the drop actually
    // commits a move — the SNAPSHOT will rebuild its zone — and reappears on a no-op drop or cancel.
    const commitsGhostMove =
      card.moved && !card.onBattlefield && !card.deck && (zone === 'battlefield' || !!dest);
    release(!commitsGhostMove);
    // A press that never moved is a click: (de)select the card rather than treating it as a drop.
    if (!card.moved && card.onBattlefield) {
      if (card.additive) {
        if (selected.has(card.id)) selected.delete(card.id);
        else selected.add(card.id);
      } else {
        selected.clear();
        selected.add(card.id);
      }
      markSelection();
      // Persist the raise a pure selection implies — only for the viewer's own card and only when it
      // is not already on top. A drag instead raises via the SET_CARD_POS it sends, so don't double up.
      if (selected.has(card.id) && !card.members && ownsCard(card.el) && topmostId() !== card.id) {
        send(raiseIntent(card.id));
      }
    }
    if (card.deck) {
      // A deck-top drag fires only on a real move, resolving the drop the same way a card move does.
      if (card.moved) {
        let to = null;
        let position = null;
        if (zone === 'battlefield') {
          const pos = dropPos();
          to = { kind: 'battlefield' };
          position = [pos.x, pos.y];
        } else if (zone) {
          to = zoneDest(target);
        }
        if (to) send(moveDeckTopIntent(card.deck, to, position));
      }
    } else if (card.members) {
      const rect = battleRect();
      const dx = e.clientX - card.startX;
      const dy = e.clientY - card.startY;
      const moves = card.members.map((member) => {
        const { x, y } = memberPos(member, dx, dy, rect);
        return { id: member.id, x, y };
      });
      send(moveGroupIntent(moves));
    } else if (zone === 'battlefield' || (card.onBattlefield && !dest)) {
      // A battlefield card re-sends its position when it actually moved (the raise above covers a pure
      // selection), including when it's dropped on a zone it cannot enter, so it settles on the board
      // rather than vanishing; a card played from elsewhere lands on the board even without a drag.
      if (card.onBattlefield) {
        if (card.moved) {
          const pos = dropPos();
          send(moveIntent(card.id, pos.x, pos.y));
        }
      } else {
        const pos = dropPos();
        send(moveCardIntent(card.id, { kind: 'battlefield' }, [pos.x, pos.y]));
      }
    } else if (dropsInHand) {
      // Land the card at the slot the gap previewed: reorder a card already in the hand, or move an
      // incoming one straight into that slot (the server no-ops a move onto a zone it already holds).
      const index = card.handIndex ?? handDropIndex(target, e.clientX, card.id);
      if (card.fromHand) send(reorderHandIntent(card.id, index));
      else send(moveCardIntent(card.id, dest, null, false, index));
    } else if (dest) {
      send(moveCardIntent(card.id, dest));
    }
  });

  root.addEventListener('pointercancel', () => {
    release();
    dropMarquee();
  });

  // A pointer released or cancelled outside the table never reaches the handlers above; this net
  // restores a dragged card to hit-testing and drops any in-flight marquee so nothing gets stuck.
  if (typeof window !== 'undefined' && window.addEventListener) {
    const reset = () => {
      release();
      dropMarquee();
    };
    window.addEventListener('pointerup', reset);
    window.addEventListener('pointercancel', reset);
  }

  root.addEventListener('contextmenu', (e) => {
    // Right-clicking a card that is part of a multi-selection targets the whole selection;
    // otherwise the menu defaults to just the clicked card.
    const id = e.target?.closest?.('[data-card-id]')?.dataset.cardId;
    const targetIds = id && selected.size > 1 && selected.has(id) ? [...selected] : undefined;
    // Resolve a selected card id to its dataset so per-card Send to…/Remove route by each card's side.
    const datasets = [...boardEl.querySelectorAll('.board-card')].map((cardEl) => cardEl.dataset);
    const lookup = (cardId) => datasets.find((d) => d.cardId === cardId) ?? null;
    const items = menuItemsFor(e.target, root.dataset.viewerSeat || '', targetIds, lookup);
    if (!items.length) return;
    e.preventDefault();
    openMenu(root, items, e.clientX, e.clientY, send);
  });

  // Double-click shortcuts on the viewer's own cards/decks. A face-up card in a province is left
  // alone — bowing one there is meaningless, matching the menu's gate.
  root.addEventListener('dblclick', (e) => {
    const deckEl = e.target?.closest?.('[data-zone="deck"]');
    if (deckEl) {
      if (ownsZone(deckEl)) send(drawIntent(deckEl.dataset.owner, deckEl.dataset.side));
      return;
    }
    const cardEl = e.target?.closest?.('[data-card-id]');
    if (!cardEl || !ownsCard(cardEl)) return;
    const id = cardEl.dataset.cardId;
    if (cardEl.closest?.('[data-zone="hand"]')) {
      // Successive plays fan rightward, like dealing off a deck, so a flurry spreads instead of stacking.
      const rect = battleRect();
      const fan = (handPlays++ % HAND_PLAY_FAN_SLOTS) * PREGAME_FAN;
      const x = clamp(Math.round((rect.width - CARD_W) / 2) + fan, 0, rect.width - CARD_W);
      const y = Math.round(rect.height * HAND_PLAY_ROW - CARD_H / 2);
      send(moveCardIntent(id, { kind: 'battlefield' }, [x, y]));
    } else if (isFaceDown(cardEl)) {
      send(flipIntentFor(cardEl.dataset.doubleFaced === '1', id));
    } else if (!cardEl.closest?.('[data-zone="province"]')) {
      send(bowIntent(id, cardEl.dataset.bowed === '1'));
    }
  });

  // Leaving the board clears the hover target so a hotkey can't act on a card the pointer has left.
  root.addEventListener('pointerleave', () => {
    hovered = null;
  });

  // Hover-driven hotkeys on the card/deck under the pointer, gated to the viewer's own pieces and
  // suppressed while typing: F flip, B bow/unbow, I invert (cards); D draw, S search (decks). A card
  // flag op applies to the whole selection when the hovered card is part of one, like its menu item.
  const DECK_HOTKEYS = new Set(['d', 's']);
  document.addEventListener('keydown', (e) => {
    // An open context menu owns the keyboard: its accelerators take over and the hover hotkeys yield.
    // An open card preview does not — any hotkey still acts and the preview's own listener dismisses it.
    if (activeMenu) return;
    if (e.ctrlKey || e.metaKey || e.altKey || isTypingTarget(e.target)) return;
    const key = e.key.toLowerCase();
    if (!hovered) return;
    // View enlarges any card under the pointer, owned or not — it only reveals what's already shown.
    if (key === 'v') {
      const cardEl = hovered.closest?.('[data-card-id]');
      if (!cardEl) return;
      e.preventDefault();
      viewCard(cardEl);
      return;
    }
    const deckEl = hovered.closest?.('[data-zone="deck"]');
    if (DECK_HOTKEYS.has(key)) {
      if (!deckEl || !ownsZone(deckEl)) return;
      const { owner, side } = deckEl.dataset;
      // Consume the keystroke so opening the search prompt doesn't also type the key into its
      // freshly-focused input.
      e.preventDefault();
      if (key === 'd') send(drawIntent(owner, side));
      else openDeckSearchPrompt(owner, side, send);
      return;
    }
    if (key !== 'f' && key !== 'b' && key !== 'i') return;
    const cardEl = hovered.closest?.('[data-card-id]');
    if (!cardEl || cardEl.closest?.('[data-zone="deck"]') || !ownsCard(cardEl)) return;
    e.preventDefault();
    const id = cardEl.dataset.cardId;
    const ids = selected.size > 1 && selected.has(id) ? [...selected] : [id];
    if (key === 'f') send(flipIntentFor(cardEl.dataset.doubleFaced === '1', ids));
    else if (key === 'i') send(invertIntent(ids));
    // Bowing a card in a province is meaningless, so B no-ops there, matching the menu's gate.
    else if (!cardEl.closest?.('[data-zone="province"]'))
      send(bowIntent(ids, cardEl.dataset.bowed === '1'));
  });

  return { markSelection };
}

// Wire the local seat's honor as a stepper, bound once on the persistent `panel` container so it
// survives the inner-DOM swap each SNAPSHOT does. Binding only the local panel is what keeps the
// opponent's honor read-only. `send` receives a room-less client message.
export function initPanelHonor(panel, send) {
  const adjust = (e, delta) => {
    if (!e.target?.closest?.('.panel-honor')) return;
    e.preventDefault?.();
    send(honorIntent(delta));
  };
  panel.addEventListener('click', (e) => adjust(e, 1));
  panel.addEventListener('contextmenu', (e) => adjust(e, -1));
  panel.addEventListener('auxclick', (e) => {
    if (e.button === 1) adjust(e, -1);
  });
  panel.addEventListener('wheel', (e) => adjust(e, e.deltaY < 0 ? 1 : -1));
}
