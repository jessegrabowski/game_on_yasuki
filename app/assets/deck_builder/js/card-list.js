import { $, displayName } from './helpers.js';

let allResults = [];
let hasMore = false;
let selectedCard = null;

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

export function initCardList({ onSelect, onLoadMore }) {
  _onSelect = onSelect;
  _onLoadMore = onLoadMore;
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

export function renderCardList() {
  const el = $('cardList');
  el.innerHTML = '';
  allResults.forEach((card) => {
    const div = document.createElement('div');
    div.className =
      'card-list-item' + (selectedCard && selectedCard.id === card.id ? ' selected' : '');
    div._cardId = card.id;
    const nameSpan = document.createElement('span');
    nameSpan.textContent = displayName(card);
    const sideSpan = document.createElement('span');
    sideSpan.className = 'side-tag ' + (card.side || '').toLowerCase();
    sideSpan.textContent = card.side || '?';
    div.appendChild(nameSpan);
    div.appendChild(sideSpan);
    div.addEventListener('click', () => selectCard(card));
    div.addEventListener('dblclick', () => {
      selectCard(card);
      _onSelect(card);
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
  selectedCard = card;

  $('cardList')
    .querySelectorAll('.card-list-item')
    .forEach((el) => {
      el.classList.toggle('selected', el._cardId === card.id);
    });
  document
    .querySelectorAll('.deck-item, .deck-sub-item')
    .forEach((el) => el.classList.remove('selected'));

  _onSelect(card);
}
