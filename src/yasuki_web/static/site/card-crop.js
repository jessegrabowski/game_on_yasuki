// A square crop selector drawn on a canvas: the card image with a draggable, resizable box and the
// region outside it dimmed. Canvas-rendered (no DOM boxes with inline styles) to stay CSP-safe.
// Pure geometry helpers are exported separately so the box math is testable without a canvas.

// Smallest box side, as a fraction of the canvas's shorter dimension.
const MIN_FRACTION = 0.12;
// Hit area (px) of the bottom-right resize handle.
const HANDLE = 18;

export function clampSquareBox(box, width, height) {
  const max = Math.min(width, height);
  const size = Math.max(max * MIN_FRACTION, Math.min(box.size, max));
  return {
    size,
    x: Math.max(0, Math.min(box.x, width - size)),
    y: Math.max(0, Math.min(box.y, height - size)),
  };
}

export function boxToCrop(box, width, height) {
  return {
    left: box.x / width,
    top: box.y / height,
    right: (box.x + box.size) / width,
    bottom: (box.y + box.size) / height,
  };
}

export function centeredBox(width, height) {
  const size = Math.min(width, height) * 0.6;
  return clampSquareBox({ x: (width - size) / 2, y: (height - size) / 2, size }, width, height);
}

export function cropToBox(crop, width, height) {
  return clampSquareBox(
    { x: crop.left * width, y: crop.top * height, size: (crop.right - crop.left) * width },
    width,
    height,
  );
}

// Wire up the editor on `canvas` over a loaded `image`. Calls onChange(crop) — fractional
// {left,top,right,bottom} — on every move/resize and once initially. Returns { crop() }.
export function createCropEditor(canvas, image, onChange, initialCrop = null) {
  const width = canvas.width;
  const height = canvas.height;
  const ctx = canvas.getContext('2d');
  let box = initialCrop ? cropToBox(initialCrop, width, height) : centeredBox(width, height);

  function draw() {
    ctx.clearRect(0, 0, width, height);
    ctx.drawImage(image, 0, 0, width, height);
    ctx.fillStyle = 'rgba(0, 0, 0, 0.5)';
    ctx.fillRect(0, 0, width, box.y);
    ctx.fillRect(0, box.y, box.x, box.size);
    ctx.fillRect(box.x + box.size, box.y, width - box.x - box.size, box.size);
    ctx.fillRect(0, box.y + box.size, width, height - box.y - box.size);
    ctx.strokeStyle = '#fff';
    ctx.lineWidth = 2;
    ctx.strokeRect(box.x, box.y, box.size, box.size);
    ctx.fillStyle = '#fff';
    ctx.fillRect(box.x + box.size - HANDLE, box.y + box.size - HANDLE, HANDLE, HANDLE);
  }

  function at(event) {
    const rect = canvas.getBoundingClientRect();
    return { x: event.clientX - rect.left, y: event.clientY - rect.top };
  }

  let mode = null;
  let start = null;
  let startBox = null;

  canvas.addEventListener('pointerdown', (event) => {
    const p = at(event);
    const onHandle =
      p.x >= box.x + box.size - HANDLE &&
      p.x <= box.x + box.size &&
      p.y >= box.y + box.size - HANDLE &&
      p.y <= box.y + box.size;
    const inBox = p.x >= box.x && p.x <= box.x + box.size && p.y >= box.y && p.y <= box.y + box.size;
    mode = onHandle ? 'resize' : inBox ? 'move' : null;
    if (!mode) return;
    start = p;
    startBox = { ...box };
    canvas.setPointerCapture?.(event.pointerId);
  });

  canvas.addEventListener('pointermove', (event) => {
    if (!mode) return;
    const p = at(event);
    const dx = p.x - start.x;
    const dy = p.y - start.y;
    if (mode === 'move') {
      box = clampSquareBox({ x: startBox.x + dx, y: startBox.y + dy, size: startBox.size }, width, height);
    } else {
      box = clampSquareBox({ x: startBox.x, y: startBox.y, size: startBox.size + Math.max(dx, dy) }, width, height);
    }
    draw();
    onChange(boxToCrop(box, width, height));
  });

  const end = () => {
    mode = null;
  };
  canvas.addEventListener('pointerup', end);
  canvas.addEventListener('pointercancel', end);

  draw();
  onChange(boxToCrop(box, width, height));
  return { crop: () => boxToCrop(box, width, height) };
}
