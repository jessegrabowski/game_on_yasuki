import { $, debounce, scrollToSelected, deckSide, stripUnique } from './helpers.js';
import { fetchJSON } from './api.js';
import {
  addCard,
  addCustomPrint,
  removeCard,
  clearDeck,
  getDeck,
  nextCardAfterRemoval,
  getDeckNavItems,
} from './deck-state.js';
import { serializeDeck, parseDeckYaml, deckSnapshot } from './deck-io.js';
import { saveDeckSnapshot, loadDeckSnapshot, clearDeckSnapshot } from './deck-storage.js';
import {
  getMe,
  saveDeck,
  listMyDecks,
  deleteDeck,
  fetchSharedDeck,
} from './account.js';
import { buildCompositeDataURL, customPrintId, loadArtLayout } from './art.js';
import { openBorrowArt } from './borrow-art.js';
import { printDeck } from './print.js';
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
  recordPrintChoice,
  getPrintChoice,
} from './card-list.js';
import {
  initDeckList,
  renderDeckLists,
  getSelectedDeckCard,
  setSelectedDeckCard,
  selectDeckItem,
} from './deck-list.js';
import {
  initPreview,
  showPreview,
  showCustomPreview,
  addCustomPrintToCycle,
  getCurrentPrint,
  getCurrentPrintId,
  getCurrentSetName,
} from './preview.js';

const API = '/api';
let IMG = '/images';
const LIMIT = 100;
let offset = 0;
let totalDbCards = 0;

