// WIP online-play lobby, served at the unlinked, password-gated /top-secret.html route until
// launch.

import { esc, fetchImageBase } from './card-common.js';
import { listRooms, createRoom } from './rooms-api.js';
import { connectRoom } from './ws-client.js';
import { renderBoard, addCardFrame, boardFrame, initBoardInteractions } from './board.js';

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

export function appendChatMessage(logEl, sender, text) {
  logEl.innerHTML += `<li><span class="chat-sender">${esc(sender)}</span> ${esc(text)}</li>`;
  logEl.scrollTop = logEl.scrollHeight;
}

export function appendLogMessage(logEl, text) {
  const li = document.createElement('li');
  li.textContent = text;
  logEl.appendChild(li);
  logEl.scrollTop = logEl.scrollHeight;
}

export function chatFrame(room, text) {
  return { type: 'CHAT', room, chat: { text } };
}

// Wire a draggable separator: pointer-drag calls onPointer; arrow keys call onKey, which returns
// true when it handled the event (so the default scroll is suppressed).
function initSeparator(handle, { onPointer, onKey }) {
  let dragging = false;
  handle.addEventListener('pointerdown', (e) => {
    dragging = true;
    handle.setPointerCapture(e.pointerId);
  });
  handle.addEventListener('pointermove', (e) => {
    if (dragging) onPointer(e);
  });
  const stop = () => {
    dragging = false;
  };
  handle.addEventListener('pointerup', stop);
  handle.addEventListener('pointercancel', stop);
  handle.addEventListener('keydown', (e) => {
    if (onKey(e)) e.preventDefault();
  });
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
  const chatLog = document.getElementById('chatLog');
  const chatForm = document.getElementById('chatForm');
  const chatInput = document.getElementById('chatInput');
  const actionLog = document.getElementById('actionLog');
  const battlefield = document.getElementById('battlefield');
  const spawnButton = document.getElementById('spawnCard');

  let client = null;
  let myName = null;
  let currentRoom = null;
  let imgBase = '/images';
  fetchImageBase().then((base) => {
    imgBase = base;
  });

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
    currentRoom = null;
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
    currentRoom = id;
    if (chatLog) chatLog.innerHTML = '';
    if (actionLog) actionLog.innerHTML = '';
    setStatus(`Joining ${id}…`);
    client = connectRoom(id, myName);
    client.events.addEventListener('HELLO', (e) => {
      showRoom(e.detail.room);
      renderPlayers(playerList, e.detail.players, myName);
      if (roomStatus) roomStatus.textContent = '';
    });
    client.events.addEventListener('STATE', (e) => {
      renderPlayers(playerList, Object.keys(e.detail.state?.player_states ?? {}), myName);
      renderBoard(battlefield, e.detail.state?.cards ?? [], imgBase);
    });
    client.events.addEventListener('CHAT', (e) => {
      appendChatMessage(chatLog, e.detail.from, e.detail.text);
    });
    client.events.addEventListener('LOG', (e) => {
      appendLogMessage(actionLog, e.detail.text);
    });
    client.events.addEventListener('disconnected', () => {
      if (roomStatus) roomStatus.textContent = 'Disconnected from the room.';
    });
  }

  leaveButton?.addEventListener('click', leaveRoom);

  chatForm?.addEventListener('submit', (e) => {
    e.preventDefault();
    const text = chatInput?.value.trim();
    if (!text || !client || !currentRoom) return;
    client.send(chatFrame(currentRoom, text));
    chatInput.value = '';
  });

  if (battlefield) {
    initBoardInteractions(battlefield, (action) => {
      if (client && currentRoom) client.send(boardFrame(currentRoom, action));
    });
  }

  const rail = document.getElementById('rail');
  const roomBody = document.querySelector('.room-body');
  const railResizer = document.getElementById('railResizer');
  if (roomBody && railResizer) {
    const setRailWidth = (width) => {
      const rect = roomBody.getBoundingClientRect();
      const clamped = Math.max(240, Math.min(rect.width - 360, width));
      roomBody.style.gridTemplateColumns = `1fr 8px ${clamped}px`;
    };
    initSeparator(railResizer, {
      onPointer: (e) => setRailWidth(roomBody.getBoundingClientRect().right - e.clientX),
      onKey: (e) => {
        const width = rail?.getBoundingClientRect().width ?? 340;
        if (e.key === 'ArrowLeft') setRailWidth(width + 24);
        else if (e.key === 'ArrowRight') setRailWidth(width - 24);
        else return false;
        return true;
      },
    });
  }

  const railSplitter = document.getElementById('railSplitter');
  if (rail && railSplitter) {
    const setLogHeight = (height) => {
      const max = rail.getBoundingClientRect().height - 200;
      const clamped = Math.max(120, Math.min(max, height));
      rail.style.gridTemplateRows = `${clamped}px 10px 1fr`;
    };
    initSeparator(railSplitter, {
      onPointer: (e) => setLogHeight(e.clientY - rail.getBoundingClientRect().top),
      onKey: (e) => {
        const logHeight = rail.querySelector('.pane')?.getBoundingClientRect().height ?? 200;
        if (e.key === 'ArrowUp') setLogHeight(logHeight - 24);
        else if (e.key === 'ArrowDown') setLogHeight(logHeight + 24);
        else return false;
        return true;
      },
    });
  }

  spawnButton?.addEventListener('click', async () => {
    if (!client || !currentRoom) return;
    try {
      const { cards } = await (await fetch('/api/cards/random/1')).json();
      const picked = cards?.[0];
      if (!picked) return;
      client.send(
        addCardFrame(currentRoom, {
          id: `${picked.card_id}-${Date.now()}-${Math.floor(Math.random() * 1e6)}`,
          name: picked.name,
          img: picked.image_path,
          x: 20 + Math.floor(Math.random() * 220),
          y: 20 + Math.floor(Math.random() * 220),
        }),
      );
    } catch (_) {
      if (roomStatus) roomStatus.textContent = 'Could not spawn a card.';
    }
  });

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
