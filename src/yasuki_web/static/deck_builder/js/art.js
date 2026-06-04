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

// Frame-element overlays ({asset, rect}) stamped over the donor art for an (era, layoutType), or
// empty. Mirrors core overlays_for; assets are served from `${imgBase}/overlays/<asset>`.
export function overlaysFor(era, layoutType) {
  return (_layout.overlays || {})[`${era}|${layoutType}`] || [];
}

// Load the overlay assets for an (era, layoutType) as [{img, rect}] ready for compositeArt.
export async function loadOverlays(era, layoutType, imgBase) {
  return Promise.all(
    overlaysFor(era, layoutType).map(async (o) => ({
      img: await loadImage(`${imgBase}/overlays/${o.asset}`),
      rect: o.rect,
    })),
  );
}

// Keyword "mons" for a card: present mon keywords in alphabetical order down stacked slots, each
// the same size and left, at centers cy0 + i*pitch. Modern frame only. Mirrors core mon_overlays.
export function monOverlaysFor(keywords, era) {
  const cfg = _layout.mons;
  if (!cfg || era !== cfg.era) return [];
  const present = (keywords || []).filter((k) => cfg.assets[k]).sort();
  return present.map((kw, i) => {
    const cy = cfg.cy0 + i * cfg.pitch;
    return {
      asset: cfg.assets[kw],
      rect: [cfg.left, cy - cfg.height / 2, cfg.left + cfg.width, cy + cfg.height / 2],
    };
  });
}

export async function loadMonOverlays(keywords, era, imgBase) {
  return Promise.all(
    monOverlaysFor(keywords, era).map(async (o) => ({
      img: await loadImage(`${imgBase}/overlays/${o.asset}`),
      rect: o.rect,
    })),
  );
}

// Recipient patches ({rect, mask?}) re-stamped from the recipient itself after the donor art covers
// them, keyed "era|layout". A masked patch keeps only the silhouette (stat icons); an unmasked one
// restores the whole rect (banner corners, frame edges). Pixels come from the recipient scan, so
// printed values and clan colours survive with no font. Mirrors core patches_for.
export function patchesFor(era, layoutType) {
  return (_layout.patches || {})[`${era}|${layoutType}`] || [];
}

// Resolve patches to [{rect, mask|null}] with mask assets loaded, ready for compositeArt.
export async function loadPatches(era, layoutType, imgBase) {
  return Promise.all(
    patchesFor(era, layoutType).map(async (p) => ({
      rect: p.rect,
      mask: p.mask ? await loadImage(`${imgBase}/overlays/${p.mask}`) : null,
    })),
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
// native size. recipientRect/donorRect are fractional [l, t, r, b] from artRect(). overlays are
// [{img, rect}] frame elements stamped over the art (each with baked transparent holes so
// card-specific elements underneath show through). Browser-only.
export function compositeArt(
  recipientImg,
  donorImg,
  recipientRect,
  donorRect,
  overlays = [],
  patches = [],
) {
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

  for (const { img, rect } of overlays) {
    const [ol, ot, or, ob] = box(canvas.width, canvas.height, rect);
    ctx.drawImage(img, ol, ot, or - ol, ob - ot);
  }

  // Re-stamp recipient patches over the donor art: harvest each region from the pristine recipient.
  // A masked patch keeps only the silhouette (stat icons); an unmasked one restores the whole rect.
  for (const { rect, mask } of patches) {
    const [il, it, ir, ib] = box(canvas.width, canvas.height, rect);
    const w = ir - il;
    const h = ib - it;
    if (w < 1 || h < 1) continue;
    if (mask) {
      const off = document.createElement('canvas');
      off.width = w;
      off.height = h;
      const octx = off.getContext('2d');
      octx.drawImage(recipientImg, il, it, w, h, 0, 0, w, h);
      octx.globalCompositeOperation = 'destination-in';
      octx.drawImage(mask, 0, 0, w, h); // keep only inside the silhouette (mask alpha)
      ctx.drawImage(off, il, it);
    } else {
      ctx.drawImage(recipientImg, il, it, w, h, il, it, w, h); // restore the whole rect
    }
  }
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
  const [recipient, donor, flair, mons, patches] = await Promise.all([
    loadImage(`${imgBase}/${spec.recipientImagePath}`),
    loadImage(`${imgBase}/${spec.donorImagePath}`),
    loadOverlays(spec.recipientEra, spec.recipientLayout, imgBase),
    loadMonOverlays(spec.recipientKeywords, spec.recipientEra, imgBase),
    loadPatches(spec.recipientEra, spec.recipientLayout, imgBase),
  ]);
  const canvas = compositeArt(
    recipient,
    donor,
    artRect(spec.recipientEra, spec.recipientLayout),
    artRect(spec.donorEra, spec.donorLayout),
    [...flair, ...mons],
    patches,
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
