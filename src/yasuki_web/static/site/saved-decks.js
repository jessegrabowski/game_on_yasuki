// Picking a saved deck in the lobby: fetch the signed-in user's decks, let them choose one, and hand
// its slug back so the caller can load the deck's YAML into the room via LOAD_DECK. Built with the
// same createElement idiom as the deck dialog so it stays CSP-safe under style-src 'self'.

import { node } from './board.js';

// The signed-in user's decks (summary rows), or null when the request is unauthorized or fails —
// the caller reads null as "prompt the player to sign in".
export async function fetchMyDecks() {
  try {
    const res = await fetch('/api/me/decks');
    if (!res.ok) return null;
    return (await res.json()).decks;
  } catch {
    return null;
  }
}

// A shared deck's YAML rendering by slug, ready to feed LOAD_DECK, or null if it is gone.
export async function fetchDeckYaml(slug) {
  try {
    const res = await fetch(`/api/decks/${encodeURIComponent(slug)}`);
    if (!res.ok) return null;
    return (await res.json()).yaml;
  } catch {
    return null;
  }
}

// One-line label for a deck row: its name, clan when known, and dynasty/fate counts.
export function deckLabel(deck) {
  const counts = `${deck.dynasty_count ?? 0}D / ${deck.fate_count ?? 0}F`;
  return deck.clan ? `${deck.name} — ${deck.clan} (${counts})` : `${deck.name} (${counts})`;
}

// Open a picker over the room listing `decks`; choosing one calls onPick(slug) and closes. Returns
// { el, close }; closes on the overlay, the ×, or Escape.
export function openSavedDeckPicker({ decks, onPick, onClose }) {
  const overlay = node('div', 'deck-dialog-overlay');
  const modal = node('div', 'deck-dialog');

  let closed = false;
  const close = () => {
    if (closed) return;
    closed = true;
    document.removeEventListener?.('keydown', onKey);
    overlay.remove();
    onClose?.();
  };
  const onKey = (e) => {
    if (e.key === 'Escape') close();
  };

  const title = node('h2', 'deck-dialog-title', 'Your saved decks');
  const closeBtn = node('button', 'deck-dialog-close', '×');
  closeBtn.type = 'button';
  closeBtn.title = 'Close';
  closeBtn.addEventListener('click', close);
  const header = node('div', 'deck-dialog-header');
  header.append(title, closeBtn);

  const list = node('ul', 'deck-dialog-list');
  if (decks.length === 0) {
    list.append(node('li', 'deck-dialog-empty', 'No saved decks yet — build one in the deck builder.'));
  } else {
    for (const deck of decks) {
      const li = node('li', 'deck-dialog-name', deckLabel(deck));
      li.dataset.slug = deck.slug;
      li.addEventListener('click', () => {
        onPick(deck.slug);
        close();
      });
      list.append(li);
    }
  }

  modal.append(header, list);
  overlay.appendChild(modal);
  overlay.addEventListener('click', (e) => {
    if (e.target === overlay) close();
  });

  (document.querySelector('.room') ?? document.body).appendChild(overlay);
  document.addEventListener?.('keydown', onKey);
  return { el: overlay, close };
}
