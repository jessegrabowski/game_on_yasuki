// Locally predict the outcome of the toggles whose result is fully determined by the current
// snapshot, so the board can update before the server's confirming snapshot arrives. Each toggle
// mirrors its server-side flag mutator (yasuki_core table.py): BOW/UNBOW set bowed, INVERT toggles
// it, SHOW/UNSHOW set shown.
const TOGGLES = {
  BOW: (card) => ({ ...card, bowed: true }),
  UNBOW: (card) => ({ ...card, bowed: false }),
  INVERT: (card) => ({ ...card, inverted: !card.inverted }),
  SHOW: (card) => ({ ...card, shown: true }),
  UNSHOW: (card) => ({ ...card, shown: false }),
};

// Return a new snapshot with `intent` applied to its target cards, or null for an intent we do not
// predict (or one that changes nothing). The input snapshot is never mutated.
export function predictSnapshot(snapshot, intent) {
  const toggle = TOGGLES[intent?.op];
  if (!toggle || !snapshot) return null;
  const targets = new Set(intent.card_ids ?? (intent.card_id != null ? [intent.card_id] : []));
  if (targets.size === 0) return null;

  let changed = false;
  const toggleMatches = (cards) =>
    cards.map((card) => {
      if (!targets.has(card.id)) return card;
      changed = true;
      return toggle(card);
    });

  const battlefield = snapshot.battlefield
    ? toggleMatches(snapshot.battlefield)
    : snapshot.battlefield;
  let zones = snapshot.zones;
  if (zones) {
    zones = Object.fromEntries(
      Object.entries(zones).map(([key, cards]) => [key, toggleMatches(cards)]),
    );
  }
  if (!changed) return null;
  return { ...snapshot, battlefield, zones };
}
