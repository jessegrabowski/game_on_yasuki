// The deck-search dialog: the owner's deck in shuffled (top-first) order, filterable by card title,
// with a small preview of the selected card and a Pull button that deals it to the battlefield above
// the owner's dynasty deck (face-down, like a draw). Built with createElement (no innerHTML, no inline
// styles) so it stays CSP-safe under the page's style-src 'self'.
// It stays open after a pull so several cards can be taken in one sitting; the pulled card leaves the
// list and the rest keep their order. A footer closes the dialog, optionally shuffling the deck first
// to re-randomize the order the search just exposed.

import { moveCardIntent, node, shuffleIntent } from './board.js';

const SIDE_LABELS = { FATE: 'Fate', DYNASTY: 'Dynasty' };

// Deal a deck card to the battlefield above its owner's dynasty deck — the negative sentinel position
// the client lays out there — face-down, exactly like an overflow draw.
function pullIntent(cardId) {
  return moveCardIntent(cardId, { kind: 'battlefield' }, [-1, -1]);
}

const matchesTitle = (card, query) => (card.name ?? '').toLowerCase().includes(query);

// Open the dialog over the page. `cards` is the deck top-first; `limit` caps the list to the top N
// (null = whole deck). `send` receives a room-less client message. Returns { el, close }. Closes on
// the overlay, the × or footer buttons, or Escape.
export function openDeckDialog({ deck, cards, imgBase, limit = null, send, onClose }) {
  // The working list, capped to the chosen limit and kept top-first; a pulled card is spliced out.
  let pool = (cards ?? []).slice(0, limit ?? (cards ?? []).length);
  let query = '';
  let selectedId = pool[0]?.id ?? null;

  const overlay = node('div', 'deck-dialog-overlay');
  const modal = node('div', 'deck-dialog');

  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    document.removeEventListener?.('keydown', onKey);
    overlay.remove();
    onClose?.();
  };
  const onKey = (e) => {
    if (e.key === 'Escape') close();
  };

  const title = node('h2', 'deck-dialog-title');
  const closeBtn = node('button', 'deck-dialog-close', '×');
  closeBtn.type = 'button';
  closeBtn.title = 'Close';
  closeBtn.addEventListener('click', close);
  const header = node('div', 'deck-dialog-header');
  header.append(title, closeBtn);

  const filterInput = node('input', 'deck-dialog-filter');
  filterInput.type = 'text';
  filterInput.placeholder = 'Filter by title…';
  filterInput.addEventListener('input', () => {
    query = filterInput.value.trim().toLowerCase();
    renderList();
  });

  const list = node('ul', 'deck-dialog-list');
  const previewImg = node('img', 'deck-dialog-preview-img');
  const pull = node('button', 'deck-dialog-pull', 'Pull');
  pull.type = 'button';
  pull.addEventListener('click', onPull);
  const preview = node('div', 'deck-dialog-preview');
  preview.append(previewImg, pull);
  const body = node('div', 'deck-dialog-body');
  body.append(list, preview);

  const footerClose = node('button', 'deck-dialog-btn', 'Close');
  footerClose.type = 'button';
  footerClose.addEventListener('click', close);
  const footerShuffle = node('button', 'deck-dialog-btn', 'Close and shuffle');
  footerShuffle.type = 'button';
  footerShuffle.addEventListener('click', () => {
    send(shuffleIntent(deck.owner, deck.side));
    close();
  });
  const footer = node('div', 'deck-dialog-footer');
  footer.append(footerClose, footerShuffle);

  modal.append(header, filterInput, body, footer);
  overlay.appendChild(modal);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });

  const visible = () => (query ? pool.filter((card) => matchesTitle(card, query)) : pool);

  function renderTitle() {
    const side = SIDE_LABELS[deck.side] ?? deck.side ?? '';
    title.textContent = `${side} deck — ${pool.length} cards`.trim();
  }

  function renderList() {
    const cards = visible();
    if (!cards.some((card) => card.id === selectedId)) selectedId = cards[0]?.id ?? null;
    list.replaceChildren(
      ...cards.map((card) => {
        const li = node('li', 'deck-dialog-name', card.name ?? '');
        li.dataset.cardId = card.id;
        if (card.id === selectedId) li.classList.add('selected');
        li.addEventListener('click', () => {
          selectedId = card.id;
          renderList();
        });
        return li;
      }),
    );
    renderPreview();
  }

  function renderPreview() {
    const selectedCard = pool.find((card) => card.id === selectedId);
    if (selectedCard?.img) {
      previewImg.src = `${imgBase}/${selectedCard.img}`;
      previewImg.alt = selectedCard.name ?? '';
    } else {
      previewImg.removeAttribute('src');
    }
    previewImg.classList.toggle('is-empty', !selectedCard?.img);
    pull.disabled = !selectedCard;
  }

  function onPull() {
    if (!selectedId) return;
    send(pullIntent(selectedId));
    const idx = pool.findIndex((card) => card.id === selectedId);
    if (idx >= 0) pool.splice(idx, 1);
    // Keep the reading position: select whatever card slid into the pulled one's slot, else the last.
    selectedId = pool[Math.min(idx, pool.length - 1)]?.id ?? null;
    renderTitle();
    renderList();
  }

  // Mount inside `.room`, not the document body: the board's color palette (--r-panel, --r-gold, …)
  // is scoped to `.room`, so an overlay outside it would render unstyled and let cards show through.
  (document.querySelector('.room') ?? document.body).appendChild(overlay);
  document.addEventListener?.('keydown', onKey);
  filterInput.focus?.();
  renderTitle();
  renderList();
  return { el: overlay, close };
}
