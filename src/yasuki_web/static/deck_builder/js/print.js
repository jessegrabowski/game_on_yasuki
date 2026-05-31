import { fetchJSON } from './api.js';

// Client-side print: lay every card copy out at actual size (63.5 x 90 mm, 8 per landscape Letter
// page) and hand off to the browser's Save-as-PDF. Mirrors the desktop deck_pdf spec. Printing
// only displays <img> elements, so unlike the borrow-art canvas it needs no cross-origin image
// access — real prints load straight from the image host.
const SIDE_ORDER = ['DYNASTY', 'FATE', 'PRE_GAME'];
const PER_PAGE = 8;

// Ordered image source per card copy: sides in play order, cards by name, each print expanded by
// quantity. Custom art-swap prints use their pre-composited data URL; real prints resolve through
// printImageMap (print_id -> served path), falling back to the card's default image.
export function buildImageList(deck, imgBase, printImageMap) {
  const images = [];
  for (const side of SIDE_ORDER) {
    const bucket = deck[side] || {};
    const entries = Object.values(bucket).sort((a, b) => a.card.name.localeCompare(b.card.name));
    for (const entry of entries) {
      for (const printId in entry.prints) {
        const print = entry.prints[printId];
        let src;
        if (print.isCustom) {
          src = print.dataUrl;
        } else {
          const path = printImageMap.get(parseInt(printId)) || entry.card.image_path;
          src = path ? `${imgBase}/${path}` : null;
        }
        if (src) for (let i = 0; i < print.qty; i++) images.push(src);
      }
    }
  }
  return images;
}

async function resolvePrintImages(deck, api) {
  const names = new Set();
  for (const side of SIDE_ORDER) {
    const bucket = deck[side] || {};
    for (const id in bucket) names.add(bucket[id].card.name);
  }
  const map = new Map();
  if (names.size === 0) return map;
  const params = new URLSearchParams();
  names.forEach((n) => params.append('name', n));
  let cards;
  try {
    cards = (await fetchJSON(`${api}/cards/lookup?${params}`)).cards || {};
  } catch (_) {
    return map; // fall back to each card's default image
  }
  for (const key in cards) {
    for (const print of cards[key].prints || []) {
      if (print.image_path) map.set(print.print_id, print.image_path);
    }
  }
  return map;
}

export async function printDeck(deck, imgBase, api) {
  const printImageMap = await resolvePrintImages(deck, api);
  const images = buildImageList(deck, imgBase, printImageMap);
  if (images.length === 0) {
    alert('Add some cards to the deck first.');
    return;
  }

  const sheet = document.createElement('div');
  sheet.id = 'printSheet';
  let page = null;
  const loads = [];
  images.forEach((src, i) => {
    if (i % PER_PAGE === 0) {
      page = document.createElement('div');
      page.className = 'print-page';
      sheet.appendChild(page);
    }
    const img = document.createElement('img');
    img.className = 'print-card';
    loads.push(new Promise((resolve) => {
      img.onload = resolve;
      img.onerror = resolve;
    }));
    img.src = src;
    page.appendChild(img);
  });
  document.body.appendChild(sheet);

  await Promise.all(loads);

  const cleanup = () => {
    sheet.remove();
    window.removeEventListener('afterprint', cleanup);
  };
  window.addEventListener('afterprint', cleanup);
  window.print();
}
