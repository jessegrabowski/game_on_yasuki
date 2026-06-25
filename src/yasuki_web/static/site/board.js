// Shared battlefield rendering and interaction for a play room. Cards are absolutely-positioned DOM
// elements built via createElement/CSSOM rather than innerHTML: the page CSP (style-src 'self')
// blocks inline style attributes, and property assignment needs no manual escaping.

function node(tag, className, text) {
  const el = document.createElement(tag);
  if (className) el.className = className;
  if (text != null) el.textContent = text;
  return el;
}

// Show a card's face: its art, or a back for a hidden stub / explicitly face-down card.
function applyFace(el, card, imgBase) {
  if (card.hidden || card.face_up === false) {
    el.classList.add('face-down');
    return;
  }
  const img = document.createElement('img');
  img.src = `${imgBase}/${card.img}`;
  img.alt = card.name;
  el.appendChild(img);
}

// An absolutely-positioned battlefield card.
function cardElement(card, imgBase) {
  const el = node('div', 'board-card');
  if (card.bowed) el.classList.add('bowed');
  el.dataset.cardId = card.id;
  el.dataset.bowed = card.bowed ? '1' : '';
  el.style.left = `${card.x}px`;
  el.style.top = `${card.y}px`;
  applyFace(el, card, imgBase);
  return el;
}

