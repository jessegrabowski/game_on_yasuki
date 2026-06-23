import { esc, fallbackSrc, fetchImageBase } from './card-common.js';

const STAT_LABELS = [
  ['force', 'Force'],
  ['chi', 'Chi'],
  ['gold_cost', 'Cost'],
  ['focus', 'Focus'],
  ['personal_honor', 'Personal Honor'],
  ['honor_requirement', 'Honor Req'],
  ['province_strength', 'Province Str'],
  ['gold_production', 'Gold Prod'],
  ['starting_honor', 'Starting Honor'],
];

const $ = (id) => document.getElementById(id);

// Card text is curated data that carries simple inline markup (<b>, <i>, <br>). Escape everything,
// then re-enable just that subset so the formatting renders without trusting arbitrary HTML.
function safeRules(text) {
  return esc(text)
    .replace(/\n/g, '<br>')
    .replace(/&lt;(\/?(?:b|i|em|u|br))\s*\/?&gt;/gi, '<$1>');
}

let imgBase = '/images';
let card = null;
let back = null; // the other face of a double-faced card, if any
let prints = [];
let index = 0;
let flipped = false;

function pathParts() {
  const segs = location.pathname.split('/').filter(Boolean); // ['card', id, set_slug?]
  return {
    cardId: decodeURIComponent(segs[1] || ''),
    setSlug: segs[2] ? decodeURIComponent(segs[2]) : null,
  };
}

function cardPath(slug) {
  const id = encodeURIComponent(card.card_id);
  return slug ? `/card/${id}/${encodeURIComponent(slug)}` : `/card/${id}`;
}

function renderArt() {
  const print = prints[index];
  const hasBack = !!print?.back_image_path;
  const showingBack = flipped && hasBack;
  const src = showingBack
    ? `${imgBase}/${print.back_image_path}`
    : print?.image_path
      ? `${imgBase}/${print.image_path}`
      : fallbackSrc(card, imgBase) || '';

  const img = $('cardArt');
  img.onerror = () => {
    img.onerror = null;
    img.src = fallbackSrc(card, imgBase) || '';
  };
  img.src = src;
  img.alt = card.name;

  const single = prints.length <= 1;
  $('artPrev').hidden = $('artNext').hidden = single;

  // The page and the zoom overlay share one face (`flipped`), so flipping either keeps both in sync.
  // The two sides of a flip card often look alike, so each view labels which face it is showing.
  for (const flip of [$('artFlip'), $('zoomFlip')]) {
    flip.hidden = !hasBack;
    flip.setAttribute('aria-pressed', String(showingBack));
  }
  for (const label of [$('cardFace'), $('zoomFace')]) {
    label.textContent = showingBack ? 'Back' : 'Front';
    label.hidden = !hasBack;
  }
  const zoomImg = $('zoomImg');
  zoomImg.src = src;
  zoomImg.alt = card.name;
}

function renderInfo() {
  const print = prints[index];
  // Flipped to a double-faced card's back: the panel shows the back card's stats/text, and flavor
  // comes from the back face of this printing.
  const face = flipped && back ? back : card;
  $('cardName').textContent = face.extended_title || face.name;
  $('cardTypeline').textContent = [(face.types || []).join(' · '), (face.clans || []).join(' · ')]
    .filter(Boolean)
    .join(' — ');

  $('cardStats').innerHTML = STAT_LABELS.filter(([key]) => face[key] != null)
    .map(([key, label]) => `<div><dt>${label}</dt><dd>${esc(face[key])}</dd></div>`)
    .join('');

  const keywords = [...new Set(face.keywords || [])]; // the array can repeat a keyword
  const kw = $('cardKeywords');
  kw.textContent = keywords.join(' · ');
  kw.hidden = keywords.length === 0;

  $('cardText').innerHTML = safeRules(face.text || '');

  const flavorText = flipped && back ? print?.back_flavor_text : print?.flavor_text;
  const flavor = $('cardFlavor');
  flavor.innerHTML = flavorText ? safeRules(flavorText) : '';
  flavor.hidden = !flavorText;

  const artist = $('cardArtist');
  artist.textContent = print?.artist ? `Illustrated by ${print.artist}` : '';
  artist.hidden = !print?.artist;

  const story = $('cardStory');
  story.textContent = face.story ? `Story: ${face.story}` : '';
  story.hidden = !face.story;
}

function renderPrints() {
  $('printsList').innerHTML = prints
    .map((p, i) => {
      const thumb = p.image_path
        ? `<img src="${esc(`${imgBase}/${p.image_path}`)}" alt="" loading="lazy">`
        : '<span class="print-thumb-empty"></span>';
      const rarity = p.rarity ? `<span class="print-rarity">${esc(p.rarity)}</span>` : '';
      return (
        `<li class="print-row${i === index ? ' selected' : ''}" data-i="${i}">` +
        thumb +
        `<span class="print-meta"><span class="print-set">${esc(p.set_name)}</span>${rarity}</span>` +
        `</li>`
      );
    })
    .join('');
}

function selectPrint(i, pushUrl = true) {
  index = i;
  flipped = false;
  renderArt();
  renderInfo();
  renderPrints();
  if (pushUrl && prints[index]?.set_slug) {
    history.replaceState(null, '', cardPath(prints[index].set_slug));
  }
}

function step(delta) {
  const n = prints.length;
  if (n > 1) selectPrint((index + delta + n) % n);
}

function toggleFlip() {
  if (!prints[index]?.back_image_path) return;
  flipped = !flipped;
  renderArt();
  renderInfo();
}

function openZoom() {
  $('zoom').hidden = false;
}

function closeZoom() {
  $('zoom').hidden = true;
}

async function init() {
  imgBase = await fetchImageBase();
  const { cardId, setSlug } = pathParts();

  let body;
  try {
    const res = await fetch(`/api/cards/${encodeURIComponent(cardId)}`);
    if (!res.ok) throw new Error(`${res.status}`);
    body = await res.json();
  } catch (_) {
    $('cardMissing').hidden = false;
    return;
  }

  card = body.card;
  back = body.back || null;
  prints = body.prints || [];
  document.title = `${card.name} — Game on, Yasuki!`;

  const wanted = setSlug ? prints.findIndex((p) => p.set_slug === setSlug) : -1;
  $('cardPage').hidden = false;
  selectPrint(wanted >= 0 ? wanted : 0, false);

  $('artPrev').addEventListener('click', () => step(-1));
  $('artNext').addEventListener('click', () => step(1));
  $('artFlip').addEventListener('click', toggleFlip);
  $('cardArt').addEventListener('click', openZoom);
  $('printsList').addEventListener('click', (e) => {
    const row = e.target.closest('.print-row');
    if (row) selectPrint(Number(row.dataset.i));
  });

  $('zoom').addEventListener('click', (e) => {
    if (e.target === $('zoom')) closeZoom();
  });
  $('zoomFlip').addEventListener('click', (e) => (e.stopPropagation(), toggleFlip()));

  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeZoom();
    else if (e.key === 'ArrowLeft') step(-1);
    else if (e.key === 'ArrowRight') step(1);
    else if (e.key === 'f' || e.key === 'F') toggleFlip();
  });
}

init();
