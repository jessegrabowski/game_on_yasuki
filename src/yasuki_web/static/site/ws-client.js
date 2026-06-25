// WebSocket client for a play room: connects to /ws/{roomId} (wss when the page is https) and
// retries the connection once if it drops unexpectedly.

function roomSocketUrl(roomId) {
  const loc = globalThis.location;
  const proto = loc?.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${loc?.host ?? ''}/ws/${encodeURIComponent(roomId)}`;
}

export function connectRoom(roomId, playerName) {
  const events = new EventTarget();
  let socket = null;
  let reconnectsLeft = 1;
  let closedByCaller = false;

  function send(message) {
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(message));
    }
  }

  function open() {
    socket = new WebSocket(roomSocketUrl(roomId));

    socket.addEventListener('open', () => {
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
      // Retry only a genuine network drop (1006). Server policy closes — rate limit, gate, room
      // full — would just fail again, so surface them as a disconnect instead of reconnecting.
      if (e.code === 1006 && reconnectsLeft > 0) {
        reconnectsLeft -= 1;
        open();
      } else {
        events.dispatchEvent(new CustomEvent('disconnected'));
      }
    });
  }

  function close() {
    closedByCaller = true;
    socket?.close();
  }

  open();
  return { events, send, close };
}
