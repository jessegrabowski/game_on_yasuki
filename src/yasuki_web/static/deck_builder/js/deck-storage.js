const KEY = 'yasuki.deck.v1';

// localStorage so an in-progress deck survives navigating to other pages and accidental tab
// closes. Access is best-effort: privacy modes throw on read, writes can hit quota — never let
// persistence failures break the builder.
function storage() {
  try {
    return globalThis.localStorage || null;
  } catch (_) {
    return null;
  }
}

export function saveDeckSnapshot(yaml) {
  const store = storage();
  if (!store) return;
  try {
    store.setItem(KEY, yaml);
  } catch (_) {
    /* quota or disabled */
  }
}

export function loadDeckSnapshot() {
  const store = storage();
  if (!store) return null;
  try {
    return store.getItem(KEY);
  } catch (_) {
    return null;
  }
}

export function clearDeckSnapshot() {
  const store = storage();
  if (!store) return;
  try {
    store.removeItem(KEY);
  } catch (_) {
    /* ignore */
  }
}
