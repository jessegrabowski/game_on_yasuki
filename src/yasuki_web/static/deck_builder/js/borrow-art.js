import { $, esc, debounce, displayName } from './helpers.js';
import { fetchJSON } from './api.js';
import {
  artRect,
  compositeArt,
  customPrintId,
  loadImage,
  loadMonOverlays,
  loadOverlays,
} from './art.js';

// Modal to borrow a donor card's art onto the recipient print, compositing entirely in the browser.
// On "Use", calls onUse(customPrint) with a print object to drop into the recipient's print cycle.
export function openBorrowArt({ recipientCard, recipientPrint, imgBase, api, onUse }) {
  let donorCard = null;
  let donorPrints = [];
  let donorIndex = 0;
  let recipientImg = null;
  let recipientOverlays = [];
  let lastDataUrl = null;

  const overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  overlay.innerHTML = `
    <div class="modal" role="dialog" aria-label="Borrow art">
      <div class="modal-head">Borrow art onto ${esc(displayName(recipientCard))}</div>
      <div class="modal-body">
        <div class="borrow-left">
          <input type="text" id="borrowSearch" placeholder="Search a card to borrow art from&hellip;">
          <div class="borrow-results" id="borrowResults"></div>
        </div>
        <div class="borrow-right">
          <div class="borrow-preview-wrap">
            <img class="borrow-preview" id="borrowPreview" alt="composite preview">
            <div class="borrow-placeholder" id="borrowPlaceholder">Pick a donor card</div>
          </div>
          <div class="print-nav borrow-print-nav hidden" id="borrowPrintNav">
            <button id="borrowPrev">&#9664;</button>
            <span class="print-info" id="borrowPrintInfo"></span>
            <button id="borrowNext">&#9654;</button>
          </div>
        </div>
      </div>
      <div class="modal-actions">
        <button class="btn" id="borrowUse" disabled>Use This Art</button>
        <button class="btn" id="borrowCancel">Cancel</button>
      </div>
    </div>`;
  document.body.appendChild(overlay);

  let resultCards = [];
  let selectedIndex = -1;
  let offset = 0;
  let hasMore = false;
  let loading = false;
  let query = '';

  // Infinite-scroll pagination: load the next page when the sentinel scrolls into the results pane.
  const observer = new IntersectionObserver(
    (entries) => {
      if (entries[0].isIntersecting && hasMore && !loading) loadPage();
    },
    { root: $('borrowResults'), threshold: 0 },
  );

  // Arrow keys move the donor selection in this window (not the main card list). Captured on
  // document so it pre-empts the global navigation handler while the modal is open.
  const onKey = (e) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      e.stopPropagation();
      if (!resultCards.length) return;
      const next = e.key === 'ArrowDown' ? selectedIndex + 1 : selectedIndex - 1;
      selectRow(Math.max(0, Math.min(next, resultCards.length - 1)));
    } else if (e.key === 'Enter') {
      e.stopPropagation();
      if (!$('borrowUse').disabled) $('borrowUse').click();
    } else if (e.key === 'Escape') {
      e.stopPropagation();
      close();
    }
  };
  document.addEventListener('keydown', onKey, true);

  function close() {
    document.removeEventListener('keydown', onKey, true);
    observer.disconnect();
    overlay.remove();
  }
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });
  $('borrowCancel').addEventListener('click', close);

  loadImage(`${imgBase}/${recipientPrint.image_path}`).then((img) => {
    recipientImg = img;
    if (donorCard) renderComposite();
  });
  // Recipient frame elements re-stamped over the borrowed art: holding flair + keyword mons.
  Promise.all([
    loadOverlays(recipientPrint.era, recipientPrint.layout_type, imgBase),
    loadMonOverlays(recipientCard.keywords, recipientPrint.era, imgBase),
  ]).then(([flair, mons]) => {
    recipientOverlays = [...flair, ...mons];
    if (donorCard) renderComposite();
  });

  const searchEl = $('borrowSearch');
  searchEl.addEventListener('input', debounce(runSearch, 250));
  searchEl.focus();
  runSearch(); // populate on open so the window isn't empty

  const pickDebounced = debounce((card) => card && pickDonor(card), 120);

  function selectRow(index) {
    selectedIndex = index;
    const rows = $('borrowResults').querySelectorAll('.borrow-result');
    rows.forEach((el, i) => el.classList.toggle('selected', i === index));
    if (rows[index]) rows[index].scrollIntoView({ block: 'nearest' });
    pickDebounced(resultCards[index]);
  }

  async function runSearch() {
    query = searchEl.value.trim();
    if (query.length === 1) return; // wait for a meaningful query; empty shows the first page
    offset = 0;
    resultCards = [];
    selectedIndex = -1;
    $('borrowResults').innerHTML = '';
    loadPage();
  }

  async function loadPage() {
    if (loading) return;
    loading = true;
    const params = new URLSearchParams({ limit: '40', offset: String(offset) });
    if (query) params.set('search', query);
    let data;
    try {
      data = await fetchJSON(`${api}/cards?${params}`);
    } catch (_) {
      loading = false;
      return;
    }
    const results = $('borrowResults');
    const oldSentinel = results.querySelector('#borrowSentinel');
    if (oldSentinel) oldSentinel.remove();
    (data.cards || []).forEach((card) => {
      const i = resultCards.length;
      resultCards.push(card);
      const row = document.createElement('div');
      row.className = 'borrow-result';
      row.textContent = displayName(card);
      row.addEventListener('click', () => selectRow(i));
      results.appendChild(row);
    });
    offset += (data.cards || []).length;
    hasMore = !!data.has_more;
    const sentinel = document.createElement('div');
    sentinel.id = 'borrowSentinel';
    sentinel.style.height = '1px';
    results.appendChild(sentinel);
    observer.disconnect();
    if (hasMore) observer.observe(sentinel);
    loading = false;
  }

  async function pickDonor(card) {
    donorCard = card;
    donorIndex = 0;
    try {
      const detail = await fetchJSON(`${api}/cards/${card.card_id}`);
      donorPrints = (detail.prints || []).filter((p) => p.image_path);
    } catch (_) {
      donorPrints = [];
    }
    renderComposite();
  }

  $('borrowPrev').addEventListener('click', () => {
    if (!donorPrints.length) return;
    donorIndex = (donorIndex - 1 + donorPrints.length) % donorPrints.length;
    renderComposite();
  });
  $('borrowNext').addEventListener('click', () => {
    if (!donorPrints.length) return;
    donorIndex = (donorIndex + 1) % donorPrints.length;
    renderComposite();
  });

  async function renderComposite() {
    const nav = $('borrowPrintNav');
    const useBtn = $('borrowUse');
    const placeholder = $('borrowPlaceholder');
    if (!recipientImg || !donorCard || !donorPrints.length) {
      nav.classList.add('hidden');
      useBtn.disabled = true;
      placeholder.style.display = donorCard && !donorPrints.length ? 'flex' : 'flex';
      placeholder.textContent = donorCard && !donorPrints.length ? 'No art on this card' : 'Pick a donor card';
      return;
    }
    const donor = donorPrints[donorIndex];
    let donorImg;
    try {
      donorImg = await loadImage(`${imgBase}/${donor.image_path}`);
    } catch (_) {
      return;
    }
    const canvas = compositeArt(
      recipientImg,
      donorImg,
      artRect(recipientPrint.era, recipientPrint.layout_type),
      artRect(donor.era, donor.layout_type),
      recipientOverlays,
    );
    lastDataUrl = canvas.toDataURL('image/jpeg', 0.92);
    const preview = $('borrowPreview');
    preview.src = lastDataUrl;
    placeholder.style.display = 'none';
    nav.classList.remove('hidden');
    $('borrowPrintInfo').textContent = `${donor.set_name || '?'} (${donorIndex + 1}/${donorPrints.length})`;
    useBtn.disabled = false;
  }

  $('borrowUse').addEventListener('click', () => {
    if (!donorCard || !donorPrints.length || !lastDataUrl) return;
    const donor = donorPrints[donorIndex];
    const recipe = {
      recipientPrintId: recipientPrint.print_id,
      donorCardId: donorCard.card_id,
      donorPrintId: donor.print_id,
    };
    onUse({
      print_id: customPrintId(recipe),
      set_name: recipientPrint.set_name || '',
      isCustom: true,
      // Plain name (no unique marker) so the deck YAML round-trips through name lookup.
      art: { donorName: donorCard.extended_title || donorCard.name, donorSet: donor.set_name || '' },
      recipe,
      dataUrl: lastDataUrl,
      recipientPrint, // kept so the art button can re-borrow onto the same base print
    });
    close();
  });
}
