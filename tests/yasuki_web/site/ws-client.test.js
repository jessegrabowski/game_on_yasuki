import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

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
    this.sent.push(data);
  }

  close() {
    this.readyState = 3;
    this._emit('close', {});
  }

  _emit(type, event) {
    (this._listeners[type] || []).forEach((fn) => fn(event));
  }

  acceptConnection() {
    this.readyState = FakeWebSocket.OPEN;
    this._emit('open', {});
  }

  deliver(message) {
    this._emit('message', { data: JSON.stringify(message) });
  }

  deliverRaw(data) {
    this._emit('message', { data });
  }

  drop(code = 1006) {
    this._emit('close', { code });
  }
}

globalThis.WebSocket = FakeWebSocket;
globalThis.location = { protocol: 'http:', host: 'testserver' };

const { connectRoom } = await import('../../../src/yasuki_web/static/site/ws-client.js');

const latest = () => FakeWebSocket.instances.at(-1);

beforeEach(() => {
  FakeWebSocket.instances = [];
});

describe('connectRoom', () => {
  it('targets the room WebSocket endpoint', () => {
    connectRoom('aB3xY7zq', 'Ada');
    assert.equal(latest().url, 'ws://testserver/ws/aB3xY7zq');
  });

  it('sends a JOIN frame with the room and name once connected', () => {
    connectRoom('room1', 'Ada');
    latest().acceptConnection();
    assert.deepEqual(JSON.parse(latest().sent[0]), {
      type: 'JOIN',
      room: 'room1',
      join: { name: 'Ada' },
    });
  });

  it('dispatches an inbound message as an event named by its type', () => {
    const client = connectRoom('room1', 'Ada');
    let received = null;
    client.events.addEventListener('HELLO', (e) => {
      received = e.detail;
    });
    latest().acceptConnection();
    latest().deliver({ type: 'HELLO', you: 'Ada', players: ['Ada'] });
    assert.deepEqual(received, { type: 'HELLO', you: 'Ada', players: ['Ada'] });
  });

  it('ignores a malformed inbound frame without dispatching or throwing', () => {
    const client = connectRoom('room1', 'Ada');
    let dispatched = false;
    client.events.addEventListener('HELLO', () => {
      dispatched = true;
    });
    latest().acceptConnection();
    latest().deliverRaw('not json at all');
    assert.equal(dispatched, false);
  });

  it('reconnects once after an unexpected drop, then gives up', () => {
    const client = connectRoom('room1', 'Ada');
    let disconnected = false;
    client.events.addEventListener('disconnected', () => {
      disconnected = true;
    });

    latest().acceptConnection();
    latest().drop();
    assert.equal(FakeWebSocket.instances.length, 2, 'a single reconnect is attempted');
    assert.equal(disconnected, false);

    latest().drop();
    assert.equal(FakeWebSocket.instances.length, 2, 'no second reconnect');
    assert.equal(disconnected, true);
  });

  it('does not reconnect after a policy close', () => {
    const client = connectRoom('room1', 'Ada');
    let disconnected = false;
    client.events.addEventListener('disconnected', () => {
      disconnected = true;
    });
    latest().acceptConnection();
    latest().drop(1008); // rate limit
    assert.equal(FakeWebSocket.instances.length, 1, 'no reconnect on a policy close');
    assert.equal(disconnected, true);
  });

  it('does not reconnect after the caller closes', () => {
    const client = connectRoom('room1', 'Ada');
    latest().acceptConnection();
    client.close();
    assert.equal(FakeWebSocket.instances.length, 1);
  });
});
