import { $, esc, displayName } from './helpers.js';
import { fetchJSON } from './api.js';

let currentPrints = [];
let currentPrintIndex = 0;
let _imgBase = '/images';
let _flipped = false;
let _currentCard = null;

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
  const type = (card.type || '').toLowerCase();
  const path = DEFAULT_BY_TYPE[type];
  return path ? _imgBase + '/' + path : null;
}

export function initPreview(imgBase) {
  _imgBase = imgBase;
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
  const el = $('preview');

  currentPrints = [];
  currentPrintIndex = 0;
  _flipped = false;
  _currentCard = card;
  try {
    const detail = await fetchJSON(`${apiBase}/cards/${card.id}`);
    currentPrints = detail.prints || [];
  } catch (_) {
    /* ignore */
  }

  if (preferredPrintId != null && currentPrints.length > 0) {
    const idx = currentPrints.findIndex((p) => p.print_id === preferredPrintId);
    if (idx >= 0) currentPrintIndex = idx;
  }

  const currentPrint = currentPrints[currentPrintIndex];
  const imgPath = currentPrint ? currentPrint.image_path : card.image_path;
  const imgSrc = imgPath ? `${_imgBase}/${imgPath}` : null;
  const fb = fallbackSrc(card);

  const stats = [
    ['Type', card.type],
    ['Clan', card.clan],
    ['Deck', card.side],
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

  let html = '';
  if (imgSrc) {
    const onerror = fb
      ? "this.onerror=null;this.src='" + esc(fb) + "'"
      : "this.style.display='none'";
    html +=
      '<img class="preview-img" src="' +
      esc(imgSrc) +
      '" alt="' +
      esc(card.name) +
      '" onerror="' +
      onerror +
      '">';
  } else if (fb) {
    html +=
      '<img class="preview-img" src="' +
      esc(fb) +
      '" alt="' +
      esc(card.name) +
      "\" onerror=\"this.style.display='none'\">";
  } else {
    html += '<div class="preview-placeholder">No image available</div>';
  }

  if (currentPrints.length > 0) {
    const setName = currentPrint ? currentPrint.set_name || '' : '';
    const disabled = currentPrints.length <= 1 ? ' disabled' : '';
    html += '<div class="print-nav">';
    html += '<button id="prevPrintBtn"' + disabled + '>◀</button>';
    html +=
      '<span class="print-info">' +
      esc(setName) +
      ' (' +
      (currentPrintIndex + 1) +
      '/' +
      currentPrints.length +
      ')</span>';
    html += '<button id="nextPrintBtn"' + disabled + '>▶</button>';
    html += '<button id="flipBtn" title="Flip card image">🔄</button>';
    html += '</div>';
  } else {
    html += '<div class="print-nav">';
    html += '<button id="flipBtn" title="Flip card image">🔄</button>';
    html += '</div>';
  }

  html += '<div class="preview-name">' + esc(displayName(card)) + '</div>';
  html += '<div class="preview-stats"><table>';
  stats.forEach((pair) => {
    html += '<tr><td>' + esc(pair[0]) + '</td><td>' + esc(String(pair[1])) + '</td></tr>';
  });
  html += '</table></div>';
  if (currentPrint && currentPrint.flavor_text) {
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
}

function toggleFlip() {
  _flipped = !_flipped;
  const imgEl = document.querySelector('.preview-img');
  if (imgEl) {
    imgEl.classList.toggle('preview-img-flipped', _flipped);
  }
}

function prevPrint() {
  if (currentPrints.length <= 1) return;
  currentPrintIndex = (currentPrintIndex - 1 + currentPrints.length) % currentPrints.length;
  updatePreviewPrint();
}

function nextPrint() {
  if (currentPrints.length <= 1) return;
  currentPrintIndex = (currentPrintIndex + 1) % currentPrints.length;
  updatePreviewPrint();
}

function updatePreviewPrint() {
  const print = currentPrints[currentPrintIndex];
  if (!print) return;

  _flipped = false;

  const imgEl = document.querySelector('.preview-img');
  if (imgEl) {
    imgEl.classList.remove('preview-img-flipped');
    if (print.image_path) {
      imgEl.src = _imgBase + '/' + print.image_path;
      imgEl.style.display = '';
    } else {
      const fb = _currentCard ? fallbackSrc(_currentCard) : null;
      if (fb) {
        imgEl.src = fb;
        imgEl.style.display = '';
      } else {
        imgEl.style.display = 'none';
      }
    }
  }

  const infoEl = document.querySelector('.print-info');
  if (infoEl) {
    infoEl.textContent =
      (print.set_name || 'Unknown') +
      ' (' +
      (currentPrintIndex + 1) +
      '/' +
      currentPrints.length +
      ')';
  }

  const flavorEl = document.querySelector('.preview-flavor');
  if (flavorEl) {
    if (print.flavor_text) {
      flavorEl.textContent = print.flavor_text;
      flavorEl.style.display = '';
    } else {
      flavorEl.style.display = 'none';
    }
  }
}
