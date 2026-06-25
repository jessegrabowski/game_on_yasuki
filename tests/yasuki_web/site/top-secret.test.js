import { describe, it, beforeEach, mock } from 'node:test';
import assert from 'node:assert/strict';

import { resetDOM } from '../deck_builder/dom-shim.js';
import { makeRoom } from './fixtures.js';

class FakeWebSocket {
  static OPEN = 1;
  static instances = [];
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    this.sent = [];
    this._listeners = {};
    FakeWebSocket.instances.push(this);
  }
  addEventListener(type, fn) {
    (this._listeners[type] ||= []).push(fn);
  }
  send(data) {
    this.sent.push(JSON.parse(data));
  }
  close() {
    this.readyState = 3;
  }
  _emit(type, event) {
    (this._listeners[type] || []).forEach((fn) => fn(event));
  }
  accept() {
    this.readyState = FakeWebSocket.OPEN;
    this._emit('open', {});
  }
  deliver(message) {
    this._emit('message', { data: JSON.stringify(message) });
  }
}

function fakeLocalStorage() {
  const store = {};
  return {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => {
      store[k] = String(v);
    },
    removeItem: (k) => {
      delete store[k];
    },
  };
}

globalThis.fetch = mock.fn();
globalThis.WebSocket = FakeWebSocket;
globalThis.location = { protocol: 'http:', host: 'testserver' };

import {
  listRooms,
  createRoom,
  deleteRoom,
} from '../../../src/yasuki_web/static/site/rooms-api.js';
import {
  renderRooms,
  renderPlayers,
  appendChatMessage,
  appendLogMessage,
  chatFrame,
  loadDeckFrame,
  readyFrame,
  resetFrame,
  initSeparator,
  readDeleteTokens,
  rememberDeleteToken,
  forgetDeleteToken,
  ownedRoomIds,
  init,
} from '../../../src/yasuki_web/static/site/top-secret.js';

function mockJSON(body) {
  fetch.mock.mockImplementation(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(body) }),
  );
}

const ok = (body) => Promise.resolve({ ok: true, json: () => Promise.resolve(body) });

beforeEach(() => {
  resetDOM();
  fetch.mock.resetCalls();
  fetch.mock.restore();
  FakeWebSocket.instances = [];
  globalThis.localStorage = fakeLocalStorage();
});

describe('rooms-api', () => {
  it('lists rooms with a plain GET', async () => {
    mockJSON({ rooms: [makeRoom()], count: 1, total_rooms: 1 });
    const result = await listRooms();
    assert.equal(result.count, 1);
    const [url, options] = fetch.mock.calls[0].arguments;
    assert.equal(url, '/api/rooms');
    assert.equal(options?.method ?? 'GET', 'GET');
  });

  it('rejects when the server responds non-ok', async () => {
    fetch.mock.mockImplementation(() =>
      Promise.resolve({ ok: false, status: 401, statusText: 'Unauthorized' }),
    );
    await assert.rejects(() => listRooms(), { message: '401 Unauthorized' });
  });

  it('creates a room with the documented POST body', async () => {
    mockJSON({ room_id: 'r1', room: makeRoom({ id: 'r1' }), delete_token: 't', websocket_url: '/ws/r1' });
    await createRoom({ name: 'Crab Table', maxPlayers: 2 });
    const [url, options] = fetch.mock.calls[0].arguments;
    assert.equal(url, '/api/rooms');
    assert.equal(options.method, 'POST');
    assert.deepEqual(JSON.parse(options.body), { max_players: 2, room_name: 'Crab Table' });
  });

  it('omits room_name when no name is given', async () => {
    mockJSON({ room_id: 'r1', room: makeRoom(), delete_token: 't', websocket_url: '/ws/r1' });
    await createRoom();
    const { body } = fetch.mock.calls[0].arguments[1];
    assert.deepEqual(JSON.parse(body), { max_players: 2 });
  });

  it('deletes a room with its delete token', async () => {
    mockJSON({ message: 'gone', room_id: 'r1' });
    await deleteRoom('r1', 'secret-token');
    const [url, options] = fetch.mock.calls[0].arguments;
    assert.equal(url, '/api/rooms/r1');
    assert.equal(options.method, 'DELETE');
    assert.equal(options.headers['X-Delete-Token'], 'secret-token');
  });
});

