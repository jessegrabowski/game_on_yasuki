const PAGE_SIZE = 60;

// Type-keyed default art, mirroring the deck builder's preview fallbacks, for cards whose print has
// no scanned image yet.
const DEFAULT_BY_TYPE = {
  celestial: 'defaults/generic_celestial.jpg',
  event: 'defaults/generic_event.jpg',
  follower: 'defaults/generic_follower.jpg',
  holding: 'defaults/generic_holding.jpg',
  item: 'defaults/generic_item.jpg',
  personality: 'defaults/generic_personality.jpg',
  region: 'defaults/generic_region.jpg',
  ring: 'defaults/generic_ring.jpg',
  sensei: 'defaults/generic_sensei.jpg',
  spell: 'defaults/generic_spell.jpg',
  strategy: 'defaults/generic_strategy.jpg',
  stronghold: 'defaults/generic_stronghold.jpg',
  wind: 'defaults/generic_wind.jpg',
};

const grid = document.getElementById('grid');
const status = document.getElementById('status');
const resultMeta = document.getElementById('resultMeta');
const queryInput = document.getElementById('q');

let imgBase = '/images';
let query = '';
let sort = 'name';
let order = 'asc';
let offset = 0;
let total = 0;
let loading = false;
let exhausted = false;

const esc = (s) =>
  String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

const displayName = (card) => {
  const title = card.extended_title || card.name || '';
  return card.is_unique ? '◆ ' + title : title;
};

function fallbackSrc(card) {
  const type = ((card.types || [])[0] || '').toLowerCase();
  const path = DEFAULT_BY_TYPE[type];
  return path ? `${imgBase}/${path}` : null;
}

function tileHTML(card) {
  const name = esc(displayName(card));
  const primary = card.image_path ? `${imgBase}/${card.image_path}` : fallbackSrc(card);
  const fb = fallbackSrc(card);

  if (!primary) {
    return `<div class="card-tile placeholder" title="${name}">${name}</div>`;
  }

  // On a broken scan, drop to the type default once, then to a text placeholder.
  const onError = fb && primary !== fb
    ? `this.onerror=null;this.src='${esc(fb)}'`
    : `this.onerror=null;this.closest('.card-tile').classList.add('placeholder');this.remove()`;
  const full = card.image_path ? `${imgBase}/${card.image_path}` : primary;

  return (
    `<div class="card-tile" role="button" tabindex="0" title="${name}" ` +
    `data-full="${esc(full)}" data-name="${name}" data-card-id="${esc(card.card_id)}" ` +
    `data-default-print-id="${esc(card.default_print_id ?? '')}">` +
    `<img src="${esc(primary)}" alt="${name}" loading="lazy" onerror="${onError}">` +
    `<span class="card-tile-name">${name}</span>` +
    `</div>`
  );
}

// The enlarged-card overlay doubles as a print viewer: it cycles a card's printings (oldest first,
// matching the detail endpoint) and flips double-faced cards. Built once and reused; `viewer` holds
// the open card's state, and `openToken` discards a slow detail fetch when a newer card is opened.
let lightbox, lightboxImg, lightboxCaption, lightboxPrev, lightboxNext, lightboxFlip;
const viewer = { card: null, prints: [], index: 0, flipped: false, name: '', fallback: '' };
let openToken = 0;

function closeLightbox() {
  if (lightbox) lightbox.classList.remove('open');
  document.removeEventListener('keydown', onLightboxKey);
}

function onLightboxKey(e) {
  if (e.key === 'Escape') closeLightbox();
  else if (e.key === 'ArrowLeft') stepPrint(-1);
  else if (e.key === 'ArrowRight') stepPrint(1);
  else if (e.key === 'f' || e.key === 'F') flipCard();
}

function stepPrint(delta) {
  const n = viewer.prints.length;
  if (n <= 1) return;
  viewer.index = (viewer.index + delta + n) % n;
  viewer.flipped = false; // a fresh printing always opens on its front
  renderViewer();
}

function flipCard() {
  if (!viewer.prints[viewer.index]?.back_image_path) return;
  viewer.flipped = !viewer.flipped;
  renderViewer();
}

function renderViewer() {
  const print = viewer.prints[viewer.index];
  const back = print?.back_image_path ? `${imgBase}/${print.back_image_path}` : null;
  const front = print?.image_path
    ? `${imgBase}/${print.image_path}`
    : viewer.fallback || (viewer.card && fallbackSrc(viewer.card)) || '';
  const showingBack = viewer.flipped && back;

  lightboxImg.src = showingBack ? back : front;
  lightboxImg.alt = viewer.name;

  const n = viewer.prints.length;
  const setName = print?.set_name ? ` &mdash; ${esc(print.set_name)}` : '';
  const counter = n > 1 ? ` (${viewer.index + 1}/${n})` : '';
  lightboxCaption.innerHTML = `${esc(viewer.name)}${setName}${counter}`;

  lightboxPrev.hidden = lightboxNext.hidden = n <= 1;
  lightboxFlip.hidden = !back;
  lightboxFlip.setAttribute('aria-pressed', String(!!showingBack));
}

