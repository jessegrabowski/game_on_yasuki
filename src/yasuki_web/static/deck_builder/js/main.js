import { $, debounce, titleCase, scrollToSelected } from './helpers.js';
import { fetchJSON } from './api.js';
import { addCard, removeCard, clearDeck, nextCardAfterRemoval, getDeckNavItems } from './deck-state.js';
import {
  initCardList,
  renderCardList,
  updateResults,
  setFetching,
  isFetching,
  getSelectedCard,
  setSelectedCard,
  selectCard,
  getAllResults,
} from './card-list.js';
import {
  initDeckList,
  renderDeckLists,
  getSelectedDeckCard,
  setSelectedDeckCard,
  selectDeckItem,
} from './deck-list.js';
import { initPreview, showPreview, getCurrentPrintId, getCurrentSetName } from './preview.js';

const API = '/api';
let IMG = '/images';
const LIMIT = 100;
let offset = 0;

async function init() {
  try {
    const cfg = await fetchJSON(`${API}/config`);
    IMG = cfg.image_base_url || IMG;
  } catch (_) {
    /* fall back to /images */
  }

  initPreview(IMG);

  initCardList({
    onSelect: (card) => showPreview(card, null, API),
    onLoadMore: () => {
      offset += LIMIT;
      fetchCards();
    },
  });

  initDeckList({
    onSelect: (card, printId, el) => {
      setSelectedCard(card);
      showPreview(card, printId, API);
      selectDeckItem(el);
    },
    onDblClick: () => doRemoveSelectedFromDeck(),
  });

  $('searchInput').addEventListener('input', debounce(searchCards, 300));
  $('searchInput').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
      e.preventDefault();
      searchCards();
    }
  });

  $('formatFilter').addEventListener('change', searchCards);
  $('deckFilter').addEventListener('change', () => {
    updateTypeFilterForDeck();
    searchCards();
  });
  $('typeFilter').addEventListener('change', searchCards);

  $('helpBtn').addEventListener('click', toggleHelp);
  $('addBtn').addEventListener('click', doAddSelectedToDeck);
  $('removeBtn').addEventListener('click', doRemoveSelectedFromDeck);
  $('clearBtn').addEventListener('click', doClearDeck);

  await populateFilters();
  searchCards();
}

function toggleHelp() {
  const el = $('searchHelp');
  el.style.display = el.style.display === 'none' ? '' : 'none';
}

let allTypes = [];

async function populateFilters() {
  const fill = (selectEl, items, labelFn) => {
    items.forEach((item) => {
      const opt = document.createElement('option');
      opt.value = item;
      opt.textContent = labelFn ? labelFn(item) : item;
      selectEl.appendChild(opt);
    });
  };

  const addSeparator = (selectEl) => {
    const opt = document.createElement('option');
    opt.disabled = true;
    opt.textContent = '──────────';
    selectEl.appendChild(opt);
  };

  try {
    const [formats, decks, types] = await Promise.all([
      fetchJSON(`${API}/formats`),
      fetchJSON(`${API}/decks`),
      fetchJSON(`${API}/card-types`),
    ]);
    const arcs = formats.arcs || [];
    const other = formats.other || [];
    fill($('formatFilter'), arcs);
    if (arcs.length > 0 && other.length > 0) addSeparator($('formatFilter'));
    fill($('formatFilter'), other);
    fill(
      $('deckFilter'),
      (decks.deck_types || []).map((d) => d.toUpperCase()),
      (d) => titleCase(d),
    );
    allTypes = types.card_types || [];
    fill($('typeFilter'), allTypes);
  } catch (e) {
    console.error('Failed to populate filters:', e);
  }
}

function repopulateTypeFilter(types) {
  const typeEl = $('typeFilter');
  const current = typeEl.value;
  typeEl.innerHTML = '';
  const allOpt = document.createElement('option');
  allOpt.value = '';
  allOpt.textContent = 'All Types';
  typeEl.appendChild(allOpt);
  types.forEach((t) => {
    const opt = document.createElement('option');
    opt.value = t;
    opt.textContent = t;
    typeEl.appendChild(opt);
  });
  if (types.includes(current)) {
    typeEl.value = current;
  } else {
    typeEl.value = '';
  }
}

