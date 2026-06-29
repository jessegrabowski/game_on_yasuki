// Account-backed deck storage. The session cookie attaches automatically on same-origin requests,
// so no credentials option is needed; every signed-out call simply comes back unauthorized.

const JSON_HEADERS = { 'Content-Type': 'application/json' };

// The signed-in user ({ id, display_name, avatar }) or null. /api/me always returns 200 with a
// { user } body, so only a network failure yields null here.
export async function getMe() {
  try {
    const res = await fetch('/api/me');
    if (!res.ok) return null;
    return (await res.json()).user;
  } catch {
    return null;
  }
}

// Persist a deck. Returns { ok: true, deck } on success, else { ok: false, status, error } with a
// human message — 401 (sign in), 400 (unknown cards), or 422 (a length / count cap).
export async function saveDeck({ name, yaml, visibility = 'private', description = null, format = null }) {
  const res = await fetch('/api/me/decks', {
    method: 'POST',
    headers: JSON_HEADERS,
    body: JSON.stringify({ name, yaml, visibility, description, format }),
  });
  if (res.ok) return { ok: true, deck: (await res.json()).deck };
  return { ok: false, status: res.status, error: await errorMessage(res) };
}

export async function listMyDecks() {
  const res = await fetch('/api/me/decks');
  if (!res.ok) return [];
  return (await res.json()).decks;
}

export async function deleteDeck(slug) {
  const res = await fetch(`/api/me/decks/${encodeURIComponent(slug)}`, { method: 'DELETE' });
  return res.ok;
}

// Erase the signed-in account (profile, decks, sessions). Returns whether it succeeded.
export async function deleteAccount() {
  const res = await fetch('/api/me', { method: 'DELETE' });
  return res.ok;
}

// A shared deck by slug ({ deck, cards, yaml }), or null if it is missing or private to someone else.
export async function fetchSharedDeck(slug) {
  const res = await fetch(`/api/decks/${encodeURIComponent(slug)}`);
  if (!res.ok) return null;
  return res.json();
}

// Turn a failed save response into a one-line message for the status area.
async function errorMessage(res) {
  if (res.status === 401) return 'Sign in to save decks';
  try {
    const { detail } = await res.json();
    if (detail && detail.error === 'unknown_cards') {
      return `Unknown card(s): ${detail.cards.join(', ')}`;
    }
    if (typeof detail === 'string') return detail;
  } catch {
    // fall through to the generic message
  }
  return `Save failed (${res.status})`;
}