async function init() {
  try {
    const cfg = await fetchJSON(`${API}/config`);
    IMG = cfg.image_base_url || IMG;
  } catch (_) {
    /* fall back to /images */
  }

  try {
    const data = await fetchJSON(`${API}/cards?limit=1&offset=0`);
    totalDbCards = data.total;
    $('totalDbCount').textContent = totalDbCards;
  } catch (_) {
    $('totalDbCount').textContent = '?';
  }

  try {
    await loadArtLayout(fetchJSON);
  } catch (_) {
    /* borrow-art unavailable until /api/art-layout responds */
  }

  initPreview(IMG, recordPrintChoice, onBorrowArt);

  initCardList({
    onSelect: (card) =>
      showPreview(card, getPrintChoice(card.card_id)?.printId ?? card.default_print_id ?? null, API),
    onDblClick: () => doAddSelectedToDeck(),
    onLoadMore: () => {
      offset += LIMIT;
      fetchCards();
    },
  });

  initDeckList({
    onSelect: (card, printId, el) => {
      setSelectedCard(card);
      const sel = getSelectedDeckCard();
      const entry = sel ? getDeck()[sel.side]?.[sel.id] : null;
      const printData = entry?.prints?.[printId];
      if (printData?.isCustom) showCustomPreview(card, printData);
      else showPreview(card, printId, API);
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

  // Format and type drive the clan dropdown: narrow it to clans that still have a matching card
  // before re-running the search, so the user can't pick a clan with no results.
  const onDrivingFilterChange = async () => {
    await updateClanFilter();
    searchCards();
  };
  $('formatFilter').addEventListener('change', onDrivingFilterChange);
  $('typeFilter').addEventListener('change', onDrivingFilterChange);
  $('clanFilter').addEventListener('change', searchCards);

  $('helpBtn').addEventListener('click', toggleHelp);
  $('addBtn').addEventListener('click', doAddSelectedToDeck);
  $('removeBtn').addEventListener('click', doRemoveSelectedFromDeck);
  $('clearBtn').addEventListener('click', doClearDeck);
  $('exportBtn').addEventListener('click', doExportDeck);
  $('printBtn').addEventListener('click', () => printDeck(getDeck(), IMG, API));
  $('importBtn').addEventListener('click', () => $('importFileInput').click());
  $('saveOnlineBtn').addEventListener('click', doSaveOnline);
  $('myDecksBtn').addEventListener('click', doToggleMyDecks);
  const persistDeckMeta = debounce(persistDeck, 400);
  $('deckNameInput').addEventListener('input', () => {
    $('deckNameInput').closest('.deck-name-row').classList.remove('shake');
    persistDeckMeta();
  });
  $('deckAuthorInput').addEventListener('input', persistDeckMeta);
  $('importFileInput').addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    file.text().then((text) => doImportDeck(text));
    e.target.value = '';
  });

  await populateFilters();
  searchCards();

  // Restore an in-progress deck saved before the user navigated away. Runs through the import path
  // (re-resolving cards and recompositing custom art) now that the card DB is reachable.
  const saved = loadDeckSnapshot();
  if (saved) {
    try {
      await doImportDeck(saved, { silent: true });
    } catch (e) {
      console.error('Failed to restore saved deck:', e);
    }
  }

  refreshAccount();
}

function toggleHelp() {
  $('searchHelp').classList.toggle('hidden');
}

// Whether a deck can be saved to / loaded from an account. Identity and account management live in
// the nav widget and the settings page; here we only need to know if a session exists.
let currentUser = null;

// Transient feedback for a save or load action (empty otherwise — no persistent status line).
function setAccountStatus(text) {
  $('accountStatus').textContent = text;
}

async function refreshAccount() {
  currentUser = await getMe();
}

// The same YAML the Export and autosave paths produce, or null with a nudge if the deck is unnamed
// (a saved deck must be findable by name).
function currentDeckYaml() {
  const name = requireDeckName();
  if (!name) return null;
  return { name, yaml: serializeDeck(getDeck(), { name, author: $('deckAuthorInput').value.trim() }) };
}

async function doSaveOnline() {
  if (!currentUser) {
    window.location.href = '/auth/login';
    return;
  }
  const deck = currentDeckYaml();
  if (!deck) return;
  setAccountStatus('Saving to your account…');
  const result = await saveDeck({ name: deck.name, yaml: deck.yaml });
  setAccountStatus(result.ok ? `Saved to your account as “${result.deck.name}”` : result.error);
}

async function doToggleMyDecks() {
  const panel = $('myDecksPanel');
  if (!panel.classList.contains('hidden')) {
    panel.classList.add('hidden');
    return;
  }
  if (!currentUser) {
    window.location.href = '/auth/login';
    return;
  }
  renderMyDecksPanel(await listMyDecks());
  panel.classList.remove('hidden');
}

function renderMyDecksPanel(decks) {
  const panel = $('myDecksPanel');
  panel.replaceChildren();
  if (decks.length === 0) {
    const empty = document.createElement('p');
    empty.className = 'my-decks-empty';
    empty.textContent = 'No saved decks yet — save one with “Save online”.';
    panel.append(empty);
    return;
  }
  for (const deck of decks) {
    panel.append(myDeckRow(deck));
  }
}

function myDeckRow(deck) {
  const row = document.createElement('div');
  row.className = 'my-decks-row';

  const load = document.createElement('button');
  load.className = 'btn-small';
  load.textContent = `${deck.name} (${deck.dynasty_count}D / ${deck.fate_count}F)`;
  load.title = 'Load this deck into the builder';
  load.addEventListener('click', () => loadMyDeck(deck.slug));

  const remove = document.createElement('button');
  remove.className = 'btn-small btn-danger';
  remove.textContent = '✕';
  remove.title = 'Delete this saved deck';
  remove.addEventListener('click', () => removeMyDeck(deck.slug));

  row.append(load, remove);
  return row;
}

async function loadMyDeck(slug) {
  const shared = await fetchSharedDeck(slug);
  if (!shared) {
    setAccountStatus('Could not load that deck');
    return;
  }
  await doImportDeck(shared.yaml);
  $('myDecksPanel').classList.add('hidden');
  setAccountStatus(`Loaded “${shared.deck.name}” from your account`);
}

async function removeMyDeck(slug) {
  if (await deleteDeck(slug)) {
    renderMyDecksPanel(await listMyDecks());
  }
}

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
    const [formats, clans, types] = await Promise.all([
      fetchJSON(`${API}/formats`),
      fetchJSON(`${API}/clans`),
      fetchJSON(`${API}/card-types`),
    ]);
    const arcs = formats.arcs || [];
    const other = formats.other || [];
    fill($('formatFilter'), arcs);
    if (arcs.length > 0 && other.length > 0) addSeparator($('formatFilter'));
    fill($('formatFilter'), other);
    fill($('clanFilter'), clans.clans || []);
    fill($('typeFilter'), types.card_types || []);
  } catch (e) {
    console.error('Failed to populate filters:', e);
  }
}

