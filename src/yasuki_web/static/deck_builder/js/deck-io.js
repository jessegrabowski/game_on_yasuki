import { deckHasCards } from './deck-state.js';

const SECTIONS = [
  ['pre_game', 'PRE_GAME'],
  ['dynasty', 'DYNASTY'],
  ['fate', 'FATE'],
];
const SECTION_LABEL = { pre_game: 'Pre-Game', dynasty: 'Dynasty', fate: 'Fate' };

// Title-case-preserving plural for the type subheaders (Holding -> Holdings, Strategy -> Strategies).
function pluralType(type) {
  return type.endsWith('y') ? type.slice(0, -1) + 'ies' : type + 's';
}

function entryQty(entry) {
  return Object.values(entry.prints).reduce((sum, p) => sum + p.qty, 0);
}

// Render the decklist as YAML: name/author/date metadata, then each deck section grouped by card
// type with `# Type (n)` subheaders and counts (comments — purely for reading; the parser skips
// them). Card lines keep the `<n>x Name [Set] {art: Donor [Set]}` grammar.
export function serializeDeck(deck, { name = '', author = '', date } = {}) {
  const dateStr = date ?? new Date().toISOString().slice(0, 10);
  const needsQuote = (s) => /[:#\[\]{},&*?|<>=!%@`]/.test(s) || s.startsWith(' ') || s.endsWith(' ');
  const quoteValue = (s) => (needsQuote(s) ? `"${s.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"` : s);

  const lines = [`name: ${quoteValue(name)}`];
  if (author) lines.push(`author: ${quoteValue(author)}`);
  lines.push(`date: ${dateStr}`, '');

  for (const [sectionKey, bucketKey] of SECTIONS) {
    const entries = Object.values(deck[bucketKey] || {});
    if (entries.length === 0) continue;

    const byType = {};
    for (const entry of entries) {
      const type = (entry.card.types || [])[0] || 'Other';
      (byType[type] ||= []).push(entry);
    }

    const total = entries.reduce((sum, e) => sum + entryQty(e), 0);
    lines.push(`${SECTION_LABEL[sectionKey]}: # (${total})`);

    Object.keys(byType)
      .sort()
      .forEach((type, i) => {
        if (i > 0) lines.push(''); // blank line between type blocks
        const group = byType[type].sort((a, b) =>
          (a.card.extended_title || a.card.name).localeCompare(b.card.extended_title || b.card.name),
        );
        lines.push(`  # ${pluralType(type)} (${group.reduce((sum, e) => sum + entryQty(e), 0)})`);
        for (const entry of group) {
          const name = entry.card.extended_title || entry.card.name;
          Object.entries(entry.prints)
            .sort((a, b) => (a[1].set_name || '').localeCompare(b[1].set_name || ''))
            .forEach(([, printData]) => {
              const countPrefix = printData.qty > 1 ? `${printData.qty}x ` : '';
              const setSuffix = printData.set_name ? ` [${printData.set_name}]` : '';
              const art = printData.art;
              const artSuffix = art
                ? ` {art: ${art.donorName}${art.donorSet ? ` [${art.donorSet}]` : ''}}`
                : '';
              lines.push(`  - ${countPrefix}${name}${setSuffix}${artSuffix}`);
            });
        }
      });
    lines.push('');
  }

  return lines.join('\n').trimEnd() + '\n';
}

// The localStorage snapshot for the live deck: its serialized YAML when it holds cards, or null to
// signal the snapshot should be cleared so an emptied deck never resurrects on reload.
export function deckSnapshot(deck, name, author) {
  return deckHasCards(deck) ? serializeDeck(deck, { name, author }) : null;
}

export function parseDeckYaml(text) {
  const result = { name: 'Imported Deck', author: '', date: '', pre_game: [], dynasty: [], fate: [] };
  let currentSection = null;
  const unquote = (s) => s.trim().replace(/^["']|["']$/g, '');

  for (const rawLine of text.split('\n')) {
    const line = rawLine.trimEnd();
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;

    const nameMatch = trimmed.match(/^name:\s*(.+)$/);
    if (nameMatch) {
      result.name = unquote(nameMatch[1]);
      continue;
    }
    const authorMatch = trimmed.match(/^author:\s*(.+)$/);
    if (authorMatch) {
      result.author = unquote(authorMatch[1]);
      continue;
    }
    const dateMatch = trimmed.match(/^date:\s*(.+)$/);
    if (dateMatch) {
      result.date = dateMatch[1].trim();
      continue;
    }

    // Accept the pretty keys (Dynasty:, Fate:, Pre-Game:) and the old lowercase ones.
    const sectionMatch = trimmed.match(/^(pre[-_ ]?game|dynasty|fate):\s*(#.*)?$/i);
    if (sectionMatch) {
      const norm = sectionMatch[1].toLowerCase().replace(/[-_ ]/g, '');
      currentSection = norm === 'pregame' ? 'pre_game' : norm;
      continue;
    }

    if (currentSection && /^\s*-\s/.test(line)) {
      const entry = _parseCardLine(trimmed.replace(/^-\s*/, ''));
      if (entry) result[currentSection].push(entry);
    }
  }

  return result;
}

function _splitNameSet(text) {
  const setMatch = text.match(/^(.*?)\s+\[([^\]]+)\]\s*$/);
  if (setMatch) return { name: setMatch[1].trim(), setName: setMatch[2] };
  return { name: text.trim(), setName: null };
}

function _parseCardLine(text) {
  let count = 1;
  let rest = text;

  const countMatch = rest.match(/^(\d+)[x×]\s+/i);
  if (countMatch) {
    count = parseInt(countMatch[1], 10);
    rest = rest.slice(countMatch[0].length);
  }

  let art = null;
  const artMatch = rest.match(/\s*\{art:\s*(.+?)\}\s*$/);
  if (artMatch) {
    const donor = _splitNameSet(artMatch[1].trim());
    art = { donorName: donor.name, donorSet: donor.setName };
    rest = rest.slice(0, artMatch.index);
  }

  const { name, setName } = _splitNameSet(rest);
  if (!name) return null;
  return { name, count, setName, art };
}
