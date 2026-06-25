// INTERIM (PR03): a flat, fully-public battlefield with no ownership or hidden info, replaced by
// the authoritative TableState protocol in PR07.
//
// Shared battlefield rendering for a play room. Cards are absolutely-positioned DOM elements built
// via createElement/CSSOM rather than innerHTML: the page CSP (style-src 'self') blocks inline
// style attributes, and property assignment needs no manual escaping.

function cardElement(card, imgBase) {
  const el = document.createElement('div');
  el.className = 'board-card';
  if (card.bowed) el.classList.add('bowed');
  el.dataset.cardId = card.id;
  el.style.left = `${card.x}px`;
  el.style.top = `${card.y}px`;

  if (card.face_up === false) {
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

export const boardFrame = (room, action) => ({ type: 'BOARD', room, board: action });

export function addCardFrame(room, card) {
  return boardFrame(room, {
    kind: 'ADD_CARD',
    id: card.id,
    name: card.name,
    img: card.img,
    x: card.x,
    y: card.y,
  });
}

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

export const moveAction = (id, x, y) => ({ kind: 'SET_CARD_POS', id, x, y });
export const flagAction = (id, flag) => ({ kind: 'CARD_FLAG', id, flag });
export const removeAction = (id) => ({ kind: 'REMOVE_CARD', id });

let activeMenu = null;

function closeMenu() {
  activeMenu?.remove();
  activeMenu = null;
}

function openMenu(boardEl, cardId, clientX, clientY, sendBoardAction) {
  closeMenu();
  const rect = boardEl.getBoundingClientRect();
  const menu = document.createElement('ul');
  menu.className = 'board-menu';
  menu.style.left = `${clientX - rect.left}px`;
  menu.style.top = `${clientY - rect.top}px`;

  const items = [
    ['Flip', flagAction(cardId, 'face_up')],
    ['Bow / Unbow', flagAction(cardId, 'bowed')],
    ['Remove', removeAction(cardId)],
  ];
  for (const [label, action] of items) {
    const li = document.createElement('li');
    li.textContent = label;
    li.addEventListener('click', () => {
      sendBoardAction(action);
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
// re-render that every STATE triggers. `sendBoardAction` receives a board action object.
export function initBoardInteractions(boardEl, sendBoardAction) {
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
      sendBoardAction(moveAction(drag.id, pos.x, pos.y));
    }
  });

  const endDrag = (e) => {
    if (!drag) return;
    const pos = dragPosition(e.clientX, e.clientY, rectOf(), { x: drag.grabX, y: drag.grabY });
    sendBoardAction(moveAction(drag.id, pos.x, pos.y));
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
    openMenu(boardEl, cardEl.dataset.cardId, e.clientX, e.clientY, sendBoardAction);
  });
}