// Rebuild the clan dropdown from the clans still reachable under the current format/type selection,
// keeping the chosen clan if it survives and falling back to "All Clans" if it no longer matches.
async function updateClanFilter() {
  const clanEl = $('clanFilter');
  const current = clanEl.value;
  const params = new URLSearchParams();
  const format = $('formatFilter').value;
  const cardType = $('typeFilter').value;
  if (format) params.set('format', format);
  if (cardType) params.set('card_type', cardType);
  let clans;
  try {
    const data = await fetchJSON(`${API}/clans?${params}`);
    clans = data.clans || [];
  } catch (e) {
    console.error('Failed to update clan filter:', e);
    return;
  }
  clanEl.innerHTML = '';
  const allOpt = document.createElement('option');
  allOpt.value = '';
  allOpt.textContent = 'All Clans';
  clanEl.appendChild(allOpt);
  clans.forEach((clan) => {
    const opt = document.createElement('option');
    opt.value = clan;
    opt.textContent = clan;
    clanEl.appendChild(opt);
  });
  clanEl.value = clans.includes(current) ? current : '';
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
  const clan = $('clanFilter').value;
  const cardType = $('typeFilter').value;

  if (search) params.set('search', search);
  if (format) params.set('format', format);
  if (clan) params.set('clan', clan);
  if (cardType) params.set('card_type', cardType);
  params.set('limit', LIMIT);
  params.set('offset', offset);

  try {
    const data = await fetchJSON(`${API}/cards?${params}`);
    updateResults(data.cards, data.has_more, offset > 0);
    $('filteredCount').textContent = data.total;
    renderCardList();
  } catch (e) {
    console.error('Failed to fetch cards:', e);
    setFetching(false);
  }
}

// Snapshot the live deck to localStorage so it survives navigation, storing the same YAML that
// Export produces and restoring it on load through the import path.
function persistDeck() {
  const name = $('deckNameInput').value.trim();
  const author = $('deckAuthorInput').value.trim();
  const snapshot = deckSnapshot(getDeck(), name, author);
  if (snapshot) saveDeckSnapshot(snapshot);
  else clearDeckSnapshot();
}

function doAddSelectedToDeck() {
  const card = getSelectedCard();
  if (!card) return;
  const side = deckSide(card);
  const active = getCurrentPrint();
  if (active?.isCustom) {
    addCustomPrint(side, card, active.print_id, {
      set_name: active.set_name || '',
      isCustom: true,
      art: active.art,
      recipe: active.recipe,
      dataUrl: active.dataUrl,
    });
  } else {
    addCard(card.card_id, side, card, getCurrentPrintId() || 0, getCurrentSetName());
  }
  renderDeckLists();
  persistDeck();
}

function onBorrowArt(card, recipientPrint) {
  if (!card || !recipientPrint) return;
  openBorrowArt({
    recipientCard: card,
    recipientPrint,
    imgBase: IMG,
    api: API,
    // The chosen art becomes the active print in the cycle; the user still hits Add to commit it.
    onUse: (customPrint) => addCustomPrintToCycle(customPrint),
  });
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
  persistDeck();
}

function doClearDeck() {
  clearDeck();
  setSelectedDeckCard(null);
  renderDeckLists();
  clearDeckSnapshot();
}

// The trimmed deck name, or null after nudging the (required) name field when it's empty.
function requireDeckName() {
  const input = $('deckNameInput');
  const name = input.value.trim();
  if (name) return name;
  input.focus();
  const row = input.closest('.deck-name-row');
  row.classList.remove('shake');
  void row.offsetWidth;
  row.classList.add('shake');
  return null;
}

