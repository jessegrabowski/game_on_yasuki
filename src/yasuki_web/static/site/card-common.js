// Type-keyed default art, mirroring the deck builder's preview fallbacks, for cards whose print has
// no scanned image yet.
export const DEFAULT_BY_TYPE = {
  celestial: 'defaults/generic_celestial.jpg',
  event: 'defaults/generic_event.jpg',
  follower: 'defaults/generic_follower.jpg',
  holding: 'defaults/generic_holding.jpg',
  item: 'defaults/generic_item.jpg',
  personality: 'defaults/generic_personality.jpg',
  region: 'defaults/generic_region.jpg',
  ring: 'defaults/generic_ring.jpg',
  sensei: 'defaults/generic_sensei.jpg',
  spell: 'defaults/generic_spell.jpg',
  strategy: 'defaults/generic_strategy.jpg',
  stronghold: 'defaults/generic_stronghold.jpg',
  wind: 'defaults/generic_wind.jpg',
};

export const esc = (s) =>
  String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');

export const displayName = (card) => {
  const title = card.extended_title || card.name || '';
  return card.is_unique ? '◆ ' + title : title;
};

// Personalities placeholder to their clan frame; unaligned (or a non-great-clan alignment) falls
// back to DEFAULT_BY_TYPE.personality. Mirrors default_personality_image in yasuki_core/paths.py.
const GREAT_CLANS = new Set([
  'crab', 'crane', 'dragon', 'lion', 'mantis', 'naga', 'phoenix', 'scorpion', 'spider', 'unicorn',
]);

function personalityFallback(card) {
  for (const clan of card.clans || []) {
    const slug = clan.toLowerCase().replace(' clan', '').trim();
    if (GREAT_CLANS.has(slug)) return `defaults/generic_personality_${slug}.jpg`;
  }
  return DEFAULT_BY_TYPE.personality;
}

export function fallbackSrc(card, imgBase) {
  const type = ((card.types || [])[0] || '').toLowerCase();
  const path = type === 'personality' ? personalityFallback(card) : DEFAULT_BY_TYPE[type];
  return path ? `${imgBase}/${path}` : null;
}

// Server runtime config: the image origin (R2 CDN in production, the local /images mount otherwise)
// and the debug flag that gates debug-level server errors in the game log.
export async function fetchConfig() {
  try {
    const config = await (await fetch('/api/config')).json();
    return {
      imageBase: config.image_base_url || '/images',
      debug: !!config.debug,
      devLogin: !!config.dev_login,
    };
  } catch (_) {
    return { imageBase: '/images', debug: false, devLogin: false };
  }
}

export async function fetchImageBase() {
  return (await fetchConfig()).imageBase;
}
