// Canonical room shape, mirroring public_room from src/yasuki_web/rooms.py. The server-side test
// test_room_payload_exposes_expected_keys (tests/yasuki_web/test_rooms.py) asserts the API returns
// these keys; keep the two in lockstep so a shape change breaks a test rather than only surfacing
// after a deploy.
export function makeRoom(overrides = {}) {
  return {
    id: 'aB3xY7zq',
    name: 'Crab Table',
    max_players: 2,
    players: [],
    state: 'waiting',
    created_at: '2026-06-23T00:00:00+00:00',
    ...overrides,
  };
}
