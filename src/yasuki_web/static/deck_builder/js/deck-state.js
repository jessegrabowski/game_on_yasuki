const deck = { DYNASTY: {}, FATE: {}, PRE_GAME: {} };

export function getDeck() {
  return deck;
}

export function getBucket(side) {
  return deck[side] || deck.FATE;
}

export function addCard(cardId, side, card, printId, setName) {
  const bucket = deck[side] || deck.FATE;
  if (!bucket[cardId]) bucket[cardId] = { card, prints: {} };
  if (!bucket[cardId].prints[printId])
    bucket[cardId].prints[printId] = { qty: 0, set_name: setName };
  bucket[cardId].prints[printId].qty++;
}

export function removeCard(cardId, side, printId) {
  const bucket = deck[side];
  if (!bucket || !bucket[cardId]) return { cardRemoved: false, printRemoved: false };

  const entry = bucket[cardId];

  if (printId == null) {
    const firstKey = Object.keys(entry.prints)[0];
    if (!firstKey) return { cardRemoved: false, printRemoved: false };
    printId = parseInt(firstKey);
  }

  if (!entry.prints[printId]) return { cardRemoved: false, printRemoved: false };
  entry.prints[printId].qty--;

  let printRemoved = false;
  if (entry.prints[printId].qty <= 0) {
    delete entry.prints[printId];
    printRemoved = true;
  }

  let cardRemoved = false;
  if (Object.keys(entry.prints).length === 0) {
    delete bucket[cardId];
    cardRemoved = true;
  }

  return { cardRemoved, printRemoved, resolvedPrintId: printId };
}

export function clearDeck() {
  Object.keys(deck).forEach((k) => (deck[k] = {}));
}

export function deckEntryTotal(entry) {
  return Object.values(entry.prints).reduce((s, p) => s + p.qty, 0);
}

export function nextCardAfterRemoval(side, removedId) {
  const bucket = deck[side] || {};
  const entries = Object.entries(bucket).sort((a, b) =>
    a[1].card.name.localeCompare(b[1].card.name),
  );
  if (entries.length === 0) return null;
  const oldIdx = entries.findIndex((pair) => pair[0] > removedId);
  const nextIdx = oldIdx >= 0 ? Math.min(oldIdx, entries.length - 1) : entries.length - 1;
  const next = entries[nextIdx];
  return { id: next[0], card: next[1].card };
}

export function getDeckNavItems(side) {
  const bucket = deck[side] || {};
  const items = [];
  const cardsByType = {};

  for (const id in bucket) {
    const entry = bucket[id];
    const type = entry.card.type || 'Unknown';
    if (!cardsByType[type]) cardsByType[type] = [];
    cardsByType[type].push({ id, entry });
  }

  Object.keys(cardsByType)
    .sort()
    .forEach((type) => {
      const cards = cardsByType[type].sort((a, b) =>
        a.entry.card.name.localeCompare(b.entry.card.name),
      );
      cards.forEach((c) => {
        const printEntries = Object.entries(c.entry.prints);
        if (printEntries.length === 1) {
          items.push({
            side,
            id: c.id,
            printId: parseInt(printEntries[0][0]),
            card: c.entry.card,
          });
        } else {
          items.push({ side, id: c.id, printId: null, card: c.entry.card });
          printEntries
            .sort((a, b) => parseInt(a[0]) - parseInt(b[0]))
            .forEach((pair) => {
              items.push({ side, id: c.id, printId: parseInt(pair[0]), card: c.entry.card });
            });
        }
      });
    });

  return items;
}
