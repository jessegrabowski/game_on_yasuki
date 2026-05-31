import { $, esc, displayName } from './helpers.js';
import { fetchJSON } from './api.js';

let currentPrints = [];
let currentPrintIndex = 0;
let _imgBase = '/images';
let _flipped = false;
let _currentCard = null;
let _cardBacks = null;
let _frontSrc = null;
let _backSrc = null;
let _onPrintChange = () => {};
let _onBorrowArt = () => {};

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

function fallbackSrc(card) {
  const type = ((card.types || [])[0] || '').toLowerCase();
  const path = DEFAULT_BY_TYPE[type];
  return path ? _imgBase + '/' + path : null;
}

async function loadCardBacks(apiBase) {
  if (_cardBacks) return;
  try {
    _cardBacks = (await fetchJSON(`${apiBase}/card-backs`)).backs || {};
  } catch (_) {
    _cardBacks = {};
  }
}

// The reverse image for a print: its printed back face if the card is double-sided, otherwise the
// generic back for the card's deck and era (Fate cards show the Fate back; an old-era print shows
// the old back, a modern one the new back).
function backSrc(card, print) {
  if (print && print.back_image_path) return `${_imgBase}/${print.back_image_path}`;
  const deck = (card.decks || []).includes('Fate') ? 'Fate' : 'Dynasty';
  const backs = _cardBacks?.[deck];
  if (!backs) return null;
  const key = print?.back_era || 'new';
  const path = backs[key] || backs.new || backs.old;
  return path ? `${_imgBase}/${path}` : null;
}

export function initPreview(imgBase, onPrintChange, onBorrowArt) {
  _imgBase = imgBase;
  _cardBacks = null;
  if (onPrintChange) _onPrintChange = onPrintChange;
  if (onBorrowArt) _onBorrowArt = onBorrowArt;
}

// The full print object currently shown (with era/layout_type/image_path), or null. Used as the
// recipient when borrowing art.
export function getCurrentPrint() {
  return currentPrints.length > 0 ? currentPrints[currentPrintIndex] : null;
}

// Front and back image URLs for the print currently shown, in the order the flip button toggles.
export function getCurrentFaces() {
  return { front: _frontSrc, back: _backSrc };
}

export function getCurrentPrintId() {
  if (currentPrints.length > 0) return currentPrints[currentPrintIndex].print_id;
  return null;
}

export function getCurrentSetName() {
  if (currentPrints.length > 0) return currentPrints[currentPrintIndex].set_name || '';
  return '';
}

export async function showPreview(card, preferredPrintId, apiBase) {
  currentPrints = [];
  currentPrintIndex = 0;
  _flipped = false;
  _currentCard = card;
  try {
    const detail = await fetchJSON(`${apiBase}/cards/${card.card_id}`);
    currentPrints = detail.prints || [];
  } catch (_) {
    /* ignore */
  }
  await loadCardBacks(apiBase);

  if (preferredPrintId != null && currentPrints.length > 0) {
    const idx = currentPrints.findIndex((p) => p.print_id === preferredPrintId);
    if (idx >= 0) currentPrintIndex = idx;
  }
  renderPreview();
}

// Append a custom (art-swap) print to the current card's print cycle and make it the active choice,
// so the user reviews it (and can cycle back to the real prints) before adding it to the deck.
export function addCustomPrintToCycle(customPrint) {
  currentPrints = currentPrints.filter((p) => p.print_id !== customPrint.print_id);
  currentPrints.push(customPrint);
  currentPrintIndex = currentPrints.length - 1;
  _flipped = false;
  renderPreview();
}

