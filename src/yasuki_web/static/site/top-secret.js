// WIP online-play lobby, served at the unlinked, password-gated /top-secret.html route until
// launch.

import { esc, fetchImageBase } from './card-common.js';
import { listRooms, createRoom, deleteRoom } from './rooms-api.js';
import { connectRoom } from './ws-client.js';
import {
  renderBoard,
  renderTableau,
  renderHand,
  renderPanel,
  spawnMessage,
  drawIntent,
  initBoardInteractions,
  highlightCard,
  deckAnchor,
  placePregameCards,
} from './board.js';

const DELETE_TOKENS_KEY = 'yasuki.play.deleteTokens.v1';

export function roomItemHTML(room, ownedIds = new Set()) {
  const players = (room.players || []).length;
  const closeButton = ownedIds.has(room.id)
    ? `<button class="close-btn" data-close-id="${esc(room.id)}">Close</button>`
    : '';
  return (
    `<li>` +
    `<span class="room-name">${esc(room.name)}</span>` +
    `<span class="room-meta">${players}/${room.max_players} · ${esc(room.id)}</span>` +
    `<span class="room-buttons">` +
    `<button class="join-btn" data-room-id="${esc(room.id)}">Join</button>` +
    closeButton +
    `</span>` +
    `</li>`
  );
}

