// WIP online-play lobby, served at the unlinked, password-gated /top-secret.html route until
// launch.

import { esc } from './card-common.js';
import { listRooms, createRoom } from './rooms-api.js';
import { connectRoom } from './ws-client.js';

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

export function renderPlayers(listEl, players, you) {
  listEl.innerHTML = players
    .map((name) => `<li>${esc(name)}${name === you ? ' <span class="you">(you)</span>' : ''}</li>`)
    .join('');
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
  const playerName = document.getElementById('playerName');
  const roomList = document.getElementById('roomList');
  const lobbyStatus = document.getElementById('lobbyStatus');
  const createForm = document.getElementById('createForm');
  const roomName = document.getElementById('roomName');
  const joinForm = document.getElementById('joinForm');
  const joinRoomId = document.getElementById('joinRoomId');
  const refreshButton = document.getElementById('refreshRooms');
  const lobbyView = document.getElementById('lobbyView');
  const roomView = document.getElementById('roomView');
  const roomIdLabel = document.getElementById('roomIdLabel');
  const playerList = document.getElementById('playerList');
  const roomStatus = document.getElementById('roomStatus');
  const leaveButton = document.getElementById('leaveRoom');

  let client = null;
  let myName = null;

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

  function showRoom(roomId) {
    if (roomIdLabel) roomIdLabel.textContent = roomId;
    if (lobbyView) lobbyView.hidden = true;
    if (roomView) roomView.hidden = false;
  }

  function leaveRoom() {
    client?.close();
    client = null;
    if (roomView) roomView.hidden = true;
    if (lobbyView) lobbyView.hidden = false;
    loadRooms();
  }

  function joinRoom(roomId) {
    const id = (roomId || '').trim();
    if (!id) return;
    myName = playerName?.value.trim();
    if (!myName) {
      setStatus('Enter a name first.');
      return;
    }
    setStatus(`Joining ${id}…`);
    client = connectRoom(id, myName);
    client.events.addEventListener('HELLO', (e) => {
      showRoom(e.detail.room);
      renderPlayers(playerList, e.detail.players, myName);
      if (roomStatus) roomStatus.textContent = '';
    });
    client.events.addEventListener('STATE', (e) => {
      renderPlayers(playerList, Object.keys(e.detail.state?.player_states ?? {}), myName);
    });
    client.events.addEventListener('disconnected', () => {
      if (roomStatus) roomStatus.textContent = 'Disconnected from the room.';
    });
  }

  leaveButton?.addEventListener('click', leaveRoom);

  createForm?.addEventListener('submit', async (e) => {
    e.preventDefault();
    if (!playerName?.value.trim()) {
      setStatus('Enter a name first.');
      return;
    }
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