describe('renderRooms', () => {
  it('renders a row from the real room shape with a join control', () => {
    const list = document.getElementById('roomList');
    renderRooms(list, [makeRoom({ id: 'abc', name: 'Crab Table', players: ['Ada'] })]);
    assert.match(list.innerHTML, /Crab Table/);
    assert.match(list.innerHTML, /1\/2/);
    assert.match(list.innerHTML, /data-room-id="abc"/);
  });

  it('shows a Close control only for rooms you own', () => {
    const list = document.getElementById('roomList');
    renderRooms(list, [makeRoom({ id: 'mine' })], new Set(['mine']));
    assert.match(list.innerHTML, /data-close-id="mine"/);
  });

  it('omits Close for rooms you do not own', () => {
    const list = document.getElementById('roomList');
    renderRooms(list, [makeRoom({ id: 'theirs' })]);
    assert.doesNotMatch(list.innerHTML, /close-id/);
  });

  it('escapes room-supplied text', () => {
    const list = document.getElementById('roomList');
    renderRooms(list, [makeRoom({ name: '<script>x</script>' })]);
    assert.doesNotMatch(list.innerHTML, /<script>/);
  });

  it('shows an empty state when there are no rooms', () => {
    const list = document.getElementById('roomList');
    renderRooms(list, []);
    assert.match(list.innerHTML, /No open rooms/);
  });

  it('reports occupancy as players over capacity', () => {
    const list = document.getElementById('roomList');
    renderRooms(list, [makeRoom({ max_players: 4, players: ['Ada', 'Kenji'] })]);
    assert.match(list.innerHTML, /2\/4/);
  });
});

describe('renderPlayers', () => {
  it('lists each player and marks the local one', () => {
    const list = document.getElementById('playerList');
    renderPlayers(list, ['Ada', 'Kenji'], 'Ada');
    assert.match(list.innerHTML, /Ada/);
    assert.match(list.innerHTML, /Kenji/);
    assert.match(list.innerHTML, /Ada <span class="you">\(you\)<\/span>/);
    assert.doesNotMatch(list.innerHTML, /Kenji <span class="you">/);
  });

  it('escapes player names', () => {
    const list = document.getElementById('playerList');
    renderPlayers(list, ['<script>x</script>'], null);
    assert.doesNotMatch(list.innerHTML, /<script>/);
  });
});

describe('appendChatMessage', () => {
  it('appends a line with the sender wrapped and the text shown', () => {
    const log = document.getElementById('chatLog');
    appendChatMessage(log, 'Ada', 'hello');
    assert.match(log.innerHTML, /class="chat-sender">Ada</);
    assert.match(log.innerHTML, /hello/);
  });

  it('escapes markup in the sender and text', () => {
    const log = document.getElementById('chatLog');
    appendChatMessage(log, '<b>x</b>', '<script>y</script>');
    assert.doesNotMatch(log.innerHTML, /<script>/);
    assert.doesNotMatch(log.innerHTML, /<b>/);
  });
});

describe('appendLogMessage', () => {
  it('renders prose as text and a card segment as a link', () => {
    const log = document.getElementById('actionLog');
    appendLogMessage(log, [{ text: 'Ada bowed ' }, { card_id: 'c1', name: 'Hida Kisada' }]);

    const segments = log.children[0].children;
    assert.equal(segments[0].textContent, 'Ada bowed ');
    assert.equal(segments[1].className, 'log-card-link');
    assert.equal(segments[1].dataset.cardId, 'c1');
    assert.equal(segments[1].textContent, 'Hida Kisada');
  });

  it('renders an unknown card ("a card") as plain text, not a link', () => {
    const log = document.getElementById('actionLog');
    appendLogMessage(log, [{ text: 'Ada drew a card' }]);
    assert.equal(log.children[0].children[0].className, '');
  });
});

describe('chatFrame', () => {
  it('builds a CHAT client message for the room', () => {
    assert.deepEqual(chatFrame('r1', 'hi'), { type: 'CHAT', room: 'r1', chat: { text: 'hi' } });
  });
});

describe('setup frames', () => {
  it('wraps deck YAML in a LOAD_DECK frame', () => {
    assert.deepEqual(loadDeckFrame('r1', 'name: D'), {
      type: 'LOAD_DECK',
      room: 'r1',
      load_deck: { yaml: 'name: D' },
    });
  });

  it('defaults READY to a two-player ready', () => {
    assert.deepEqual(readyFrame('r1'), {
      type: 'READY',
      room: 'r1',
      ready: { ready: true, solo: false },
    });
  });

  it('marks a goldfish READY as solo', () => {
    assert.deepEqual(readyFrame('r1', { solo: true }), {
      type: 'READY',
      room: 'r1',
      ready: { ready: true, solo: true },
    });
  });

  it('builds a parameterless RESET frame', () => {
    assert.deepEqual(resetFrame('r1'), { type: 'RESET', room: 'r1' });
  });
});