function buildLightbox() {
  lightbox = document.createElement('div');
  lightbox.className = 'lightbox';
  lightbox.innerHTML =
    '<button class="lb-nav lb-prev" type="button" aria-label="Previous printing">&#x2039;</button>' +
    '<figure class="lb-figure">' +
    '<img class="lightbox-img" alt="">' +
    '<button class="lb-flip" type="button" aria-label="Flip card">&#x21BB;</button>' +
    '<figcaption class="lb-caption"></figcaption>' +
    '</figure>' +
    '<button class="lb-nav lb-next" type="button" aria-label="Next printing">&#x203A;</button>';
  document.body.appendChild(lightbox);

  lightboxImg = lightbox.querySelector('.lightbox-img');
  lightboxCaption = lightbox.querySelector('.lb-caption');
  lightboxPrev = lightbox.querySelector('.lb-prev');
  lightboxNext = lightbox.querySelector('.lb-next');
  lightboxFlip = lightbox.querySelector('.lb-flip');

  lightbox.addEventListener('click', (e) => {
    if (e.target === lightbox) closeLightbox();
  });
  lightboxPrev.addEventListener('click', (e) => (e.stopPropagation(), stepPrint(-1)));
  lightboxNext.addEventListener('click', (e) => (e.stopPropagation(), stepPrint(1)));
  lightboxFlip.addEventListener('click', (e) => (e.stopPropagation(), flipCard()));
}

// Enlarge a card over a dim backdrop, painting the tile's art immediately, then hydrate the print
// list from the detail endpoint so the viewer can cycle and flip. Clicking the backdrop or pressing
// Escape dismisses it.
async function openLightbox(tile) {
  if (!lightbox) buildLightbox();
  const token = ++openToken;

  viewer.card = null;
  viewer.prints = [];
  viewer.index = 0;
  viewer.flipped = false;
  viewer.name = tile.dataset.name || '';
  viewer.fallback = tile.dataset.full || '';

  lightboxImg.src = viewer.fallback;
  lightboxImg.alt = viewer.name;
  lightboxCaption.textContent = viewer.name;
  lightboxPrev.hidden = lightboxNext.hidden = lightboxFlip.hidden = true;
  lightbox.classList.add('open');
  document.addEventListener('keydown', onLightboxKey);

  const cardId = tile.dataset.cardId;
  if (!cardId) return;
  try {
    const res = await fetch(`/api/cards/${encodeURIComponent(cardId)}`);
    if (!res.ok || token !== openToken) return; // superseded by a newer open, or closed
    const body = await res.json();
    if (token !== openToken) return;
    viewer.card = body.card;
    viewer.prints = body.prints || [];
    const want = Number(tile.dataset.defaultPrintId);
    const idx = viewer.prints.findIndex((p) => p.print_id === want);
    viewer.index = idx >= 0 ? idx : 0;
    renderViewer();
  } catch (_) {
    /* keep the static tile art if the detail fetch fails */
  }
}

function renderMeta() {
  if (total === 0) {
    resultMeta.textContent = query ? 'No cards match that search.' : '';
    return;
  }
  const shown = grid.childElementCount;
  const fmt = (n) => n.toLocaleString('en-US');
  resultMeta.innerHTML =
    `Showing <strong>${fmt(shown)}</strong> of <strong>${fmt(total)}</strong> cards` +
    (query ? ` for <strong>${esc(query)}</strong>` : '');
}

async function loadMore() {
  if (loading || exhausted) return;
  loading = true;
  status.innerHTML = '<span class="spinner"></span>Loading&hellip;';

  const params = new URLSearchParams({ limit: PAGE_SIZE, offset, sort, order });
  if (query) params.set('search', query);

  try {
    const res = await fetch(`/api/cards?${params}`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const body = await res.json();
    total = body.total ?? 0;
    const cards = body.cards || [];
    grid.insertAdjacentHTML('beforeend', cards.map(tileHTML).join(''));
    offset += cards.length;
    exhausted = !body.has_more || cards.length === 0;
    renderMeta();
    status.textContent =
      total === 0 ? '' : exhausted && total > 0 ? '— end of results —' : '';
  } catch (err) {
    exhausted = true;
    status.textContent = 'Search failed. Please try again.';
  } finally {
    loading = false;
  }
}

function init() {
  const params = new URLSearchParams(location.search);
  query = (params.get('q') || '').trim();
  queryInput.value = query;

  const sortSelect = document.getElementById('sort');
  const orderSelect = document.getElementById('order');
  if (params.get('sort')) sortSelect.value = params.get('sort');
  if (params.get('order')) orderSelect.value = params.get('order');
  sort = sortSelect.value;
  order = orderSelect.value;

  // Changing the sort reloads the page through the search form, keeping the URL canonical and
  // shareable rather than re-sorting only the cards already fetched.
  const resubmit = () => document.getElementById('searchForm').submit();
  sortSelect.addEventListener('change', resubmit);
  orderSelect.addEventListener('change', resubmit);

  const zoomFromEvent = (e) => {
    const tile = e.target.closest('.card-tile');
    if (!tile || !tile.dataset.full) return false;
    openLightbox(tile);
    return true;
  };
  grid.addEventListener('click', zoomFromEvent);
  grid.addEventListener('keydown', (e) => {
    if ((e.key === 'Enter' || e.key === ' ') && zoomFromEvent(e)) e.preventDefault();
  });

  fetch('/api/config')
    .then((r) => r.json())
    .then((c) => {
      if (c.image_base_url) imgBase = c.image_base_url;
    })
    .catch(() => {})
    .finally(() => {
      loadMore();
      new IntersectionObserver(
        (entries) => {
          if (entries.some((e) => e.isIntersecting)) loadMore();
        },
        { rootMargin: '600px' }
      ).observe(document.getElementById('sentinel'));
    });
}

init();
