// WIP online-play lobby, served at the unlinked, password-gated /top-secret.html route until
// launch.

import { esc, fetchConfig } from './card-common.js';
import { listRooms, createRoom, deleteRoom } from './rooms-api.js';
import { connectRoom } from './ws-client.js';
import {
  renderBoard,
  renderTableau,
  renderHand,
  renderPanel,
  initPanelHonor,
  spawnMessage,
  drawIntent,
  initBoardInteractions,
  highlightCard,
  deckAnchor,
  pregameAnchor,
  placeUnplacedCards,
  setBackArt,
  backArtBySide,
} from './board.js';
import { openDeckDialog } from './deck-dialog.js';

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

// `filename` is a fallback human label only — the server prefers the deck name inside the YAML.
export function loadDeckFrame(room, yaml, filename = null) {
  const load_deck = { yaml };
  if (filename) load_deck.filename = filename;
  return { type: 'LOAD_DECK', room, load_deck };
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
  const leaveButton = document.getElementById('leaveRoom');
  const chatLog = document.getElementById('chatLog');
  const chatForm = document.getElementById('chatForm');
  const chatInput = document.getElementById('chatInput');
  const actionLog = document.getElementById('actionLog');
  // Surface a system notice (connection drop, a rejected action) as a line in the game log.
  const logSystem = (text) => actionLog && appendLogMessage(actionLog, [{ text }]);
  const battlefield = document.getElementById('battlefield');
  let boardInteractions = null;
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
  // SEARCH_DECK carries its "top N" inside the intent as `value`; mirror it here between the request
  // and the DECK_CONTENTS reply so it can cap the dialog (null = whole deck).
  let pendingDeckLimit = null;
  let imgBase = '/images';
  let debug = false;
  fetchConfig().then((config) => {
    imgBase = config.imageBase;
    debug = config.debug;
    loadCardBacks(imgBase);
  });

  // Load the generic per-side card backs so face-down cards render a real back, not a flat gradient.
  async function loadCardBacks(base) {
    try {
      const { backs } = await (await fetch('/api/card-backs')).json();
      setBackArt(backArtBySide(backs, base));
    } catch (_) {
      // Leave the gradient fallback in place when the backs can't be fetched.
    }
  }

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
    });
    client.events.addEventListener('SNAPSHOT', (e) => {
      const snapshot = e.detail.snapshot ?? {};
      const seats = snapshot.seats ?? {};
      const present = Object.values(seats)
        .filter((seat) => seat.connected)
        .map((seat) => seat.name);
      renderPlayers(playerList, present, myName);
      // Decks only carry cards once setup deals the table; an empty table is the pre-game/reset
      // state. Resolve the pending toggles off that: dealt clears Ready, cleared clears New game.
      const dealt = Object.values(snapshot.decks ?? {}).some((deck) => deck.count > 0 || deck.top);
      (dealt ? readyButton : newGameButton)?.classList.remove('btn-gold');
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
      const anchorFor = (owner, isViewer, group) => {
        const tableau = isViewer ? selfTableau : opponentTableau;
        if (group === 'PREGAME') return pregameAnchor(tableau, battlefield, isViewer);
        return deckAnchor(tableau, battlefield, isViewer, group);
      };
      const onTable = placeUnplacedCards(snapshot.battlefield ?? [], you, anchorFor);
      renderBoard(battlefield, onTable, imgBase);
      // The re-render rebuilt every card element, so reattach the selection outline by card id.
      boardInteractions?.markSelection();
      renderHand(selfHand, handOf(you), imgBase);
      renderHand(opponentHand, handOf(opponent), imgBase);
      if (selfHand) selfHand.dataset.owner = you;
      if (opponentHand) opponentHand.dataset.owner = opponent;
      renderPanel(selfPanel, seats[you] ?? {}, { editable: true });
      renderPanel(opponentPanel, seats[opponent] ?? {}, { editable: false });
    });
    client.events.addEventListener('CHAT', (e) => {
      appendChatMessage(chatLog, e.detail.from, e.detail.text);
    });
    client.events.addEventListener('LOG', (e) => {
      appendLogMessage(actionLog, e.detail.parts);
    });
    client.events.addEventListener('DECK_CONTENTS', (e) => {
      openDeckDialog({
        deck: e.detail.deck,
        cards: e.detail.cards ?? [],
        imgBase,
        limit: pendingDeckLimit,
        send: (frame) => sendToRoom({ ...frame, room: currentRoom }),
      });
    });
    client.events.addEventListener('ERROR', (e) => {
      const msg = e.detail?.message ?? 'Something went wrong.';
      // A debug-level error (a rejected intent) is silent in prod — the SNAPSHOT revert is the
      // player's feedback — and tagged when the debug flag is on. Other errors always show.
      if (e.detail?.debug) {
        if (debug) logSystem(`[debug] ${msg}`);
        return;
      }
      logSystem(msg);
    });
    client.events.addEventListener('disconnected', () => {
      logSystem('Disconnected from the room.');
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

  const submitDeck = (yaml, filename = null) => {
    const text = yaml?.trim();
    if (!text) return;
    sendToRoom(loadDeckFrame(currentRoom, text, filename));
  };

  // Strip the extension off a chosen file's name to use as the fallback deck label.
  const deckLabel = (name) => name?.replace(/\.[^./]+$/, '') || null;

  // Prefer the File System Access picker (it remembers the last directory via DECK_PICKER_OPTIONS.id);
  // fall back to a hidden file input where it is unsupported, mirroring the deck builder's import.
  loadDeckButton?.addEventListener('click', async () => {
    if (typeof globalThis.showOpenFilePicker === 'function') {
      try {
        const [handle] = await globalThis.showOpenFilePicker(DECK_PICKER_OPTIONS);
        const file = await handle.getFile();
        submitDeck(await file.text(), deckLabel(file.name));
      } catch (e) {
        if (e?.name !== 'AbortError') logSystem('Could not load the deck file.');
      }
    } else {
      deckFileInput?.click();
    }
  });

  deckFileInput?.addEventListener('change', (e) => {
    const file = e.target.files?.[0];
    if (file) file.text().then((text) => submitDeck(text, deckLabel(file.name)));
    e.target.value = '';
  });

  // Ready and New game glow gold the moment they're clicked to show the request is in flight, then
  // revert to white when the SNAPSHOT confirms it resolved (a dealt table clears Ready; a cleared
  // table clears New game — see the SNAPSHOT handler).
  readyButton?.addEventListener('click', () => {
    readyButton.classList.add('btn-gold');
    sendToRoom(readyFrame(currentRoom));
  });
  goldfishButton?.addEventListener('click', () => sendToRoom(readyFrame(currentRoom, { solo: true })));
  newGameButton?.addEventListener('click', () => {
    newGameButton.classList.add('btn-gold');
    sendToRoom(resetFrame(currentRoom));
  });

  const boardStage = document.getElementById('boardStage');
  if (boardStage && battlefield) {
    // A SEARCH_DECK intent carries its top-N as `intent.value`; mirror it into pendingDeckLimit to
    // cap the DECK_CONTENTS dialog, but pass the message through untouched so the server logs it.
    boardInteractions = initBoardInteractions(boardStage, battlefield, (message) => {
      if (message.intent?.op === 'SEARCH_DECK') pendingDeckLimit = message.intent.value ?? null;
      sendToRoom({ ...message, room: currentRoom });
    });
  }

  // Only the local panel is wired, so the opponent's honor stays read-only.
  if (selfPanel) {
    initPanelHonor(selfPanel, (message) => sendToRoom({ ...message, room: currentRoom }));
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
      logSystem('Could not spawn a card.');
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
