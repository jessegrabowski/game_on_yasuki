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
let revisions = []; // errata history, oldest first; empty for cards never errata'd
let errataPrint = null; // the printing an errata was issued for, if any
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
  // A printing that carries an errata shows the errata render as its front; the pre-errata art stays
  // on image_path for the old/new comparison.
  const frontPath = print?.errata_image_path || print?.image_path;
  const src = showingBack
    ? `${imgBase}/${print.back_image_path}`
    : frontPath
      ? `${imgBase}/${frontPath}`
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

  // A printing's special back that carries its own text (a story scroll) — show its title and prose,
  // with no stats or rules. A bare clan card-back has no text, so we leave the front's panel as-is
  // and only flip the image.
  if (flipped && !back && (print?.back_title || print?.back_flavor_text)) {
    $('cardName').textContent = print.back_title || 'Card Back';
    $('cardTypeline').textContent = '';
    $('cardStats').innerHTML = '';
    $('cardKeywords').hidden = true;
    $('cardText').innerHTML = '';
    const scroll = print.back_flavor_text;
    const flavor = $('cardFlavor');
    flavor.innerHTML = scroll ? safeRules(scroll) : '';
    flavor.hidden = !scroll;
    $('cardArtist').hidden = true;
    $('cardStory').hidden = true;
    return;
  }

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
      const thumbPath = p.errata_image_path || p.image_path;
      const thumb = thumbPath
        ? `<img src="${esc(`${imgBase}/${thumbPath}`)}" alt="" loading="lazy">`
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

// Set up the compare control once. Its visibility is per-printing (see refreshCompareButton): the
// errata was issued for one printing, so the button shows only when that printing is selected.
function setupCompare() {
  if (revisions.length < 2) return;
  $('compareBtn').textContent = 'Compare revisions';

  // Prior revisions, newest first, so the default selection is the change immediately before current.
  $('compareSelect').innerHTML = revisions
    .slice(0, -1)
    .reverse()
    .map((rev) => `<option value="${rev.revision_index}">${esc(revLabel(rev))}</option>`)
    .join('');
}

function refreshCompareButton() {
  $('cardErrata').hidden = !prints[index]?.errata;
}

function revLabel(rev) {
  if (!rev.effective_date) return 'Original printing';
  return rev.source ? `${rev.effective_date} · ${rev.source}` : rev.effective_date;
}

function currentLabel() {
  const current = revisions[revisions.length - 1];
  return current.effective_date ? `Current · ${current.effective_date}` : 'Current';
}

// Point a revision's announcement link at its source_url, or hide it when the revision has none
// (e.g. the original printing).
function setSrcLink(id, rev) {
  const el = $(id);
  if (rev.source_url) {
    el.href = rev.source_url;
    el.textContent = `${rev.source || 'Errata announcement'} ↗`;
    el.hidden = false;
  } else {
    el.removeAttribute('href');
    el.hidden = true;
  }
}

// A revision's own render, else the printing's art: its errata render for the current revision, its
// pre-errata art for an older one.
function revImgSrc(rev) {
  const path =
    rev.image_path ||
    (rev === revisions[revisions.length - 1]
      ? errataPrint?.errata_image_path || errataPrint?.image_path
      : errataPrint?.image_path);
  return path ? `${imgBase}/${path}` : fallbackSrc(card, imgBase) || '';
}

// Render the API's unified diff rows (old→current) as a single-column GitHub-style patch: context
// lines plain, removed lines with a − gutter, added lines with a +, and the words that actually
// changed within a line highlighted.
function renderUnified(rows) {
  return rows
    .map((row) => {
      const gutter = row.type === 'del' ? '−' : row.type === 'ins' ? '+' : ' ';
      const body = row.segments
        .map((s) => (s.kind === 'chg' ? `<span class="chg">${esc(s.text)}</span>` : esc(s.text)))
        .join('');
      return (
        `<div class="diff-row ${row.type}"><span class="diff-gutter">${gutter}</span>` +
        `<span class="diff-text">${body || ' '}</span></div>`
      );
    })
    .join('');
}

function renderComparison() {
  const selIndex = Number($('compareSelect').value);
  const selected = revisions.find((r) => r.revision_index === selIndex) || revisions[0];
  $('compareDiffHead').innerHTML =
    `${esc(revLabel(selected))} <span class="compare-arrow">→</span> ${esc(currentLabel())}`;
  $('compareDiff').innerHTML = renderUnified(selected.diff || []);
  $('compareOldImg').src = revImgSrc(selected);
  setSrcLink('compareOldSrc', selected);
}

function openCompare() {
  const current = revisions[revisions.length - 1];
  $('compareCurCap').textContent = currentLabel();
  $('compareCurImg').src = revImgSrc(current);
  setSrcLink('compareCurSrc', current);
  renderComparison();
  $('compare').hidden = false;
}

function closeCompare() {
  $('compare').hidden = true;
}

function selectPrint(i, pushUrl = true) {
  index = i;
  flipped = false;
  renderArt();
  renderInfo();
  renderPrints();
  refreshCompareButton();
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
  revisions = body.revisions || [];
  document.title = `${card.name} — Game on, Yasuki!`;

  // The errata render belongs to the printing it was issued for: it becomes that printing's front
  // (errata_image_path), while its pre-errata art stays on image_path for the old/new comparison.
  let errataIndex = -1;
  const current = revisions[revisions.length - 1];
  if (current?.image_path) {
    const slug = current.image_path.split('/')[1]; // sets/<slug>/<file>
    errataIndex = prints.findIndex((p) => p.set_slug === slug);
    if (errataIndex >= 0) {
      prints[errataIndex].errata_image_path = current.image_path;
      prints[errataIndex].errata = true;
      errataPrint = prints[errataIndex];
    }
  }
  setupCompare();

  // Default to the errata'd printing (the current version) unless the URL asked for a specific set.
  const wanted = setSlug ? prints.findIndex((p) => p.set_slug === setSlug) : errataIndex;
  $('cardPage').hidden = false;
  selectPrint(wanted >= 0 ? wanted : 0, false);

  $('artPrev').addEventListener('click', () => step(-1));
  $('artNext').addEventListener('click', () => step(1));
  $('artFlip').addEventListener('click', toggleFlip);
  $('compareBtn').addEventListener('click', openCompare);
  $('compareSelect').addEventListener('change', renderComparison);
  $('compareClose').addEventListener('click', closeCompare);
  $('compare').addEventListener('click', (e) => {
    if (e.target === $('compare')) closeCompare();
  });
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
    if (e.key === 'Escape') {
      closeZoom();
      closeCompare();
    } else if (!$('compare').hidden) {
      // Comparison open: don't let arrow keys step printings behind it.
    } else if (e.key === 'ArrowLeft') step(-1);
    else if (e.key === 'ArrowRight') step(1);
    else if (e.key === 'f' || e.key === 'F') toggleFlip();
  });
}

init();
