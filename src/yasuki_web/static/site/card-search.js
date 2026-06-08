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
    `data-full="${esc(full)}" data-name="${name}">` +
    `<img src="${esc(primary)}" alt="${name}" loading="lazy" onerror="${onError}">` +
    `<span class="card-tile-name">${name}</span>` +
    `</div>`
  );
}

let lightbox;
let lightboxImg;

function closeLightbox() {
  if (lightbox) lightbox.classList.remove('open');
  document.removeEventListener('keydown', onLightboxKey);
}

function onLightboxKey(e) {
  if (e.key === 'Escape') closeLightbox();
}

// Enlarge a card over a dim backdrop; clicking the backdrop (anywhere but the card) or pressing
// Escape dismisses it. The overlay is built once and reused.
function openLightbox(src, alt) {
  if (!lightbox) {
    lightbox = document.createElement('div');
    lightbox.className = 'lightbox';
    lightboxImg = document.createElement('img');
    lightboxImg.className = 'lightbox-img';
    lightbox.appendChild(lightboxImg);
    document.body.appendChild(lightbox);
    lightbox.addEventListener('click', (e) => {
      if (e.target === lightbox) closeLightbox();
    });
  }
  lightboxImg.src = src;
  lightboxImg.alt = alt || '';
  lightbox.classList.add('open');
  document.addEventListener('keydown', onLightboxKey);
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
    openLightbox(tile.dataset.full, tile.dataset.name);
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
