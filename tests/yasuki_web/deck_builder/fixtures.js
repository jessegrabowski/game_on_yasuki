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
    keywords: [],
    image_path: 'sets/imperial_edition/doji_hoturi.jpg',
    is_unique: false,
    ...overrides,
  };
}

// Canonical print shape, mirroring /api/cards/{id}.prints[*]. era/layout_type are appended
// server-side for the art-swap canvas; keep in lockstep with the API contract test.
export function makePrint(overrides = {}) {
  return {
    print_id: 123,
    card_id: 'doji_hoturi',
    set_name: 'Imperial Edition',
    rarity: 'Rare',
    artist: 'Kaija Rudek',
    image_path: 'sets/imperial_edition/doji_hoturi.jpg',
    back_image_path: null,
    flavor_text: null,
    era: '1995-99',
    layout_type: 'Personality',
    ...overrides,
  };
}
