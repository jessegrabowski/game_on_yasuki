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

const { connectRoom, RECONNECT_DELAY_MS } = await import(
  '../../../src/yasuki_web/static/site/ws-client.js'
);

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

  it('reconnects once after a live connection drops, then gives up', (t) => {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    const client = connectRoom('room1', 'Ada');
    let disconnected = false;
    client.events.addEventListener('disconnected', () => {
      disconnected = true;
    });

    latest().acceptConnection();
    latest().drop();
    // The reconnect is deferred by a short backoff so a restarting server isn't hammered.
    assert.equal(FakeWebSocket.instances.length, 1, 'reconnect is deferred, not immediate');
    t.mock.timers.tick(RECONNECT_DELAY_MS);
    assert.equal(FakeWebSocket.instances.length, 2, 'a single reconnect fires after the delay');
    assert.equal(disconnected, false);

    // The reconnect attempt itself never opened, so its drop gives up rather than retrying again.
    latest().drop();
    assert.equal(FakeWebSocket.instances.length, 2, 'no second reconnect');
    assert.equal(disconnected, true);
  });

  it('does not reconnect when the initial handshake never opened', (t) => {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    const client = connectRoom('room1', 'Ada');
    let disconnected = false;
    client.events.addEventListener('disconnected', () => {
      disconnected = true;
    });

    // A 1006 before the socket ever opens is a server that is down or restarting; retrying it just
    // piles up failed attempts and feeds the browser's per-host reconnect backoff.
    latest().drop();
    t.mock.timers.tick(RECONNECT_DELAY_MS);
    assert.equal(FakeWebSocket.instances.length, 1, 'no retry storm against a dead server');
    assert.equal(disconnected, true);
  });

  it('defers reconnecting a hidden tab until it becomes visible again', (t) => {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    const listeners = {};
    globalThis.document = {
      visibilityState: 'hidden',
      addEventListener: (type, fn) => {
        (listeners[type] ||= []).push(fn);
      },
      removeEventListener: (type, fn) => {
        listeners[type] = (listeners[type] || []).filter((f) => f !== fn);
      },
    };
    try {
      connectRoom('room1', 'Ada');
      latest().acceptConnection();
      latest().drop();
      t.mock.timers.tick(RECONNECT_DELAY_MS);
      assert.equal(FakeWebSocket.instances.length, 1, 'no reconnect while the tab is hidden');

      globalThis.document.visibilityState = 'visible';
      (listeners.visibilitychange || []).forEach((fn) => fn());
      assert.equal(FakeWebSocket.instances.length, 2, 'reconnects once the tab is foregrounded');
    } finally {
      delete globalThis.document;
    }
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
