// The player's avatar, shared by the nav widget and the in-game seat panels so one identity drives
// both: either a crop of a chosen card (canvas) or, as a fallback, a circle of the name's initials.

export function initials(name) {
  return (
    (name ?? '')
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0].toUpperCase())
      .join('') || '?'
  );
}

// The source-pixel rectangle for a fractional crop box on an image of the given natural size.
export function cropToPixels(crop, imageWidth, imageHeight) {
  return {
    sx: crop.left * imageWidth,
    sy: crop.top * imageHeight,
    sw: (crop.right - crop.left) * imageWidth,
    sh: (crop.bottom - crop.top) * imageHeight,
  };
}

export function loadImage(src) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = reject;
    img.src = src;
  });
}

// Draw the cropped region of a loaded card image to fill the (square) canvas; CSS rounds it to a
// circle. Display only, no pixel readback, so a cross-origin card image needs no CORS.
export function drawCardAvatar(canvas, image, crop) {
  const { sx, sy, sw, sh } = cropToPixels(crop, image.naturalWidth, image.naturalHeight);
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(image, sx, sy, sw, sh, 0, 0, canvas.width, canvas.height);
}

const AVATAR_PX = 64;

// The avatar element for a holder of an avatar spec: a canvas of their chosen card crop when one is
// set, else an initials circle. The canvas is returned immediately and filled once the card image
// loads. `className` and `name` let each caller pick the circle's CSS class and the source of the
// initials fallback (the nav uses ``display_name``; the seat bars and roster pass the seat name).
export function buildAvatarElement(holder, imgBase, { className = 'account-avatar', name } = {}) {
  const spec = holder?.avatar;
  if (!spec) {
    const span = document.createElement('span');
    span.className = className;
    span.textContent = initials(name ?? holder?.display_name);
    return span;
  }
  const canvas = document.createElement('canvas');
  canvas.className = className;
  canvas.width = AVATAR_PX;
  canvas.height = AVATAR_PX;
  loadImage(`${imgBase}/${spec.image_path}`)
    .then((image) => drawCardAvatar(canvas, image, spec.crop))
    .catch(() => {});
  return canvas;
}