async function updateTypeFilterForDeck() {
  const deckVal = $('deckFilter').value;
  if (!deckVal) {
    repopulateTypeFilter(allTypes);
    return;
  }
  try {
    const data = await fetchJSON(`${API}/card-types-by-deck?deck=${encodeURIComponent(deckVal)}`);
    repopulateTypeFilter(data.card_types || []);
  } catch (_) {
    repopulateTypeFilter(allTypes);
  }
}

function searchCards() {
  offset = 0;
  fetchCards();
}

async function fetchCards() {
  if (isFetching()) return;
  setFetching(true);

  const params = new URLSearchParams();
  const search = $('searchInput').value.trim();
  const format = $('formatFilter').value;
  const deckVal = $('deckFilter').value;
  const cardType = $('typeFilter').value;

  if (search) params.set('search', search);
  if (format) params.set('format', format);
  if (deckVal) params.set('deck', deckVal);
  if (cardType) params.set('card_type', cardType);
  params.set('limit', LIMIT);
  params.set('offset', offset);

  try {
    const data = await fetchJSON(`${API}/cards?${params}`);
    updateResults(data.cards, data.has_more, offset > 0);
    $('totalCards').textContent = `${data.total} cards`;
    renderCardList();
  } catch (e) {
    console.error('Failed to fetch cards:', e);
    setFetching(false);
  }
}

function doAddSelectedToDeck() {
  const card = getSelectedCard();
  if (!card) return;
  const side = card.side || 'FATE';
  const printId = getCurrentPrintId() || 0;
  const setName = getCurrentSetName();
  addCard(card.id, side, card, printId, setName);
  renderDeckLists();
}

function doRemoveSelectedFromDeck() {
  const sel = getSelectedDeckCard();
  if (!sel) return;

  const { side, id } = sel;
  const { cardRemoved, printRemoved, resolvedPrintId } = removeCard(id, side, sel.printId);

  if (cardRemoved) {
    const next = nextCardAfterRemoval(side, id);
    if (next) {
      setSelectedDeckCard({ side, id: next.id, printId: null });
      setSelectedCard(next.card);
      showPreview(next.card, null, API);
    } else {
      setSelectedDeckCard(null);
    }
  } else if (printRemoved) {
    setSelectedDeckCard({ side, id, printId: null });
  }

  renderDeckLists();
  renderCardList();
}

function doClearDeck() {
  clearDeck();
  setSelectedDeckCard(null);
  renderDeckLists();
}

// Keyboard navigation
let focusedList = 'cardList';

['cardList', 'dynastyList', 'fateList', 'preGameList'].forEach((id) => {
  $(id).addEventListener('mousedown', () => {
    focusedList = id;
  });
});

document.addEventListener('keydown', (e) => {
  const active = document.activeElement;
  if (active && (active.tagName === 'INPUT' || active.tagName === 'SELECT' || active.tagName === 'TEXTAREA'))
    return;

  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault();
    if (focusedList === 'cardList') {
      doAddSelectedToDeck();
    } else {
      doRemoveSelectedFromDeck();
    }
    return;
  }

  if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return;

  e.preventDefault();
  const dir = e.key === 'ArrowDown' ? 1 : -1;

  if (focusedList === 'cardList') {
    navigateCardList(dir);
  } else {
    navigateDeckList(focusedList, dir);
  }
});

function navigateCardList(dir) {
  const results = getAllResults();
  if (results.length === 0) return;
  const sel = getSelectedCard();
  let idx = sel ? results.findIndex((c) => c.id === sel.id) : -1;
  idx += dir;
  if (idx < 0) idx = 0;
  if (idx >= results.length) idx = results.length - 1;
  selectCard(results[idx]);
  scrollToSelected('cardList', '.card-list-item.selected');
}

const DECK_LIST_SIDES = { dynastyList: 'DYNASTY', fateList: 'FATE', preGameList: 'PRE_GAME' };