export function renderRooms(listEl, rooms, ownedIds = new Set()) {
  listEl.innerHTML = rooms.length
    ? rooms.map((room) => roomItemHTML(room, ownedIds)).join('')
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

// Render a game-log line from its segments: prose as plain spans, each referenced card as a link
// (data-card-id) the room wires up to highlight the card on the board.
export function appendLogMessage(logEl, parts) {
  const li = document.createElement('li');
  for (const part of parts) {
    const span = document.createElement('span');
    if (part.card_id) {
      span.className = 'log-card-link';
      span.dataset.cardId = part.card_id;
      span.textContent = part.name;
    } else {
      span.textContent = part.text;
    }
    li.appendChild(span);
  }
  logEl.appendChild(li);
  logEl.scrollTop = logEl.scrollHeight;
}

export function chatFrame(room, text) {
  return { type: 'CHAT', room, chat: { text } };
}

export function loadDeckFrame(room, yaml) {
  return { type: 'LOAD_DECK', room, load_deck: { yaml } };
}

export function readyFrame(room, { solo = false } = {}) {
  return { type: 'READY', room, ready: { ready: true, solo } };
}

export function resetFrame(room) {
  return { type: 'RESET', room };
}

// File-picker options for loading a deck. The id lets the browser reopen the picker at the last
// directory used for this same id, across sessions.
const DECK_PICKER_OPTIONS = {
  id: 'yasuki-deck-load',
  types: [{ description: 'Deck YAML', accept: { 'application/yaml': ['.yaml', '.yml'] } }],
};

// Wire a draggable separator: pointer-drag calls onPointer; arrow keys call onKey, which returns
// true when it handled the event (so the default scroll is suppressed).
export function initSeparator(handle, { onPointer, onKey }) {
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

// The delete token is the only way to close a room you created, so stash it client-side. Access is
// best-effort: private mode and quota throw, and losing a token only forgoes cleanup of that room.
export function readDeleteTokens() {
  try {
    return JSON.parse(globalThis.localStorage?.getItem(DELETE_TOKENS_KEY) || '{}');
  } catch (_) {
    return {};
  }
}

function writeDeleteTokens(tokens) {
  try {
    globalThis.localStorage?.setItem(DELETE_TOKENS_KEY, JSON.stringify(tokens));
  } catch (_) {
    /* best-effort */
  }
}

export function rememberDeleteToken(roomId, token) {
  const tokens = readDeleteTokens();
  tokens[roomId] = token;
  writeDeleteTokens(tokens);
}

export function forgetDeleteToken(roomId) {
  const tokens = readDeleteTokens();
  delete tokens[roomId];
  writeDeleteTokens(tokens);
}

export const ownedRoomIds = () => new Set(Object.keys(readDeleteTokens()));

export function init() {
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
  const opponentTableau = document.getElementById('opponentTableau');
  const selfTableau = document.getElementById('selfTableau');
  const opponentHand = document.getElementById('opponentHand');
  const selfHand = document.getElementById('selfHand');
  const opponentPanel = document.getElementById('opponentPanel');
  const selfPanel = document.getElementById('selfPanel');
  const spawnButton = document.getElementById('spawnCard');
  const loadDeckButton = document.getElementById('loadDeckButton');
  const deckFileInput = document.getElementById('deckFileInput');
  const readyButton = document.getElementById('readyButton');
  const goldfishButton = document.getElementById('goldfishButton');
  const newGameButton = document.getElementById('newGameButton');

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
      renderRooms(roomList, rooms, ownedRoomIds());
      setStatus('');
    } catch (_) {
      setStatus('Could not load rooms.');
    }
  }

  async function closeRoom(roomId) {
    const token = readDeleteTokens()[roomId];
    if (!token) return;
    try {
      await deleteRoom(roomId, token);
      forgetDeleteToken(roomId);
      loadRooms();
    } catch (_) {
      setStatus('Could not close the room.');
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
    client.events.addEventListener('SNAPSHOT', (e) => {
      const snapshot = e.detail.snapshot ?? {};
      const seats = snapshot.seats ?? {};
      const present = Object.values(seats)
        .filter((seat) => seat.connected)
        .map((seat) => seat.name);
      renderPlayers(playerList, present, myName);
      const you = snapshot.your_seat;
      // The context menu reads the viewer's seat off the board root to gate "Send to…"/deck/province
      // actions to the cards and zones this player owns.
      if (boardStage) boardStage.dataset.viewerSeat = you ?? '';
      if (!you) {
        renderBoard(battlefield, snapshot.battlefield ?? [], imgBase);
        return;
      }
      const opponent = you === 'P1' ? 'P2' : 'P1';
      const handOf = (seat) => snapshot.zones?.[`${seat}:hand`] ?? [];
      // Tableaus first so the dynasty decks exist to anchor each seat's loose pre-game cards against.
      renderTableau(selfTableau, you, snapshot, imgBase);
      renderTableau(opponentTableau, opponent, snapshot, imgBase);
      const anchorFor = (owner, isViewer) =>
        deckAnchor(isViewer ? selfTableau : opponentTableau, battlefield, isViewer);
      const onTable = placePregameCards(snapshot.battlefield ?? [], you, anchorFor);
      renderBoard(battlefield, onTable, imgBase);
      renderHand(selfHand, handOf(you), imgBase);
      renderHand(opponentHand, handOf(opponent), imgBase);
      if (selfHand) selfHand.dataset.owner = you;
      if (opponentHand) opponentHand.dataset.owner = opponent;
      renderPanel(selfPanel, seats[you] ?? {});
      renderPanel(opponentPanel, seats[opponent] ?? {});
    });
    client.events.addEventListener('CHAT', (e) => {
      appendChatMessage(chatLog, e.detail.from, e.detail.text);
    });
    client.events.addEventListener('LOG', (e) => {
      appendLogMessage(actionLog, e.detail.parts);
    });
    client.events.addEventListener('ERROR', (e) => {
      if (roomStatus) roomStatus.textContent = e.detail?.message ?? 'Something went wrong.';
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

  const sendToRoom = (frame) => {
    if (client && currentRoom) client.send(frame);
  };

  // Double-click one of your decks to draw its top card; the server routes where it lands.
  selfTableau?.addEventListener('dblclick', (e) => {
    const deck = e.target.closest?.('.deck');
    if (deck) sendToRoom({ ...drawIntent(deck.dataset.owner, deck.dataset.side), room: currentRoom });
  });

  const submitDeck = (yaml) => {
    const text = yaml?.trim();
    if (!text) return;
    sendToRoom(loadDeckFrame(currentRoom, text));
    if (roomStatus) roomStatus.textContent = 'Deck loaded — ready up to begin.';
  };

  // Prefer the File System Access picker (it remembers the last directory via DECK_PICKER_OPTIONS.id);
  // fall back to a hidden file input where it is unsupported, mirroring the deck builder's import.
  loadDeckButton?.addEventListener('click', async () => {
    if (typeof globalThis.showOpenFilePicker === 'function') {
      try {
        const [handle] = await globalThis.showOpenFilePicker(DECK_PICKER_OPTIONS);
        submitDeck(await (await handle.getFile()).text());
      } catch (e) {
        if (e?.name !== 'AbortError' && roomStatus) roomStatus.textContent = 'Could not load deck.';
      }
    } else {
      deckFileInput?.click();
    }
  });

  deckFileInput?.addEventListener('change', (e) => {
    const file = e.target.files?.[0];
    if (file) file.text().then(submitDeck);
    e.target.value = '';
  });

  readyButton?.addEventListener('click', () => sendToRoom(readyFrame(currentRoom)));
  goldfishButton?.addEventListener('click', () => sendToRoom(readyFrame(currentRoom, { solo: true })));
  newGameButton?.addEventListener('click', () => sendToRoom(resetFrame(currentRoom)));

  const boardStage = document.getElementById('boardStage');
  if (boardStage && battlefield) {
    initBoardInteractions(boardStage, battlefield, (message) =>
      sendToRoom({ ...message, room: currentRoom }),
    );
  }

  actionLog?.addEventListener('click', (e) => {
    const link = e.target?.closest?.('.log-card-link');
    // Search the whole stage, not just the battlefield: a named card may be in a province or discard.
    if (link && boardStage) highlightCard(boardStage, link.dataset.cardId);
  });

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
      // The server assigns the card id; spawn just carries what to put down.
      client.send({
        ...spawnMessage({
          name: picked.name,
          img: picked.image_path,
          x: 20 + Math.floor(Math.random() * 220),
          y: 20 + Math.floor(Math.random() * 220),
        }),
        room: currentRoom,
      });
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
    const closeId = e.target?.dataset?.closeId;
    if (closeId) {
      closeRoom(closeId);
      return;
    }
    const id = e.target?.dataset?.roomId;
    if (id) joinRoom(id);
  });

  refreshButton?.addEventListener('click', loadRooms);

  loadRooms();
}

if (typeof window !== 'undefined') init();