describe('initSeparator', () => {
  function wire() {
    const handle = document.getElementById('separator');
    const dragged = [];
    initSeparator(handle, {
      onPointer: (e) => dragged.push(e.clientX),
      onKey: (e) => e.key === 'ArrowLeft',
    });
    return { handle, dragged };
  }

  it('forwards pointer moves only while a drag is in progress', () => {
    const { handle, dragged } = wire();
    handle._emit('pointermove', { clientX: 1 });
    assert.deepEqual(dragged, [], 'no drag yet');

    handle._emit('pointerdown', { pointerId: 1 });
    handle._emit('pointermove', { clientX: 2 });
    handle._emit('pointerup', {});
    handle._emit('pointermove', { clientX: 3 });
    assert.deepEqual(dragged, [2], 'only the move between down and up');
  });

  it('stops dragging on pointercancel', () => {
    const { handle, dragged } = wire();
    handle._emit('pointerdown', { pointerId: 1 });
    handle._emit('pointercancel', {});
    handle._emit('pointermove', { clientX: 9 });
    assert.deepEqual(dragged, []);
  });

  it('suppresses the default only for keys onKey claims', () => {
    const { handle } = wire();
    let prevented = 0;
    const press = (key) => handle._emit('keydown', { key, preventDefault: () => (prevented += 1) });
    press('ArrowLeft');
    press('ArrowRight');
    assert.equal(prevented, 1);
  });
});

describe('delete-token persistence', () => {
  it('remembers, reads back, and exposes owned room ids', () => {
    rememberDeleteToken('r1', 'tok1');
    assert.deepEqual(readDeleteTokens(), { r1: 'tok1' });
    assert.deepEqual([...ownedRoomIds()], ['r1']);
  });

  it('forgets a token', () => {
    rememberDeleteToken('r1', 'tok1');
    forgetDeleteToken('r1');
    assert.deepEqual(readDeleteTokens(), {});
  });

  it('reads empty when storage is unavailable', () => {
    globalThis.localStorage = undefined;
    assert.deepEqual(readDeleteTokens(), {});
    assert.deepEqual([...ownedRoomIds()], []);
  });

  it('survives corrupt stored JSON', () => {
    globalThis.localStorage.setItem('yasuki.play.deleteTokens.v1', 'not json');
    assert.deepEqual(readDeleteTokens(), {});
  });
});

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function installRouter(overrides = {}) {
  const routes = {
    'GET /api/config': () => ok({ image_base_url: '/images' }),
    'GET /api/rooms': () => ok({ rooms: [makeRoom({ id: 'r1', name: 'Crab Table' })] }),
    'POST /api/rooms': () => ok({ room_id: 'r2', delete_token: 'tok', websocket_url: '/ws/r2' }),
    'GET /api/cards/random/1': () =>
      ok({ cards: [{ card_id: 'c9', name: 'Spy', image_path: 'a.jpg' }] }),
    ...overrides,
  };
  fetch.mock.mockImplementation((url, options) =>
    (routes[`${options?.method ?? 'GET'} ${url}`] || (() => ok({})))(),
  );
}

async function joinedRoom() {
  installRouter();
  init();
  await flush();
  document.getElementById('playerName').value = 'Ada';
  document.getElementById('roomList')._emit('click', { target: { dataset: { roomId: 'r1' } } });
  const ws = FakeWebSocket.instances.at(-1);
  ws.accept();
  ws.deliver({ type: 'HELLO', room: 'r1', your_seat: 'P1', players: ['Ada'] });
  return ws;
}

