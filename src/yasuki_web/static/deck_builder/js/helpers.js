export const $ = (id) => document.getElementById(id);

export function esc(s) {
  return s
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

export function displayName(card) {
  const title = card.extended_title || card.name;
  return card.is_unique ? '\u25C6 ' + title : title;
}

// The deck-builder bucket a card belongs to: FATE, DYNASTY, or PRE_GAME (strongholds, senseis,
// anything not in the Fate or Dynasty deck). Derived from the card's `decks` array.
export function deckSide(card) {
  const decks = card.decks || [];
  if (decks.includes('Fate')) return 'FATE';
  if (decks.includes('Dynasty')) return 'DYNASTY';
  return 'PRE_GAME';
}

// Primary deck label for the card-list side tag (e.g. "Fate", "Dynasty", "Pre-Game").
export function primaryDeck(card) {
  return (card.decks || [])[0] || '';
}

export function pluralize(word) {
  const w = word.toLowerCase();
  let result;
  if (w.endsWith('y')) result = w.slice(0, -1) + 'ies';
  else if (w.endsWith('s') || w.endsWith('sh') || w.endsWith('ch') || w.endsWith('x') || w.endsWith('z'))
    result = w + 'es';
  else result = w + 's';
  if (word[0] === word[0].toUpperCase()) result = result[0].toUpperCase() + result.slice(1);
  return result;
}

export function debounce(fn, ms) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

export function titleCase(s) {
  return s
    .toLowerCase()
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

export function scrollToSelected(containerId, selector) {
  const container = $(containerId);
  const item = container.querySelector(selector);
  if (item) item.scrollIntoView({ block: 'nearest' });
}
