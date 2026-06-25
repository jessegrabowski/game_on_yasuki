// Client for the room REST endpoints (src/yasuki_web/rooms.py). The page is already behind the WIP
// Basic-auth gate, so the browser attaches credentials to these same-origin requests automatically.

async function requestJSON(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}

export function listRooms() {
  return requestJSON('/api/rooms');
}

export function createRoom({ name, maxPlayers = 2 } = {}) {
  const body = { max_players: maxPlayers };
  if (name) body.room_name = name;
  return requestJSON('/api/rooms', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}