function navigateDeckList(listId, dir) {
  const side = DECK_LIST_SIDES[listId] || 'FATE';
  const items = getDeckNavItems(side);
  if (items.length === 0) return;

  const sel = getSelectedDeckCard();
  let idx = -1;
  if (sel && sel.side === side) {
    idx = items.findIndex((item) => item.id === sel.id && item.printId === sel.printId);
  }

  idx += dir;
  if (idx < 0) idx = 0;
  if (idx >= items.length) idx = items.length - 1;

  const item = items[idx];
  setSelectedDeckCard({ side: item.side, id: item.id, printId: item.printId });
  setSelectedCard(item.card);
  showPreview(item.card, item.printId, API);
  renderDeckLists();
  renderCardList();
  scrollToSelected(listId, '.deck-item.selected, .deck-sub-item.selected');
}

// Column resize
(function () {
  const grid = $('columns');
  const gutters = grid.querySelectorAll('.gutter');
  const cols = grid.querySelectorAll('.col');
  const GUTTER_PX = 4;
  const MIN_COL_PX = 150;

  let colWidths = [null, null, null];

  function getColWidths() {
    return Array.from(cols).map((c) => c.getBoundingClientRect().width);
  }

  function applyWidths(widths) {
    grid.style.gridTemplateColumns = widths.map((w) => w + 'px').join(' ' + GUTTER_PX + 'px ');
  }

  gutters.forEach((gutter) => {
    gutter.addEventListener('mousedown', (e) => {
      e.preventDefault();
      const idx = parseInt(gutter.dataset.gutter);
      colWidths = getColWidths();
      gutter.classList.add('dragging');
      document.body.style.cursor = 'col-resize';
      document.body.style.userSelect = 'none';

      const startX = e.clientX;
      const startLeft = colWidths[idx];
      const startRight = colWidths[idx + 1];

      function onMove(ev) {
        const dx = ev.clientX - startX;
        const newLeft = Math.max(MIN_COL_PX, startLeft + dx);
        const newRight = Math.max(MIN_COL_PX, startRight - dx);
        if (newLeft >= MIN_COL_PX && newRight >= MIN_COL_PX) {
          colWidths[idx] = newLeft;
          colWidths[idx + 1] = newRight;
          applyWidths(colWidths);
        }
      }

      function onUp() {
        gutter.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      }

      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  });
})();

(function () {
  const sections = [
    $('dynastySection'),
    $('fateSection'),
    $('preGameSection'),
  ];
  const gutters = document.querySelectorAll('.deck-gutter');
  const MIN_SECTION_PX = 40;

  function getSectionHeights() {
    return sections.map((s) => s.getBoundingClientRect().height);
  }

  function applySectionHeights(heights) {
    sections.forEach((s, i) => {
      s.style.flex = 'none';
      s.style.height = heights[i] + 'px';
    });
  }

  gutters.forEach((gutter) => {
    gutter.addEventListener('mousedown', (e) => {
      e.preventDefault();
      const idx = parseInt(gutter.dataset.deckGutter);
      let heights = getSectionHeights();
      gutter.classList.add('dragging');
      document.body.style.cursor = 'row-resize';
      document.body.style.userSelect = 'none';

      const startY = e.clientY;
      const startTop = heights[idx];
      const startBottom = heights[idx + 1];

      function onMove(ev) {
        const dy = ev.clientY - startY;
        const newTop = Math.max(MIN_SECTION_PX, startTop + dy);
        const newBottom = Math.max(MIN_SECTION_PX, startBottom - dy);
        if (newTop >= MIN_SECTION_PX && newBottom >= MIN_SECTION_PX) {
          heights[idx] = newTop;
          heights[idx + 1] = newBottom;
          applySectionHeights(heights);
        }
      }

      function onUp() {
        gutter.classList.remove('dragging');
        document.body.style.cursor = '';
        document.body.style.userSelect = '';
        document.removeEventListener('mousemove', onMove);
        document.removeEventListener('mouseup', onUp);
      }

      document.addEventListener('mousemove', onMove);
      document.addEventListener('mouseup', onUp);
    });
  });
})();

init();
