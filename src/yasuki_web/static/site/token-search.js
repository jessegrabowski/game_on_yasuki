// The "Create token" dialog: a card-database search (the usual query syntax) with a name list on the
// left and a large preview of the selected card on the right; the chosen card spawns as a token onto
// the board. Single-click previews a card, double-click (or the Create button) spawns it. Built with
// createElement (no innerHTML, no inline styles) so it stays CSP-safe under the page's style-src 'self'.

import { node, intentMessage } from './board.js';

const PAGE = 40;
const DEBOUNCE_MS = 200;
const SCROLL_MARGIN_PX = 60; // load the next page once the list scrolls within this of the bottom
// The query starts at t:proxy (most tokens are proxies) but is editable, and the last query — edited
// or cleared — is remembered across opens within the session, since the next token is often the same.
let lastQuery = 't:proxy';

// include:all surfaces token/proxy/non-deck cards (e.g. t:proxy) the default search hides.
const withTokens = (query) => (query ? `${query} include:all` : 'include:all');

const fetchPage = async (query, offset) => {
  const res = await fetch(
    `/api/cards?search=${encodeURIComponent(query)}&limit=${PAGE}&offset=${offset}`,
  );
  const data = await res.json();
  return { cards: data.cards ?? [], hasMore: !!data.has_more };
};

// Open the search over the board; the previewed card spawns as a token at `position` (board-local).
// `searchPage` maps (query, offset) to a promise of `{ cards, hasMore }` and defaults to the
// /api/cards search (it's injectable for tests). `send` receives a room-less client message. Returns
// { el, close }; closes on a spawn, the × or backdrop, or Escape. Pages in as the list scrolls.
export function openTokenSearch({ imgBase, position, send, searchPage = fetchPage, onClose }) {
  const overlay = node('div', 'deck-dialog-overlay');
  const modal = node('div', 'token-dialog');

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

  const closeBtn = node('button', 'deck-dialog-close', '×');
  closeBtn.type = 'button';
  closeBtn.title = 'Close';
  closeBtn.addEventListener('click', close);
  const header = node('div', 'deck-dialog-header');
  header.append(node('h2', 'deck-dialog-title', 'Create token'), closeBtn);

  const form = node('form', 'token-search-form');
  const input = node('input', 'token-search-input');
  input.type = 'search';
  input.placeholder = 'Search cards…';
  input.value = lastQuery;
  form.append(input);

  const list = node('ul', 'token-search-list');
  const previewImg = node('img', 'token-search-preview-img');
  const createBtn = node('button', 'token-search-create', 'Create token');
  createBtn.type = 'button';
  createBtn.disabled = true;
  const preview = node('div', 'token-search-preview');
  preview.append(previewImg, createBtn);
  const body = node('div', 'token-search-body');
  body.append(list, preview);

  const spawn = (card) => {
    // The server resolves the database card and copies it as a full first-class token.
    send(
      intentMessage({
        op: 'SPAWN_CARD',
        print_card_id: card.card_id,
        position: [position.x, position.y],
      }),
    );
    close();
  };

  let selectedCard = null;
  let selectedRow = null;
  const select = (card, row) => {
    selectedCard = card;
    selectedRow?.classList.remove('selected');
    selectedRow = row;
    row?.classList.add('selected');
    if (card?.image_path) {
      previewImg.src = `${imgBase}/${card.image_path}`;
      previewImg.alt = card.name ?? '';
    } else {
      previewImg.removeAttribute('src');
    }
    previewImg.classList.toggle('is-empty', !card?.image_path);
    createBtn.disabled = !card;
  };
  createBtn.addEventListener('click', () => selectedCard && spawn(selectedCard));

  const resultRow = (card) => {
    const li = node('li', 'token-search-result');
    li.dataset.cardId = card.card_id ?? '';
    if (card.image_path) {
      const thumb = node('img', 'token-search-thumb');
      thumb.src = `${imgBase}/${card.image_path}`;
      thumb.alt = '';
      li.append(thumb);
    }
    li.append(node('span', 'token-search-name', card.name ?? ''));
    li.addEventListener('click', () => select(card, li));
    li.addEventListener('dblclick', () => spawn(card));
    return li;
  };

  // `latest` drops a stale response if a newer search supersedes it; `loading` keeps scroll from
  // firing overlapping page loads. A reset starts a fresh query; otherwise the next page appends.
  let latest = 0;
  let loading = false;
  let offset = 0;
  let hasMore = false;
  let activeQuery = '';
  const load = async (reset) => {
    if (reset) {
      offset = 0;
      activeQuery = input.value.trim();
      lastQuery = activeQuery;
    } else if (!hasMore || loading) {
      return;
    }
    const seq = ++latest;
    loading = true;
    const page = await searchPage(withTokens(activeQuery), offset).catch(() => null);
    if (seq !== latest) return; // a newer search owns the list and the loading flag
    loading = false;
    if (!page) return;
    if (reset) list.replaceChildren();
    const rows = page.cards.map(resultRow);
    list.append(...rows);
    offset += page.cards.length;
    hasMore = page.hasMore;
    // Preview the first card of a fresh search so the pane is never blank; paged-in rows leave the
    // current selection untouched.
    if (reset || !selectedCard) select(page.cards[0] ?? null, rows[0] ?? null);
  };

  form.addEventListener('submit', (e) => {
    e.preventDefault?.();
    load(true);
  });
  let debounce;
  input.addEventListener('input', () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => load(true), DEBOUNCE_MS);
  });
  list.addEventListener('scroll', () => {
    if (list.scrollTop + list.clientHeight >= list.scrollHeight - SCROLL_MARGIN_PX) load(false);
  });

  modal.append(header, form, body);
  overlay.append(modal);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });
  (document.querySelector('.room') ?? document.body).appendChild(overlay);
  document.addEventListener?.('keydown', onKey);
  input.focus?.();
  if (input.value.trim()) load(true); // re-run the remembered search
  return { el: overlay, close };
}
