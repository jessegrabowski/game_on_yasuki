// Canonical card shape, mirroring the live API. The server-side contract test
// (tests/yasuki_web/test_api_contract.py) verifies the API actually returns these keys; keep the
// two in lockstep so a shape change breaks tests here instead of only surfacing after a deploy.
export function makeCard(overrides = {}) {
  return {
    card_id: 'doji_hoturi',
    name: 'Doji Hoturi',
    extended_title: 'Doji Hoturi',
    decks: ['Dynasty'],
    types: ['Personality'],
    clans: ['Crane'],
    image_path: 'sets/imperial_edition/doji_hoturi.jpg',
    is_unique: false,
    ...overrides,
  };
}
