import { $, esc, displayName } from './helpers.js';
import { fetchJSON } from './api.js';

let currentPrints = [];
let currentPrintIndex = 0;
let _imgBase = '/images';

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
    html +=
      '<img class="preview-img" src="' +
      esc(imgSrc) +
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
  if (prevBtn) prevBtn.addEventListener('click', prevPrint);
  if (nextBtn) nextBtn.addEventListener('click', nextPrint);
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

  const imgEl = document.querySelector('.preview-img');
  if (imgEl) {
    if (print.image_path) {
      imgEl.src = _imgBase + '/' + print.image_path;
      imgEl.style.display = '';
    } else {
      imgEl.style.display = 'none';
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