describe('init (room client wiring)', () => {
  it('loads and renders the open rooms on start', async () => {
    installRouter();
    init();
    await flush();
    assert.match(document.getElementById('roomList').innerHTML, /Crab Table/);
  });

  it('joins a room from the list and connects a WebSocket', async () => {
    const ws = await joinedRoom();
    assert.equal(ws.url, 'ws://testserver/ws/r1');
    assert.equal(document.getElementById('roomView').hidden, false);
    assert.match(document.getElementById('playerList').innerHTML, /Ada/);
  });

  it('routes inbound SNAPSHOT, CHAT, and LOG frames to the panes', async () => {
    const ws = await joinedRoom();
    ws.deliver({
      type: 'SNAPSHOT',
      room: 'r1',
      snapshot: {
        seats: {
          P1: { name: 'Ada', honor: 0, ready: false, connected: true },
          P2: { name: 'Kenji', honor: 0, ready: false, connected: true },
        },
        battlefield: [{ id: 'c1', name: 'X', img: 'a.jpg', x: 1, y: 2, face_up: true, hidden: false }],
      },
    });
    ws.deliver({ type: 'CHAT', from: 'Ada', text: 'hello there' });
    ws.deliver({ type: 'LOG', room: 'r1', parts: [{ text: 'Kenji joined' }] });

    assert.match(document.getElementById('playerList').innerHTML, /Kenji/);
    assert.equal(document.getElementById('battlefield').children.length, 1);
    assert.match(document.getElementById('chatLog').innerHTML, /hello there/);
    const lastLog = document.getElementById('actionLog').children.at(-1);
    assert.equal(lastLog.children[0].textContent, 'Kenji joined');
  });

  it('highlights the referenced card anywhere on the stage when a log link is clicked', async () => {
    await joinedRoom();
    const boardStage = document.getElementById('boardStage');
    const cardEl = document.createElement('div');
    boardStage.querySelector = () => cardEl;

    const link = { dataset: { cardId: 'c1' } };
    const realSetTimeout = globalThis.setTimeout;
    globalThis.setTimeout = () => 0;
    try {
      document.getElementById('actionLog')._emit('click', {
        target: { closest: (sel) => (sel === '.log-card-link' ? link : null) },
      });
    } finally {
      globalThis.setTimeout = realSetTimeout;
    }

    assert.ok(cardEl.classList.contains('highlight'));
  });

  it('sends a CHAT frame on chat submit and clears the input', async () => {
    const ws = await joinedRoom();
    const input = document.getElementById('chatInput');
    input.value = 'gg';
    document.getElementById('chatForm')._emit('submit', { preventDefault() {} });

    assert.deepEqual(ws.sent.find((m) => m.type === 'CHAT'), {
      type: 'CHAT',
      room: 'r1',
      chat: { text: 'gg' },
    });
    assert.equal(input.value, '');
  });

  it('sends READY, goldfish READY, and RESET from the room buttons', async () => {
    const ws = await joinedRoom();
    document.getElementById('readyButton')._emit('click', {});
    document.getElementById('goldfishButton')._emit('click', {});
    document.getElementById('newGameButton')._emit('click', {});

    assert.ok(ws.sent.some((m) => m.type === 'READY' && m.ready.solo === false));
    assert.ok(ws.sent.some((m) => m.type === 'READY' && m.ready.solo === true));
    assert.deepEqual(ws.sent.find((m) => m.type === 'RESET'), { type: 'RESET', room: 'r1' });
  });

  it('sends LOAD_DECK with the chosen file contents', async () => {
    const ws = await joinedRoom();
    const input = document.getElementById('deckFileInput');
    input.files = [{ text: () => Promise.resolve('name: D') }];
    input._emit('change', { target: input });
    await flush();

    assert.deepEqual(ws.sent.find((m) => m.type === 'LOAD_DECK'), {
      type: 'LOAD_DECK',
      room: 'r1',
      load_deck: { yaml: 'name: D' },
    });
  });

  it('draws from a deck on double-click', async () => {
    const ws = await joinedRoom();
    document.getElementById('selfTableau')._emit('dblclick', {
      target: { closest: (s) => (s === '.deck' ? { dataset: { owner: 'P1', side: 'FATE' } } : null) },
    });
    assert.deepEqual(ws.sent.find((m) => m.type === 'INTENT'), {
      type: 'INTENT',
      room: 'r1',
      intent: { op: 'DRAW', deck: { owner: 'P1', side: 'FATE' } },
    });
  });

  it('forwards a board drag as an INTENT frame with the room injected', async () => {
    const ws = await joinedRoom();
    const stage = document.getElementById('boardStage');
    const classes = new Set(['board-card']);
    const cardEl = {
      dataset: { cardId: 'c1' },
      style: {},
      classList: { add: (c) => classes.add(c), remove: (c) => classes.delete(c), contains: (c) => classes.has(c) },
      getBoundingClientRect: () => ({ left: 0, top: 0 }),
    };
    stage._emit('pointerdown', {
      button: 0,
      clientX: 10,
      clientY: 10,
      target: { closest: (s) => (s === '[data-card-id]' ? cardEl : null) },
    });
    stage._emit('pointerup', {
      clientX: 20,
      clientY: 20,
      target: { closest: (s) => (s === '[data-zone]' ? { dataset: { zone: 'battlefield' } } : null) },
    });

    const intent = ws.sent.find((m) => m.type === 'INTENT');
    assert.equal(intent.room, 'r1');
    assert.equal(intent.intent.op, 'SET_CARD_POS');
  });

  it('spawns a random card as a SPAWN frame', async () => {
    const ws = await joinedRoom();
    document.getElementById('spawnCard')._emit('click', {});
    await flush();

    const spawn = ws.sent.find((m) => m.type === 'SPAWN');
    assert.ok(spawn, 'a SPAWN frame is sent');
    assert.equal(spawn.room, 'r1');
    assert.equal(spawn.spawn.name, 'Spy');
  });

  it('creates a room, stores its delete token, and joins it', async () => {
    installRouter();
    init();
    await flush();
    document.getElementById('playerName').value = 'Ada';
    document.getElementById('createForm')._emit('submit', { preventDefault() {} });
    await flush();

    assert.equal(readDeleteTokens().r2, 'tok');
    assert.equal(FakeWebSocket.instances.at(-1).url, 'ws://testserver/ws/r2');
  });

  it('leaves a room, closing the client and returning to the lobby', async () => {
    const ws = await joinedRoom();
    document.getElementById('leaveRoom')._emit('click', {});

    assert.equal(ws.readyState, 3, 'client socket closed');
    assert.equal(document.getElementById('roomView').hidden, true);
    assert.equal(document.getElementById('lobbyView').hidden, false);
  });

  it('joins a room by typed id from the join form', async () => {
    installRouter();
    init();
    await flush();
    document.getElementById('playerName').value = 'Ada';
    document.getElementById('joinRoomId').value = 'r1';
    document.getElementById('joinForm')._emit('submit', { preventDefault() {} });

    assert.equal(FakeWebSocket.instances.at(-1).url, 'ws://testserver/ws/r1');
  });

  it('prompts for a name before joining', async () => {
    installRouter();
    init();
    await flush();
    document.getElementById('roomList')._emit('click', { target: { dataset: { roomId: 'r1' } } });

    assert.equal(FakeWebSocket.instances.length, 0, 'no connection without a name');
    assert.match(document.getElementById('lobbyStatus').textContent, /name/i);
  });

  it('closes an owned room via its Close control', async () => {
    rememberDeleteToken('r1', 'tok');
    let deleted = null;
    installRouter({
      'DELETE /api/rooms/r1': () => {
        deleted = 'r1';
        return ok({ message: 'gone' });
      },
    });
    init();
    await flush();
    document.getElementById('roomList')._emit('click', { target: { dataset: { closeId: 'r1' } } });
    await flush();

    assert.equal(deleted, 'r1');
    assert.deepEqual(readDeleteTokens(), {}, 'token forgotten after close');
  });

  it('reports a status when the room list fails to load', async () => {
    installRouter({
      'GET /api/rooms': () => Promise.resolve({ ok: false, status: 503, statusText: 'Down' }),
    });
    init();
    await flush();

    assert.match(document.getElementById('lobbyStatus').textContent, /Could not load rooms/);
  });

  it('resizes the rail and the log panes within their bounds', async () => {
    await joinedRoom();
    const roomBody = document.querySelector('.room-body');
    const rail = document.getElementById('rail');

    // roomBody right is 200; a pointer at x=50 wants a 150px rail, clamped up to the 240px minimum.
    document.getElementById('railResizer')._emit('pointerdown', { pointerId: 1 });
    document.getElementById('railResizer')._emit('pointermove', { clientX: 50 });
    assert.match(roomBody.style.gridTemplateColumns, /240px$/);

    // rail height is 200, so the log pane's max is 200-200=0 and it clamps to the 120px minimum.
    document.getElementById('railSplitter')._emit('pointerdown', { pointerId: 1 });
    document.getElementById('railSplitter')._emit('pointermove', { clientY: 150 });
    assert.match(rail.style.gridTemplateRows, /^120px/);
  });

  it('resizes via the keyboard and suppresses the arrow-key scroll', async () => {
    await joinedRoom();
    let prevented = 0;
    const press = (id, key) =>
      document.getElementById(id)._emit('keydown', { key, preventDefault: () => (prevented += 1) });

    press('railResizer', 'ArrowLeft');
    press('railSplitter', 'ArrowUp');
    press('railResizer', 'PageUp'); // unhandled key: no preventDefault

    assert.equal(prevented, 2);
    assert.match(document.querySelector('.room-body').style.gridTemplateColumns, /px$/);
  });

  it('prompts for a name before creating a room', async () => {
    installRouter();
    init();
    await flush();
    document.getElementById('createForm')._emit('submit', { preventDefault() {} });

    assert.match(document.getElementById('lobbyStatus').textContent, /name/i);
    const posts = fetch.mock.calls.filter((c) => c.arguments[1]?.method === 'POST');
    assert.equal(posts.length, 0, 'no room is created');
  });
});
