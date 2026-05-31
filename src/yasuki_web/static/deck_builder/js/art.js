// Client-side art-swap: composite a donor card's art into a recipient card's window, mirroring the
// Python renderer (yasuki_core.card_art). The rect table + era/layout classification come from the
// server (/api/art-layout for rects; each print already carries era + layout_type), so the two
// renderers stay in lockstep.

let _layout = null;

export async function loadArtLayout(fetchJSON) {
  if (!_layout) _layout = await fetchJSON('/api/art-layout');
  return _layout;
}

// Test seam: inject a layout without a fetch.
export function setArtLayout(layout) {
  _layout = layout;
}

// The art rect (fractions [left, top, right, bottom]) for a print's (era, layoutType), falling back
// to that era's Strategy window, then the modern Strategy window — same chain as core art_rect.
export function artRect(era, layoutType) {
  const { rects, default_era: defaultEra, default_layout: defaultLayout } = _layout;
  return (
    rects[`${era}|${layoutType}`] ||
    rects[`${era}|${defaultLayout}`] ||
    rects[`${defaultEra}|${defaultLayout}`]
  );
}

function box(width, height, rect) {
  const [l, t, r, b] = rect;
  return [Math.round(l * width), Math.round(t * height), Math.round(r * width), Math.round(b * height)];
}

// Shrink a [l, t, r, b] box to the target aspect ratio, centered, so a resize to the target fills
// it without distortion (trims the donor's overflowing axis). Mirrors core cover_crop.
export function coverCrop(crop, targetW, targetH) {
  let [left, top, right, bottom] = crop;
  const w = right - left;
  const h = bottom - top;
  if (w * targetH > h * targetW) {
    const newW = Math.round((h * targetW) / targetH);
    left += Math.floor((w - newW) / 2);
    right = left + newW;
  } else {
    const newH = Math.round((w * targetH) / targetW);
    top += Math.floor((h - newH) / 2);
    bottom = top + newH;
  }
  return [left, top, right, bottom];
}

// Composite donorImg's art (its cut rect) into recipientImg's window, on a canvas at the recipient's
// native size. recipientRect/donorRect are fractional [l, t, r, b] from artRect(). Browser-only.
export function compositeArt(recipientImg, donorImg, recipientRect, donorRect) {
  const canvas = document.createElement('canvas');
  canvas.width = recipientImg.naturalWidth;
  canvas.height = recipientImg.naturalHeight;
  const ctx = canvas.getContext('2d');
  ctx.drawImage(recipientImg, 0, 0);

  const [wl, wt, wr, wb] = box(canvas.width, canvas.height, recipientRect);
  const targetW = wr - wl;
  const targetH = wb - wt;
  const [sl, st, sr, sb] = coverCrop(
    box(donorImg.naturalWidth, donorImg.naturalHeight, donorRect),
    targetW,
    targetH,
  );
  ctx.drawImage(donorImg, sl, st, sr - sl, sb - st, wl, wt, targetW, targetH);
  return canvas;
}

// A stable negative id for a custom print so the same swap stacks (qty) instead of duplicating, and
// never collides with real positive print ids. Deterministic from the recipe, like core's
// custom_print_id (the value need not match Python — decks port via the {art:} recipe, not the id).
export function customPrintId(recipe) {
  const key = `${recipe.recipientPrintId}|${recipe.donorCardId}|${recipe.donorPrintId}`;
  let hash = 0;
  for (let i = 0; i < key.length; i++) hash = (hash * 31 + key.charCodeAt(i)) | 0;
  return -(Math.abs(hash) + 1);
}

// Composite a recipe's art and return a JPEG data URL for display/PDF. spec carries each side's
// image path + (era, layout_type) — all from the annotated prints API.
export async function buildCompositeDataURL(spec, imgBase) {
  const [recipient, donor] = await Promise.all([
    loadImage(`${imgBase}/${spec.recipientImagePath}`),
    loadImage(`${imgBase}/${spec.donorImagePath}`),
  ]);
  const canvas = compositeArt(
    recipient,
    donor,
    artRect(spec.recipientEra, spec.recipientLayout),
    artRect(spec.donorEra, spec.donorLayout),
  );
  return canvas.toDataURL('image/jpeg', 0.92);
}

// Load an image CORS-enabled so its pixels can be read back (canvas/PDF) once R2 sends CORS headers.
export function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.crossOrigin = 'anonymous';
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`failed to load ${src}`));
    img.src = src;
  });
}
