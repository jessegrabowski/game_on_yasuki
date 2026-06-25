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

export function addCardFrame(room, card) {
  return {
    type: 'BOARD',
    room,
    board: { kind: 'ADD_CARD', id: card.id, name: card.name, img: card.img, x: card.x, y: card.y },
  };
}
