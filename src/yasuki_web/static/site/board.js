// Shared battlefield rendering and interaction for a play room. Cards are absolutely-positioned DOM
// elements built via createElement/CSSOM rather than innerHTML: the page CSP (style-src 'self')
// blocks inline style attributes, and property assignment needs no manual escaping.

function cardElement(card, imgBase) {
  const el = document.createElement('div');
  el.className = 'board-card';
  if (card.bowed) el.classList.add('bowed');
  el.dataset.cardId = card.id;
  el.dataset.bowed = card.bowed ? '1' : '';
  el.style.left = `${card.x}px`;
  el.style.top = `${card.y}px`;

  // A hidden stub (a card this viewer may not identify) or an explicitly face-down card shows a back.
  if (card.hidden || card.face_up === false) {
    el.classList.add('face-down');
  } else {
    const img = document.createElement('img');
    img.src = `${imgBase}/${card.img}`;
    img.alt = card.name;
    el.appendChild(img);
  }
  return el;
}

export function renderBoard(boardEl, cards, imgBase) {
  boardEl.replaceChildren(...cards.map((card) => cardElement(card, imgBase)));
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

// Card footprint, matching .board-card in play.css.
const CARD_W = 90;
const CARD_H = 128;
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

// Wire pointer-drag and the right-click menu once; delegation on the board survives the full
// re-render that every SNAPSHOT triggers. `send` receives a room-less client message.
export function initBoardInteractions(boardEl, send) {
  let drag = null;
  let lastSent = 0;

  const rectOf = () => boardEl.getBoundingClientRect();
  const cardUnder = (target) => target?.closest?.('.board-card');

  boardEl.addEventListener('pointerdown', (e) => {
    if (e.button !== 0) return;
    const cardEl = cardUnder(e.target);
    if (!cardEl) return;
    const cardRect = cardEl.getBoundingClientRect();
    drag = {
      id: cardEl.dataset.cardId,
      grabX: e.clientX - cardRect.left,
      grabY: e.clientY - cardRect.top,
    };
    boardEl.setPointerCapture(e.pointerId);
  });

  boardEl.addEventListener('pointermove', (e) => {
    if (!drag) return;
    const pos = dragPosition(e.clientX, e.clientY, rectOf(), { x: drag.grabX, y: drag.grabY });
    const cardEl = boardEl.querySelector(`[data-card-id="${CSS.escape(drag.id)}"]`);
    if (cardEl) {
      cardEl.style.left = `${pos.x}px`;
      cardEl.style.top = `${pos.y}px`;
    }
    const now = Date.now();
    if (now - lastSent > DRAG_SEND_MS) {
      lastSent = now;
      send(moveIntent(drag.id, pos.x, pos.y));
    }
  });

  const endDrag = (e) => {
    if (!drag) return;
    const pos = dragPosition(e.clientX, e.clientY, rectOf(), { x: drag.grabX, y: drag.grabY });
    send(moveIntent(drag.id, pos.x, pos.y));
    drag = null;
  };
  boardEl.addEventListener('pointerup', endDrag);
  boardEl.addEventListener('pointercancel', () => {
    drag = null;
  });

  boardEl.addEventListener('contextmenu', (e) => {
    const cardEl = cardUnder(e.target);
    if (!cardEl) return;
    e.preventDefault();
    const bowed = cardEl.dataset.bowed === '1';
    openMenu(boardEl, cardEl.dataset.cardId, bowed, e.clientX, e.clientY, send);
  });
}
