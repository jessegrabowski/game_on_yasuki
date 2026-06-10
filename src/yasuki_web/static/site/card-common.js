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

export function fallbackSrc(card, imgBase) {
  const type = ((card.types || [])[0] || '').toLowerCase();
  const path = DEFAULT_BY_TYPE[type];
  return path ? `${imgBase}/${path}` : null;
}

// The image origin is config-driven (R2 CDN in production, the local /images mount otherwise).
export async function fetchImageBase() {
  try {
    const config = await (await fetch('/api/config')).json();
    return config.image_base_url || '/images';
  } catch (_) {
    return '/images';
  }
}
