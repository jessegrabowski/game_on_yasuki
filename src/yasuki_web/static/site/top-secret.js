// WIP online-play lobby, served at the unlinked, password-gated /top-secret.html route until
// launch.

import { esc } from './card-common.js';
import { listRooms, createRoom } from './rooms-api.js';

const DELETE_TOKENS_KEY = 'yasuki.play.deleteTokens.v1';

export function roomItemHTML(room) {
  const players = (room.players || []).length;
  return (
    `<li>` +
    `<span class="room-name">${esc(room.name)}</span>` +
    `<span class="room-meta">${players}/${room.max_players} · ${esc(room.id)}</span>` +
    `<button class="join-btn" data-room-id="${esc(room.id)}">Join</button>` +
    `</li>`
  );
}

export function renderRooms(listEl, rooms) {
  listEl.innerHTML = rooms.length
    ? rooms.map(roomItemHTML).join('')
    : '<li class="empty">No open rooms yet — create one.</li>';
}

// The delete token is the only way to reclaim a room you created, so stash it client-side. Losing
// it (private mode, quota) just forgoes cleanup, never blocks play.
function rememberDeleteToken(roomId, token) {
  try {
    const store = globalThis.localStorage;
    if (!store) return;
    const tokens = JSON.parse(store.getItem(DELETE_TOKENS_KEY) || '{}');
    tokens[roomId] = token;
    store.setItem(DELETE_TOKENS_KEY, JSON.stringify(tokens));
  } catch (_) {
    /* persistence is best-effort */
  }
}

function init() {
  const roomList = document.getElementById('roomList');
  const lobbyStatus = document.getElementById('lobbyStatus');
  const createForm = document.getElementById('createForm');
  const roomName = document.getElementById('roomName');
  const joinForm = document.getElementById('joinForm');
  const joinRoomId = document.getElementById('joinRoomId');
  const refreshButton = document.getElementById('refreshRooms');

  const setStatus = (msg) => {
    if (lobbyStatus) lobbyStatus.textContent = msg;
  };

  async function loadRooms() {
    try {
      const { rooms } = await listRooms();
      renderRooms(roomList, rooms);
      setStatus('');
    } catch (_) {
      setStatus('Could not load rooms.');
    }
  }

  function joinRoom(roomId) {
    const id = (roomId || '').trim();
    if (id) setStatus(`Joining ${id}…`);
  }

  createForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      const created = await createRoom({ name: roomName?.value.trim() });
      rememberDeleteToken(created.room_id, created.delete_token);
      joinRoom(created.room_id);
    } catch (_) {
      setStatus('Could not create the room.');
    }
  });

  joinForm?.addEventListener('submit', (e) => {
    e.preventDefault();
    joinRoom(joinRoomId?.value || '');
  });

  roomList?.addEventListener('click', (e) => {
    const id = e.target?.dataset?.roomId;
    if (id) joinRoom(id);
  });

  refreshButton?.addEventListener('click', loadRooms);

  loadRooms();
}

if (typeof window !== 'undefined') init();
