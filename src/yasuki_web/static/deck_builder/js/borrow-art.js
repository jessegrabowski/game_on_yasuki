import { $, esc, debounce, displayName } from './helpers.js';
import { fetchJSON } from './api.js';
import { artRect, compositeArt, customPrintId, loadImage } from './art.js';

// Modal to borrow a donor card's art onto the recipient print, compositing entirely in the browser.
// On "Use", calls onUse(customPrint) with a print object to drop into the recipient's print cycle.
export function openBorrowArt({ recipientCard, recipientPrint, imgBase, api, onUse }) {
  let donorCard = null;
  let donorPrints = [];
  let donorIndex = 0;
  let recipientImg = null;
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

  const close = () => overlay.remove();
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });
  $('borrowCancel').addEventListener('click', close);

  loadImage(`${imgBase}/${recipientPrint.image_path}`).then((img) => {
    recipientImg = img;
    if (donorCard) renderComposite();
  });

  const searchEl = $('borrowSearch');
  searchEl.addEventListener('input', debounce(runSearch, 250));
  searchEl.focus();
  runSearch(); // populate on open so the window isn't empty

  async function runSearch() {
    const q = searchEl.value.trim();
    const results = $('borrowResults');
    if (q.length === 1) return; // wait for a meaningful query; empty shows the first page
    const params = q ? `search=${encodeURIComponent(q)}&limit=40` : 'limit=40';
    let cards = [];
    try {
      cards = (await fetchJSON(`${api}/cards?${params}`)).cards || [];
    } catch (_) {
      return;
    }
    results.innerHTML = '';
    cards.forEach((card) => {
      const row = document.createElement('div');
      row.className = 'borrow-result';
      row.textContent = displayName(card);
      row.addEventListener('click', () => pickDonor(card, row));
      results.appendChild(row);
    });
  }

  async function pickDonor(card, row) {
    $('borrowResults')
      .querySelectorAll('.borrow-result')
      .forEach((el) => el.classList.remove('selected'));
    row.classList.add('selected');
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
      art: { donorName: displayName(donorCard), donorSet: donor.set_name || '' },
      recipe,
      dataUrl: lastDataUrl,
      recipientPrint, // kept so the art button can re-borrow onto the same base print
    });
    close();
  });
}