function renderPreview() {
  const el = $('preview');
  const card = _currentCard;
  const currentPrint = currentPrints[currentPrintIndex];
  const isCustom = !!currentPrint?.isCustom;
  const fb = fallbackSrc(card);

  let imgSrc;
  if (isCustom) {
    imgSrc = currentPrint.dataUrl;
  } else {
    const imgPath = currentPrint ? currentPrint.image_path : card.image_path;
    imgSrc = imgPath ? `${_imgBase}/${imgPath}` : null;
  }
  _frontSrc = imgSrc || fb;
  // A custom print flips to the recipient print's back (its era), since the deck back is the card's.
  _backSrc = backSrc(card, isCustom ? currentPrint.recipientPrint : currentPrint);

  let html = '';
  if (isCustom) {
    html += '<img class="preview-img" src="' + esc(imgSrc) + '" alt="' + esc(card.name) + '">';
  } else if (imgSrc) {
    const onerror = fb
      ? "this.onerror=null;this.src='" + esc(fb) + "'"
      : "this.style.display='none'";
    html +=
      '<img class="preview-img" src="' + esc(imgSrc) + '" alt="' + esc(card.name) + '" onerror="' + onerror + '">';
  } else if (fb) {
    html +=
      '<img class="preview-img" src="' + esc(fb) + '" alt="' + esc(card.name) + "\" onerror=\"this.style.display='none'\">";
  } else {
    html += '<div class="preview-placeholder">No image available</div>';
  }

  if (currentPrints.length > 0) {
    const label = isCustom ? 'Custom · ' + (currentPrint.art?.donorName || 'art') : currentPrint?.set_name || '';
    const disabled = currentPrints.length <= 1 ? ' disabled' : '';
    html += '<div class="print-nav">';
    html += '<button id="prevPrintBtn"' + disabled + '>◀</button>';
    html +=
      '<span class="print-info">' + esc(label) + ' (' + (currentPrintIndex + 1) + '/' + currentPrints.length + ')</span>';
    html += '<button id="nextPrintBtn"' + disabled + '>▶</button>';
    html += '<button id="flipBtn" title="Flip card image">🔄</button>';
    html += '<button id="borrowArtBtn" title="Borrow art from another card">🎨</button>';
    html += '</div>';
  } else {
    html += '<div class="print-nav"><button id="flipBtn" title="Flip card image">🔄</button></div>';
  }

  html += '<div class="preview-name">' + esc(displayName(card)) + '</div>';
  html += '<div class="preview-stats"><table>';
  _statRows(card).forEach((pair) => {
    html += '<tr><td>' + esc(pair[0]) + '</td><td>' + esc(String(pair[1])) + '</td></tr>';
  });
  html += '</table></div>';
  if (!isCustom && currentPrint?.flavor_text) {
    html += '<div class="preview-flavor">' + esc(currentPrint.flavor_text) + '</div>';
  }
  if (card.text) {
    html += '<div class="preview-rules">' + esc(card.text) + '</div>';
  }
  el.innerHTML = html;

  const prevBtn = $('prevPrintBtn');
  const nextBtn = $('nextPrintBtn');
  const flipBtn = $('flipBtn');
  if (prevBtn) prevBtn.addEventListener('click', prevPrint);
  if (nextBtn) nextBtn.addEventListener('click', nextPrint);
  if (flipBtn) flipBtn.addEventListener('click', toggleFlip);
  const borrowBtn = $('borrowArtBtn');
  if (borrowBtn)
    borrowBtn.addEventListener('click', () => {
      const print = currentPrints[currentPrintIndex];
      const recipientPrint = print?.isCustom ? print.recipientPrint : print;
      _onBorrowArt(_currentCard, recipientPrint);
    });
}

// Render a custom (art-swap) print: the pre-rendered composite plus the card's stats. Used when a
// custom print is selected from the deck (it isn't in the prints API).
export function showCustomPreview(card, printData) {
  const el = $('preview');
  const stats = _statRows(card);
  let html =
    '<img class="preview-img" src="' + esc(printData.dataUrl) + '" alt="' + esc(card.name) + '">';
  const donor = printData.art ? printData.art.donorName : '';
  html += '<div class="print-nav"><span class="print-info">Custom art &mdash; ' + esc(donor) + '</span></div>';
  html += '<div class="preview-name">' + esc(displayName(card)) + '</div>';
  html += '<div class="preview-stats"><table>';
  stats.forEach((pair) => {
    html += '<tr><td>' + esc(pair[0]) + '</td><td>' + esc(String(pair[1])) + '</td></tr>';
  });
  html += '</table></div>';
  if (card.text) html += '<div class="preview-rules">' + esc(card.text) + '</div>';
  el.innerHTML = html;
}

function _statRows(card) {
  return [
    ['Type', (card.types || []).join(', ')],
    ['Clan', (card.clans || []).join(', ')],
    ['Deck', (card.decks || []).join(', ')],
    ['Force', card.force],
    ['Chi', card.chi],
    ['Gold Cost', card.gold_cost],
    ['Honor Req', card.honor_requirement],
    ['Personal Honor', card.personal_honor],
    ['Province Str', card.province_strength],
    ['Gold Prod', card.gold_production],
    ['Starting Honor', card.starting_honor],
    ['Focus', card.focus],
  ].filter((pair) => pair[1] != null && pair[1] !== '');
}

function toggleFlip() {
  if (!_backSrc) return;
  _flipped = !_flipped;
  const imgEl = document.querySelector('.preview-img');
  if (imgEl) imgEl.src = _flipped ? _backSrc : _frontSrc;
}

function prevPrint() {
  if (currentPrints.length <= 1) return;
  currentPrintIndex = (currentPrintIndex - 1 + currentPrints.length) % currentPrints.length;
  afterPrintChange();
}

function nextPrint() {
  if (currentPrints.length <= 1) return;
  currentPrintIndex = (currentPrintIndex + 1) % currentPrints.length;
  afterPrintChange();
}

function afterPrintChange() {
  const print = currentPrints[currentPrintIndex];
  if (_currentCard && print && !print.isCustom) {
    _onPrintChange(_currentCard, print.print_id, print.set_name || '');
  }
  _flipped = false;
  renderPreview();
}