// A card laid out in a zone (hand, province, pile) — flow-positioned, no x/y.
function zoneCard(card, imgBase) {
  const el = node('div', 'zone-card');
  if (card.bowed) el.classList.add('bowed');
  el.dataset.cardId = card.id;
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
  if (topCard) tile.append(zoneCard(topCard, imgBase));
  else if (deck && count > 0) tile.classList.add('is-back');
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
// wind are not part of the tableau — they are loose battlefield cards the client lays out beside the
// dynasty deck (see placePregameCards).
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

// A seat's identity: avatar, name, and current honor.
export function renderPanel(container, info) {
  const avatar = node('div', 'avatar', initials(info.name));
  const meta = node('div', 'panel-meta');
  meta.append(
    node('span', 'panel-name', info.name ?? ''),
    node('span', 'panel-honor', String(info.honor ?? 0)),
  );
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
export const flipIntent = (id) => intentMessage({ op: 'FLIP', card_ids: [id] });
// BOW/UNBOW are explicit ops, so a "Bow / Unbow" toggle picks the one that changes the card.
export const bowIntent = (id, bowed) =>
  intentMessage({ op: bowed ? 'UNBOW' : 'BOW', card_ids: [id] });
// Draw the top card of a seat's deck; the server routes it (fate → hand, dynasty → province).
export const drawIntent = (owner, side) => intentMessage({ op: 'DRAW', deck: { owner, side } });
// Move a card to a zone/deck/battlefield destination (position set only for the battlefield).
export const moveCardIntent = (id, to, position = null) =>
  intentMessage({ op: 'MOVE_CARD', card_id: id, to, position });

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

// Horizontal step between an owner's fanned-out pre-game cards, and the vertical gap between that fan
// and the dynasty deck, both in pixels.
const PREGAME_FAN = 20;
const PREGAME_DECK_GAP = 10;

// Battlefield-local top-left next to a seat's dynasty deck, or null if the tableau is not laid out
// yet. The pre-game cards sit just inboard of the deck — above it for the bottom (viewer) seat, below
// it for the top seat — so they read as "by the dynasty deck" without covering it.
export function deckAnchor(tableau, battlefield, above) {
  const deckEl = tableau?.querySelector?.('.pile.deck[data-side="DYNASTY"]');
  if (!deckEl) return null;
  const d = deckEl.getBoundingClientRect();
  const b = battlefield.getBoundingClientRect();
  const deckY = d.top - b.top;
  return {
    x: d.left - b.left,
    y: above ? deckY - CARD_H - PREGAME_DECK_GAP : deckY + CARD_H + PREGAME_DECK_GAP,
  };
}

// Give each unplaced pre-game card (server x < 0) a position fanned out from its owner's dynasty
// deck. Cards already dragged keep their server position; non-pre-game cards pass through untouched.
// `anchorFor(owner, isViewer)` returns the owner's anchor or null. Returns a new array.
export function placePregameCards(cards, viewerSeat, anchorFor) {
  const placedPerOwner = {};
  return cards.map((card) => {
    if (!card.pregame || card.x >= 0) return card;
    const anchor = anchorFor(card.owner, card.owner === viewerSeat);
    if (!anchor) return card;
    const index = placedPerOwner[card.owner] ?? 0;
    placedPerOwner[card.owner] = index + 1;
    return { ...card, x: anchor.x + index * PREGAME_FAN, y: anchor.y };
  });
}

let activeMenu = null;

function closeMenu() {
  activeMenu?.remove();
  activeMenu = null;
}

function openMenu(boardEl, cardId, bowed, clientX, clientY, send) {
  closeMenu();
  const rect = boardEl.getBoundingClientRect();
  const menu = document.createElement('ul');
  menu.className = 'board-menu';
  menu.style.left = `${clientX - rect.left}px`;
  menu.style.top = `${clientY - rect.top}px`;

  const items = [
    ['Flip', flipIntent(cardId)],
    ['Bow / Unbow', bowIntent(cardId, bowed)],
    ['Remove', removeMessage(cardId)],
  ];
  for (const [label, message] of items) {
    const li = document.createElement('li');
    li.textContent = label;
    li.addEventListener('click', () => {
      send(message);
      closeMenu();
    });
    menu.appendChild(li);
  }

  boardEl.appendChild(menu);
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

// Wire dragging and the right-click menu once on the table `root` (which spans the battlefield and
// every seat zone), so delegation survives the full re-render each SNAPSHOT triggers. A card can be
// picked up anywhere and dropped on any zone: a drop on the battlefield repositions (SET_CARD_POS)
// or plays a card there, a drop on another zone is a MOVE_CARD. `boardEl` is the battlefield, used
// for position maths; `send` receives a room-less client message.
export function initBoardInteractions(root, boardEl, send) {
  let drag = null;
  let lastSent = 0;
  const battleRect = () => boardEl.getBoundingClientRect();

  const release = () => {
    if (!drag) return;
    drag.el.style.pointerEvents = '';
    drag.el.classList.remove('dragging');
    drag = null;
  };

  root.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    const cardEl = e.target?.closest?.('[data-card-id]');
    if (!cardEl) return;
    const rect = cardEl.getBoundingClientRect();
    drag = {
      id: cardEl.dataset.cardId,
      el: cardEl,
      onBattlefield: cardEl.classList.contains('board-card'),
      grabX: e.clientX - rect.left,
      grabY: e.clientY - rect.top,
    };
    // Lift the card out of hit-testing so a drop lands on the zone beneath, not the card itself.
    cardEl.style.pointerEvents = 'none';
    cardEl.classList.add('dragging');
  });

  root.addEventListener('pointermove', (e) => {
    if (!drag || !drag.onBattlefield) return;
    const pos = dragPosition(e.clientX, e.clientY, battleRect(), { x: drag.grabX, y: drag.grabY });
    drag.el.style.left = `${pos.x}px`;
    drag.el.style.top = `${pos.y}px`;
    const now = Date.now();
    if (now - lastSent > DRAG_SEND_MS) {
      lastSent = now;
      send(moveIntent(drag.id, pos.x, pos.y));
    }
  });

  root.addEventListener('pointerup', (e) => {
    if (!drag) return;
    const card = drag;
    release();
    const target = e.target?.closest?.('[data-zone]');
    const zone = target?.dataset.zone;
    if (zone === 'battlefield' || (!zone && card.onBattlefield)) {
      const pos = dragPosition(e.clientX, e.clientY, battleRect(), { x: card.grabX, y: card.grabY });
      if (card.onBattlefield) send(moveIntent(card.id, pos.x, pos.y));
      else send(moveCardIntent(card.id, { kind: 'battlefield' }, [pos.x, pos.y]));
    } else if (zone) {
      const dest = zoneDest(target);
      if (dest) send(moveCardIntent(card.id, dest));
    }
  });

  root.addEventListener('pointercancel', release);

  // A pointer released or cancelled outside the table never reaches the handlers above; this net
  // restores a dragged card to hit-testing so it can never get stuck mid-drag.
  if (typeof window !== 'undefined' && window.addEventListener) {
    window.addEventListener('pointerup', release);
    window.addEventListener('pointercancel', release);
  }

  root.addEventListener('contextmenu', (e) => {
    const cardEl = e.target?.closest?.('[data-card-id]');
    if (!cardEl) return;
    e.preventDefault();
    openMenu(boardEl, cardEl.dataset.cardId, cardEl.dataset.bowed === '1', e.clientX, e.clientY, send);
  });
}
