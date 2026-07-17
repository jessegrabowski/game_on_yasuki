// WebSocket client for a play room: connects to /ws/{roomId} (wss when the page is https). A live
// connection that drops as a network blip reconnects once, after a short delay and only while the
// tab is visible. A handshake that never opened (server down or restarting) is surfaced as a
// disconnect rather than retried — repeated failed attempts are exactly what ratchets up a browser's
// escalating per-host WebSocket reconnect backoff, so we never feed it.

export const RECONNECT_DELAY_MS = 1500;

function roomSocketUrl(roomId) {
  const loc = globalThis.location;
  const proto = loc?.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${loc?.host ?? ''}/ws/${encodeURIComponent(roomId)}`;
}

function tabHidden() {
  return globalThis.document?.visibilityState === 'hidden';
}

export function connectRoom(roomId, playerName) {
  const events = new EventTarget();
  let socket = null;
  let closedByCaller = false;
  let openedThisAttempt = false;
  let reconnectsLeft = 1;
  let reconnectTimer = null;
  let awaitingVisible = false;

  function send(message) {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(message));
    }
  }

  function reconnect() {
    reconnectTimer = null;
    if (closedByCaller || reconnectsLeft <= 0) return;
    if (tabHidden()) {
      // A backgrounded play tab must not churn reconnect attempts against a (possibly restarting)
      // server; defer until the player brings it forward again.
      if (!awaitingVisible) {
        awaitingVisible = true;
        globalThis.document?.addEventListener?.('visibilitychange', onVisibilityChange);
      }
      return;
    }
    reconnectsLeft -= 1;
    open();
  }

  function onVisibilityChange() {
    if (tabHidden()) return;
    awaitingVisible = false;
    globalThis.document?.removeEventListener?.('visibilitychange', onVisibilityChange);
    reconnect();
  }

  function open() {
    openedThisAttempt = false;
    socket = new WebSocket(roomSocketUrl(roomId));

    socket.addEventListener('open', () => {
      openedThisAttempt = true;
      send({ type: 'JOIN', room: roomId, join: { name: playerName } });
    });

    socket.addEventListener('message', (e) => {
      let message;
      try {
        message = JSON.parse(e.data);
      } catch (_) {
        return;
      }
      if (message && typeof message.type === 'string') {
        events.dispatchEvent(new CustomEvent(message.type, { detail: message }));
      }
    });

    socket.addEventListener('close', (e) => {
      if (closedByCaller) return;
      // Reconnect only a socket that opened and then dropped as a network blip (1006), after a
      // delay. A never-opened handshake or a policy close (rate limit, gate, full) disconnects.
      if (e.code === 1006 && openedThisAttempt && reconnectsLeft > 0) {
        reconnectTimer = setTimeout(reconnect, RECONNECT_DELAY_MS);
      } else {
        events.dispatchEvent(new CustomEvent('disconnected'));
      }
    });
  }

  function close() {
    closedByCaller = true;
    if (reconnectTimer !== null) {
      clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (awaitingVisible) {
      awaitingVisible = false;
      globalThis.document?.removeEventListener?.('visibilitychange', onVisibilityChange);
    }
    socket?.close();
  }

  open();
  return { events, send, close };
}
