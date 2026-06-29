// Account API shared by the nav widget and the settings page. Same-origin, so the session cookie
// attaches automatically.

// The signed-in user ({ id, display_name, avatar }) or null.
export async function getMe() {
  try {
    const res = await fetch('/api/me');
    if (!res.ok) return null;
    return (await res.json()).user;
  } catch {
    return null;
  }
}

export async function logout() {
  try {
    await fetch('/auth/logout', { method: 'POST' });
  } catch {
    // Even if the request fails, the caller reloads into a fresh state.
  }
}

// Change the display name. Returns { ok: true, user } or { ok: false, error } with a message.
export async function updateDisplayName(displayName) {
  const res = await fetch('/api/me', {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ display_name: displayName }),
  });
  if (res.ok) return { ok: true, user: (await res.json()).user };
  return { ok: false, error: await _errorMessage(res) };
}

// Card name/text search, capped — for the avatar card picker. Returns the cards array (empty on
// any failure).
export async function searchCards(query) {
  if (!query) return [];
  try {
    const res = await fetch(`/api/cards?search=${encodeURIComponent(query)}&limit=24`);
    if (!res.ok) return [];
    return (await res.json()).cards ?? [];
  } catch {
    return [];
  }
}

// Set the avatar to a crop of a card (the server resolves the image from card_id). Returns ok.
export async function setAvatar(cardId, crop) {
  const res = await fetch('/api/me/avatar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ card_id: cardId, crop }),
  });
  return res.ok;
}

// Clear the avatar, falling back to the name's initials. Returns ok.
export async function clearAvatar() {
  const res = await fetch('/api/me/avatar', { method: 'DELETE' });
  return res.ok;
}

// Erase the signed-in account (profile, decks, sessions). Returns ok.
export async function deleteAccount() {
  const res = await fetch('/api/me', { method: 'DELETE' });
  return res.ok;
}

// Admin: every registered account (empty on any failure, including a non-admin 403).
export async function listAccounts() {
  try {
    const res = await fetch('/api/admin/users');
    if (!res.ok) return [];
    return (await res.json()).users ?? [];
  } catch {
    return [];
  }
}

// Admin: ban an account (revokes its sessions, blocks the identity). Returns ok.
export async function banAccount(userId) {
  const res = await fetch(`/api/admin/users/${userId}/ban`, { method: 'POST' });
  return res.ok;
}

// Admin: lift a ban so the identity may sign in again. Returns ok.
export async function unbanAccount(userId) {
  const res = await fetch(`/api/admin/users/${userId}/unban`, { method: 'POST' });
  return res.ok;
}

// Admin: approve a pending account so it can use the product. Returns ok.
export async function approveAccount(userId) {
  const res = await fetch(`/api/admin/users/${userId}/approve`, { method: 'POST' });
  return res.ok;
}

// Admin: set an account's role to one of the defined roles. Returns ok.
export async function setRole(userId, role) {
  const res = await fetch(`/api/admin/users/${userId}/role`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role }),
  });
  return res.ok;
}

// Admin: the defined roles ({ name, description }), for the role picker. Empty on any failure.
export async function listRoles() {
  try {
    const res = await fetch('/api/admin/roles');
    if (!res.ok) return [];
    return (await res.json()).roles ?? [];
  } catch {
    return [];
  }
}

// Admin: define a new role. Returns the refreshed role list, or [] on failure.
export async function createRole(name, description = '') {
  const res = await fetch('/api/admin/roles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name, description }),
  });
  if (!res.ok) return [];
  return (await res.json()).roles ?? [];
}

async function _errorMessage(res) {
  if (res.status === 401) return 'Sign in to change your name';
  try {
    const { detail } = await res.json();
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return detail[0].msg; // pydantic validation error
  } catch {
    // fall through
  }
  return `Could not save (${res.status})`;
}
