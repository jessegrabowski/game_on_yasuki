import { esc, displayName, fallbackSrc, fetchImageBase } from './card-common.js';

const PAGE_SIZE = 60;

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

function cardHref(card) {
  const id = encodeURIComponent(card.card_id);
  return card.default_set_slug ? `/card/${id}/${encodeURIComponent(card.default_set_slug)}` : `/card/${id}`;
}

function tileHTML(card) {
  const name = esc(displayName(card));
  const href = cardHref(card);
  const primary = card.image_path ? `${imgBase}/${card.image_path}` : fallbackSrc(card, imgBase);
  const fb = fallbackSrc(card, imgBase);

  if (!primary) {
    return `<a class="card-tile placeholder" href="${href}" title="${name}">${name}</a>`;
  }

  // On a broken scan, drop to the type default once, then to a text placeholder.
  const onError = fb && primary !== fb
    ? `this.onerror=null;this.src='${esc(fb)}'`
    : `this.onerror=null;this.closest('.card-tile').classList.add('placeholder');this.remove()`;

  return (
    `<a class="card-tile" href="${href}" title="${name}">` +
    `<img src="${esc(primary)}" alt="${name}" loading="lazy" onerror="${onError}">` +
    `<span class="card-tile-name">${name}</span>` +
    `</a>`
  );
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

async function init() {
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

  imgBase = await fetchImageBase();
  loadMore();
  new IntersectionObserver(
    (entries) => {
      if (entries.some((e) => e.isIntersecting)) loadMore();
    },
    { rootMargin: '600px' }
  ).observe(document.getElementById('sentinel'));
}

init();
