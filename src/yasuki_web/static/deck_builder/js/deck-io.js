let _deckName = '';

export function getDeckName() {
  return _deckName;
}

export function setDeckName(name) {
  _deckName = name;
}

const SECTIONS = [
  ['pre_game', 'PRE_GAME'],
  ['dynasty', 'DYNASTY'],
  ['fate', 'FATE'],
];

export function serializeDeck(deck) {
  const needsQuote = (s) => /[:#\[\]{},&*?|<>=!%@`]/.test(s) || s.startsWith(' ') || s.endsWith(' ');
  const quoteValue = (s) => (needsQuote(s) ? `"${s.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"` : s);

  const lines = [`name: ${quoteValue(_deckName)}`, ''];

  for (const [sectionKey, bucketKey] of SECTIONS) {
    const bucket = deck[bucketKey] || {};
    const entries = Object.values(bucket);
    if (entries.length === 0) continue;

    lines.push(`${sectionKey}:`);
    entries
      .sort((a, b) =>
        (a.card.extended_title || a.card.name).localeCompare(b.card.extended_title || b.card.name),
      )
      .forEach((entry) => {
        const name = entry.card.extended_title || entry.card.name;
        Object.entries(entry.prints)
          .sort((a, b) => (a[1].set_name || '').localeCompare(b[1].set_name || ''))
          .forEach(([, printData]) => {
            const countPrefix = printData.qty > 1 ? `${printData.qty}x ` : '';
            const setSuffix = printData.set_name ? ` [${printData.set_name}]` : '';
            lines.push(`  - ${countPrefix}${name}${setSuffix}`);
          });
      });
    lines.push('');
  }

  return lines.join('\n').trimEnd() + '\n';
}

export function parseDeckYaml(text) {
  const result = { name: 'Imported Deck', pre_game: [], dynasty: [], fate: [] };
  let currentSection = null;

  for (const rawLine of text.split('\n')) {
    const line = rawLine.trimEnd();
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;

    const nameMatch = trimmed.match(/^name:\s*(.+)$/);
    if (nameMatch) {
      result.name = nameMatch[1].trim().replace(/^["']|["']$/g, '');
      continue;
    }

    const sectionMatch = trimmed.match(/^(pre_game|dynasty|fate):\s*$/);
    if (sectionMatch) {
      currentSection = sectionMatch[1];
      continue;
    }

    if (currentSection && /^\s*-\s/.test(line)) {
      const entry = _parseCardLine(trimmed.replace(/^-\s*/, ''));
      if (entry) result[currentSection].push(entry);
    }
  }

  return result;
}

function _parseCardLine(text) {
  let count = 1;
  let rest = text;

  const countMatch = rest.match(/^(\d+)[x×]\s+/i);
  if (countMatch) {
    count = parseInt(countMatch[1], 10);
    rest = rest.slice(countMatch[0].length);
  }

  let setName = null;
  const setMatch = rest.match(/^(.*?)\s+\[([^\]]+)\]\s*$/);
  if (setMatch) {
    rest = setMatch[1];
    setName = setMatch[2];
  }

  const name = rest.trim();
  if (!name) return null;
  return { name, count, setName };
}