function doExportDeck() {
  const name = requireDeckName();
  if (!name) return;
  const author = $('deckAuthorInput').value.trim();
  const yaml = serializeDeck(getDeck(), { name, author });
  const filename = name.toLowerCase().replace(/[^a-z0-9]+/g, '_') + '.yaml';
  const blob = new Blob([yaml], { type: 'text/yaml' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

async function doImportDeck(text, { silent = false } = {}) {
  const parsed = parseDeckYaml(text);

  const allEntries = [...parsed.pre_game, ...parsed.dynasty, ...parsed.fate];
  const names = new Set();
  allEntries.forEach((e) => {
    names.add(stripUnique(e.name)); // a hand-edited deck may carry the ◆ unique marker
    if (e.art?.donorName) names.add(stripUnique(e.art.donorName));
  });
  const uniqueNames = [...names];
  if (uniqueNames.length === 0) return;

  const params = new URLSearchParams();
  uniqueNames.forEach((n) => params.append('name', n));

  let cardsByName = {};
  try {
    const data = await fetchJSON(`${API}/cards/lookup?${params}`);
    cardsByName = data.cards || {};
  } catch (e) {
    console.error('Import lookup failed:', e);
    alert('Import failed: could not reach the card database.');
    return;
  }

  clearDeck();
  setSelectedDeckCard(null);

  const SIDE_MAP = { pre_game: 'PRE_GAME', dynasty: 'DYNASTY', fate: 'FATE' };
  const unresolved = [];

  for (const [section, entries] of Object.entries({
    pre_game: parsed.pre_game,
    dynasty: parsed.dynasty,
    fate: parsed.fate,
  })) {
    const side = SIDE_MAP[section];
    for (const entry of entries) {
      const card = cardsByName[stripUnique(entry.name).toLowerCase()];
      if (!card) {
        unresolved.push(entry.name);
        continue;
      }
      const prints = card.prints || [];
      const matchedPrint = entry.setName
        ? (prints.find((p) => p.set_name === entry.setName) ?? prints[0])
        : prints[0];
      const printId = matchedPrint ? matchedPrint.print_id : 0;
      const setName = matchedPrint ? matchedPrint.set_name : '';

      if (entry.art && (await addImportedCustom(side, card, matchedPrint, entry, cardsByName, unresolved))) {
        continue;
      }
      for (let i = 0; i < entry.count; i++) {
        addCard(card.card_id, side, card, printId, setName);
      }
    }
  }

  $('deckNameInput').value = parsed.name;
  $('deckAuthorInput').value = parsed.author;
  renderDeckLists();
  renderCardList();
  persistDeck();

  if (unresolved.length > 0 && !silent) {
    alert(`Import complete.\n\nCould not find ${unresolved.length} card(s):\n${unresolved.join('\n')}`);
  }
}

// Re-create a custom (art-swap) print from an imported {art:} entry: resolve the donor, fetch both
// prints' era/layout, recompose the art client-side. Returns true on success, false to fall back to
// a plain print.
async function addImportedCustom(side, recipientCard, recipientPrint, entry, cardsByName, unresolved) {
  const donorCard = cardsByName[stripUnique(entry.art.donorName || '').toLowerCase()];
  if (!recipientPrint || !donorCard) {
    unresolved.push(entry.art.donorName || '(art donor)');
    return false;
  }
  const donorPrints = donorCard.prints || [];
  const donorPrint = entry.art.donorSet
    ? (donorPrints.find((p) => p.set_name === entry.art.donorSet) ?? donorPrints[0])
    : donorPrints[0];
  if (!donorPrint) {
    unresolved.push(entry.art.donorName);
    return false;
  }

  let rDetail, dDetail;
  try {
    [rDetail, dDetail] = await Promise.all([
      fetchJSON(`${API}/cards/${recipientCard.card_id}`),
      fetchJSON(`${API}/cards/${donorCard.card_id}`),
    ]);
  } catch (_) {
    return false;
  }
  const rp = (rDetail.prints || []).find((p) => p.print_id === recipientPrint.print_id);
  const dp = (dDetail.prints || []).find((p) => p.print_id === donorPrint.print_id);
  if (!rp?.image_path || !dp?.image_path) return false;

  let dataUrl;
  try {
    dataUrl = await buildCompositeDataURL(
      {
        recipientImagePath: rp.image_path,
        recipientEra: rp.era,
        recipientLayout: rp.layout_type,
        recipientKeywords: recipientCard.keywords,
        donorImagePath: dp.image_path,
        donorEra: dp.era,
        donorLayout: dp.layout_type,
      },
      IMG,
    );
  } catch (_) {
    return false;
  }

  const recipe = { recipientPrintId: rp.print_id, donorCardId: donorCard.card_id, donorPrintId: dp.print_id };
  const printData = { set_name: rp.set_name || '', isCustom: true, art: entry.art, recipe, dataUrl };
  const printId = customPrintId(recipe);
  for (let i = 0; i < entry.count; i++) {
    addCustomPrint(side, recipientCard, printId, printData);
  }
  return true;
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
  let idx = sel ? results.findIndex((c) => c.card_id === sel.card_id) : -1;
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
  // A custom print's synthetic id isn't in the prints API; render its cached composite directly,
  // mirroring the click handler.
  const printData = item.printId != null ? getDeck()[item.side]?.[item.id]?.prints?.[item.printId] : null;
  if (printData?.isCustom) showCustomPreview(item.card, printData);
  else showPreview(item.card, item.printId, API);
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
