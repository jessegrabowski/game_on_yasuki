// The search dialog for a deck or a discard pile: the cards top-first, filterable by card title, with
// a small preview of the selected one and buttons to take it. A deck (private) offers Pull to the
// battlefield, Discard, or Bottom, and a footer that can shuffle on close to re-randomize the order
// the search exposed. A discard (public, either player may search it) offers only Pull — and only
// from one's own pile (`canPull`). Built with createElement (no innerHTML, no inline styles) so it
// stays CSP-safe under the page's style-src 'self'. It stays open after a deal so several cards can be
// taken in one sitting; the dealt card leaves the list and the rest keep their order.

import {
  deckDest,
  discardDest,
  moveCardIntent,
  node,
  shuffleIntent,
  UNPLACED_POSITION,
} from './board.js';

const SIDE_LABELS = { FATE: 'Fate', DYNASTY: 'Dynasty' };

const matchesTitle = (card, query) => (card.name ?? '').toLowerCase().includes(query);

// Open the dialog over the page. `cards` is top-first; `limit` caps the list to the top N (null =
// whole pile). `kind` is 'deck' (default) or 'discard', which trims to Pull-only with no shuffle.
// `canPull` gates the Pull button — false for an opponent's discard. `send` receives a room-less
// client message. Returns { el, close }. Closes on the overlay, the × or footer buttons, or Escape.
export function openDeckDialog({
  deck,
  cards,
  imgBase,
  limit = null,
  send,
  onClose,
  kind = 'deck',
  canPull = true,
}) {
  const isDiscard = kind === 'discard';
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

  // Pull deals the card to the battlefield via the unplaced sentinel, which the client routes to the
  // fate or dynasty side; Discard and Bottom (deck only) use plain destinations. Each deal removes the
  // card from the list and keeps the dialog open. A discard offers Pull alone, gated by `canPull`.
  const dealActions = isDiscard
    ? [{ label: 'Pull', dest: { kind: 'battlefield' }, position: UNPLACED_POSITION, enabled: canPull }]
    : [
        { label: 'Pull', dest: { kind: 'battlefield' }, position: UNPLACED_POSITION },
        { label: 'Discard', dest: discardDest(deck.owner, deck.side) },
        { label: 'Bottom', dest: deckDest(deck.owner, deck.side), toBottom: true },
      ];
  const dealButtons = dealActions.map((action) => {
    const btn = node('button', 'deck-dialog-deal', action.label);
    btn.type = 'button';
    btn.addEventListener('click', () =>
      deal((id) => moveCardIntent(id, action.dest, action.position ?? null, action.toBottom ?? false)),
    );
    return { btn, enabled: action.enabled !== false };
  });
  const preview = node('div', 'deck-dialog-preview');
  preview.append(previewImg, ...dealButtons.map((d) => d.btn));
  const body = node('div', 'deck-dialog-body');
  body.append(list, preview);

  const footerClose = node('button', 'deck-dialog-btn', 'Close');
  footerClose.type = 'button';
  footerClose.addEventListener('click', close);
  const footer = node('div', 'deck-dialog-footer');
  footer.append(footerClose);
  // Only a deck re-randomizes on close; a discard has no hidden order to restore.
  if (!isDiscard) {
    const footerShuffle = node('button', 'deck-dialog-btn', 'Close and shuffle');
    footerShuffle.type = 'button';
    footerShuffle.addEventListener('click', () => {
      send(shuffleIntent(deck.owner, deck.side));
      close();
    });
    footer.append(footerShuffle);
  }

  modal.append(header, filterInput, body, footer);
  overlay.appendChild(modal);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });

  const visible = () => (query ? pool.filter((card) => matchesTitle(card, query)) : pool);

  function renderTitle() {
    const side = SIDE_LABELS[deck.side] ?? deck.side ?? '';
    title.textContent = `${side} ${isDiscard ? 'discard' : 'deck'} — ${pool.length} cards`.trim();
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
    for (const { btn, enabled } of dealButtons) btn.disabled = !enabled || !selectedCard;
  }

  function deal(makeIntent) {
    if (!selectedId) return;
    send(makeIntent(selectedId));
    const idx = pool.findIndex((card) => card.id === selectedId);
    if (idx >= 0) pool.splice(idx, 1);
    // Keep the reading position: select whatever card slid into the dealt one's slot, else the last.
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
