import { describe, it, beforeEach, mock } from 'node:test';
import assert from 'node:assert/strict';

import { resetDOM } from '../deck_builder/dom-shim.js';
import { makeRoom } from './fixtures.js';

globalThis.fetch = mock.fn();

import { listRooms, createRoom } from '../../../src/yasuki_web/static/site/rooms-api.js';
import { renderRooms } from '../../../src/yasuki_web/static/site/top-secret.js';

function mockJSON(body) {
  fetch.mock.mockImplementation(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(body) }),
  );
}

beforeEach(() => {
  resetDOM();
  fetch.mock.resetCalls();
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
});

describe('renderRooms', () => {
  it('renders a row from the real room shape with a join control', () => {
    const list = document.getElementById('roomList');
    renderRooms(list, [makeRoom({ id: 'abc', name: 'Crab Table', players: ['Ada'] })]);
    assert.match(list.innerHTML, /Crab Table/);
    assert.match(list.innerHTML, /1\/2/);
    assert.match(list.innerHTML, /data-room-id="abc"/);
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
