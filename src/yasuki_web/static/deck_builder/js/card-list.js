import { $, displayName, deckSide, primaryDeck } from './helpers.js';

let allResults = [];
let hasMore = false;
let selectedCard = null;
const printChoices = new Map();

const scrollObserver = new IntersectionObserver(
  (entries) => {
    if (entries[0].isIntersecting && hasMore && !_fetching) {
      _onLoadMore();
    }
  },
  { root: $('cardList'), threshold: 0 },
);

let _fetching = false;
let _onLoadMore = () => {};
let _onSelect = () => {};
let _onDblClick = () => {};

export function initCardList({ onSelect, onLoadMore, onDblClick }) {
  _onSelect = onSelect;
  _onLoadMore = onLoadMore;
  if (onDblClick) _onDblClick = onDblClick;
}

export function getSelectedCard() {
  return selectedCard;
}

export function setSelectedCard(card) {
  selectedCard = card;
}

export function getAllResults() {
  return allResults;
}

export function updateResults(cards, more, append) {
  if (!append) allResults = [];
  allResults.push(...cards);
  hasMore = more;
  _fetching = false;
}

export function setFetching(v) {
  _fetching = v;
}

export function isFetching() {
  return _fetching;
}

export function getPrintChoice(cardId) {
  return printChoices.get(cardId);
}

export function recordPrintChoice(card, printId, setName) {
  printChoices.set(card.card_id, { printId, setName });
  for (const el of $('cardList').querySelectorAll('.card-list-item')) {
    if (el._cardId === card.card_id) {
      el.children[0].textContent = cardLabel(card);
      break;
    }
  }
}

function cardLabel(card) {
  const choice = printChoices.get(card.card_id);
  const name = displayName(card);
  return choice && choice.setName ? `${name} [${choice.setName}]` : name;
}

export function renderCardList() {
  const el = $('cardList');
  el.innerHTML = '';
  allResults.forEach((card) => {
    const div = document.createElement('div');
    div.className =
      'card-list-item' +
      (selectedCard && selectedCard.card_id === card.card_id ? ' selected' : '');
    div._cardId = card.card_id;
    const nameSpan = document.createElement('span');
    nameSpan.textContent = cardLabel(card);
    const sideSpan = document.createElement('span');
    sideSpan.className = 'side-tag ' + deckSide(card).toLowerCase();
    sideSpan.textContent = primaryDeck(card) || '?';
    div.appendChild(nameSpan);
    div.appendChild(sideSpan);
    div.addEventListener('click', () => selectCard(card));
    div.addEventListener('dblclick', () => {
      selectCard(card);
      _onDblClick(card);
    });
    el.appendChild(div);
  });

  const sentinel = document.createElement('div');
  sentinel.id = 'scrollSentinel';
  sentinel.style.height = '1px';
  el.appendChild(sentinel);
  scrollObserver.disconnect();
  if (hasMore) scrollObserver.observe(sentinel);
}

export function selectCard(card) {
  // Re-selecting the shown card keeps its current print; only switching cards reloads the preview.
  const sameCard = selectedCard && selectedCard.card_id === card.card_id;
  selectedCard = card;

  $('cardList')
    .querySelectorAll('.card-list-item')
    .forEach((el) => {
      el.classList.toggle('selected', el._cardId === card.card_id);
    });
  document
    .querySelectorAll('.deck-item, .deck-sub-item')
    .forEach((el) => el.classList.remove('selected'));

  if (!sameCard) _onSelect(card);
}
