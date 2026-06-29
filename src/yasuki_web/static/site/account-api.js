// Account API shared by the nav widget and the settings page. Same-origin, so the session cookie
// attaches automatically.

// The signed-in user ({ id, display_name, avatar_url }) or null.
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
