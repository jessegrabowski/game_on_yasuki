import { $, displayName, pluralize } from './helpers.js';
import { getDeck, deckEntryTotal } from './deck-state.js';

let selectedDeckCard = null;
let _onDeckSelect = () => {};
let _onDeckDblClick = () => {};

export function initDeckList({ onSelect, onDblClick }) {
  _onDeckSelect = onSelect;
  _onDeckDblClick = onDblClick;
}

export function getSelectedDeckCard() {
  return selectedDeckCard;
}

export function setSelectedDeckCard(val) {
  selectedDeckCard = val;
}

export function renderDeckLists() {
  renderDeckSide('DYNASTY', 'dynastyList', 'dynastyCount');
  renderDeckSide('FATE', 'fateList', 'fateCount');
  renderDeckSide('PRE_GAME', 'preGameList', 'preGameCount');
}

function renderDeckSide(side, listId, countId) {
  const el = $(listId);
  const bucket = getDeck()[side] || {};

  let total = 0;
  const cardsByType = {};

  for (const _id in bucket) {
    const _entry = bucket[_id];
    const qty = deckEntryTotal(_entry);
    total += qty;
    const type = (_entry.card.types || [])[0] || 'Unknown';
    if (!cardsByType[type]) cardsByType[type] = [];
    cardsByType[type].push({ id: _id, entry: _entry, qty });
  }

  $(countId).textContent = total;
  el.innerHTML = '';

  if (total === 0) {
    el.innerHTML = '<div class="empty-state">No cards added yet</div>';
    return;
  }

  Object.keys(cardsByType)
    .sort()
    .forEach((type) => {
      const cards = cardsByType[type];
      const typeTotal = cards.reduce((s, c) => s + c.qty, 0);

      const header = document.createElement('div');
      header.className = 'deck-type-header';
      header.textContent = typeTotal + '\u00D7 ' + pluralize(type);
      el.appendChild(header);

      cards.sort((a, b) => a.entry.card.name.localeCompare(b.entry.card.name));

      cards.forEach(({ id, entry, qty: cardQty }) => {
        const printEntries = Object.entries(entry.prints);

        if (printEntries.length === 1) {
          renderSinglePrintItem(el, side, id, entry, cardQty, printEntries[0]);
        } else {
          renderMultiPrintItem(el, side, id, entry, cardQty, printEntries);
        }
      });
    });
}

function renderSinglePrintItem(el, side, id, entry, cardQty, printEntry) {
  const [printIdStr, printData] = printEntry;
  const printId = parseInt(printIdStr);
  const div = document.createElement('div');
  const isSelected =
    selectedDeckCard && selectedDeckCard.side === side && selectedDeckCard.id === id;
  div.className = 'deck-item' + (isSelected ? ' selected' : '') + (printData.isCustom ? ' custom' : '');

  const nameSpan = document.createElement('span');
  const setTag = printData.isCustom
    ? ' [Custom: ' + (printData.art?.donorName || 'art') + ']'
    : printData.set_name
      ? ' [' + printData.set_name + ']'
      : '';
  nameSpan.textContent = displayName(entry.card) + setTag;
  const qtySpan = document.createElement('span');
  qtySpan.className = 'qty';
  qtySpan.textContent = '\u00D7' + cardQty;
  div.appendChild(qtySpan);
  div.appendChild(nameSpan);

  div._deckSide = side;
  div._deckId = id;
  div._printId = printId;
  div.addEventListener('click', function () {
    selectedDeckCard = { side, id, printId };
    _onDeckSelect(entry.card, printId, this);
  });
  div.addEventListener('dblclick', function () {
    selectedDeckCard = { side, id, printId };
    _onDeckDblClick();
  });
  el.appendChild(div);
}

function renderMultiPrintItem(el, side, id, entry, cardQty, printEntries) {
  const cardDiv = document.createElement('div');
  const isCardSelected =
    selectedDeckCard &&
    selectedDeckCard.side === side &&
    selectedDeckCard.id === id &&
    selectedDeckCard.printId == null;
  cardDiv.className = 'deck-item' + (isCardSelected ? ' selected' : '');

  const cNameSpan = document.createElement('span');
  cNameSpan.textContent = displayName(entry.card);
  const cQtySpan = document.createElement('span');
  cQtySpan.className = 'qty';
  cQtySpan.textContent = '\u00D7' + cardQty;
  cardDiv.appendChild(cQtySpan);
  cardDiv.appendChild(cNameSpan);

  cardDiv._deckSide = side;
  cardDiv._deckId = id;
  cardDiv._printId = null;
  cardDiv.addEventListener('click', function () {
    selectedDeckCard = { side, id, printId: null };
    _onDeckSelect(entry.card, null, this);
  });
  cardDiv.addEventListener('dblclick', function () {
    selectedDeckCard = { side, id, printId: null };
    _onDeckDblClick();
  });
  el.appendChild(cardDiv);

  printEntries
    .sort((a, b) => parseInt(a[0]) - parseInt(b[0]))
    .forEach(([pidStr, pData]) => {
      const pid = parseInt(pidStr);
      const subDiv = document.createElement('div');
      const isSubSelected =
        selectedDeckCard &&
        selectedDeckCard.side === side &&
        selectedDeckCard.id === id &&
        selectedDeckCard.printId === pid;
      subDiv.className =
        'deck-sub-item' + (isSubSelected ? ' selected' : '') + (pData.isCustom ? ' custom' : '');

      const subName = document.createElement('span');
      subName.textContent = pData.isCustom
        ? 'Custom: ' + (pData.art?.donorName || 'art')
        : pData.set_name || 'Unknown';
      const subQty = document.createElement('span');
      subQty.className = 'qty';
      subQty.textContent = '\u00D7' + pData.qty;
      subDiv.appendChild(subQty);
      subDiv.appendChild(subName);

      subDiv._deckSide = side;
      subDiv._deckId = id;
      subDiv._printId = pid;
      subDiv.addEventListener('click', function () {
        selectedDeckCard = { side, id, printId: pid };
        _onDeckSelect(entry.card, pid, this);
      });
      subDiv.addEventListener('dblclick', function () {
        selectedDeckCard = { side, id, printId: pid };
        _onDeckDblClick();
      });
      el.appendChild(subDiv);
    });
}

export function selectDeckItem(activeEl) {
  document
    .querySelectorAll('.deck-item, .deck-sub-item')
    .forEach((el) => el.classList.remove('selected'));
  activeEl.classList.add('selected');
  document
    .querySelectorAll('.card-list-item')
    .forEach((el) => el.classList.remove('selected'));
}
