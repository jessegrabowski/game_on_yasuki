import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';
import { getDeckName, setDeckName, setDeckAuthor, serializeDeck, parseDeckYaml } from '../../../src/yasuki_web/static/deck_builder/js/deck-io.js';
import { addCard, clearDeck, getDeck } from '../../../src/yasuki_web/static/deck_builder/js/deck-state.js';
import { makeCard } from './fixtures.js';
const CARD_PERS = makeCard({ card_id: 'doji_hoturi', name: 'Doji Hoturi', types: ['Personality'], decks: ['Dynasty'] });
const CARD_HOLD = makeCard({ card_id: 'kobune_port', name: 'Kobune Port', types: ['Holding'], decks: ['Dynasty'] });
const CARD_STR  = makeCard({ card_id: 'ambush', name: 'Ambush', extended_title: 'Ambush', types: ['Strategy'], decks: ['Fate'] });
const CARD_SH   = makeCard({ card_id: 'kyuden_doji', name: 'Kyuden Doji', extended_title: 'Kyuden Doji', types: ['Stronghold'], decks: ['Pre-Game'] });
beforeEach(() => { clearDeck(); setDeckName(''); setDeckAuthor(''); });
describe('parseDeckYaml', () => {
  it('parses deck name', () => {
    assert.equal(parseDeckYaml('name: My Crane Deck').name, 'My Crane Deck');
  });
  it('strips quotes from deck name', () => {
    assert.equal(parseDeckYaml('name: "Deck: The Reckoning"').name, 'Deck: The Reckoning');
  });
  it('strips single quotes from deck name', () => {
    assert.equal(parseDeckYaml("name: 'Deck: The Reckoning'").name, 'Deck: The Reckoning');
  });
  it('defaults name when missing', () => {
    assert.equal(parseDeckYaml('fate:\n  - Ambush').name, 'Imported Deck');
  });
  it('parses a simple card entry', () => {
    const r = parseDeckYaml('name: T\nfate:\n  - Ambush');
    assert.deepEqual(r.fate[0], { name: 'Ambush', count: 1, setName: null, art: null });
  });
  it('parses count prefix', () => {
    const r = parseDeckYaml('name: T\ndynasty:\n  - 3x Doji Hoturi');
    assert.equal(r.dynasty[0].count, 3);
    assert.equal(r.dynasty[0].name, 'Doji Hoturi');
  });
  it('parses unicode multiplication sign as count prefix', () => {
    const r = parseDeckYaml('name: T\nfate:\n  - 2× Ambush');
    assert.equal(r.fate[0].count, 2);
    assert.equal(r.fate[0].name, 'Ambush');
  });
  it('parses set suffix', () => {
    const r = parseDeckYaml('name: T\nfate:\n  - 2x Ambush [Imperial Edition]');
    assert.equal(r.fate[0].count, 2);
    assert.equal(r.fate[0].setName, 'Imperial Edition');
  });
  it('parses all three sections', () => {
    const r = parseDeckYaml('name: T\npre_game:\n  - Kyuden Doji\ndynasty:\n  - Doji Hoturi\nfate:\n  - Ambush');
    assert.equal(r.pre_game.length, 1);
    assert.equal(r.dynasty.length, 1);
    assert.equal(r.fate.length, 1);
  });
  it('ignores comment lines', () => {
    const r = parseDeckYaml('name: T\n# comment\nfate:\n  - Ambush');
    assert.equal(r.fate.length, 1);
  });
  it('ignores blank lines', () => {
    const r = parseDeckYaml('name: T\n\n\nfate:\n  - Ambush\n\n');
    assert.equal(r.fate.length, 1);
  });
  it('handles multiple prints as separate entries', () => {
    const r = parseDeckYaml('name: T\nfate:\n  - 1x Ambush [Imperial Edition]\n  - 2x Ambush [Lotus Edition]');
    assert.equal(r.fate.length, 2);
    assert.equal(r.fate[0].setName, 'Imperial Edition');
    assert.equal(r.fate[1].count, 2);
    assert.equal(r.fate[1].setName, 'Lotus Edition');
  });
  it('does not confuse numeric card name with count prefix', () => {
    const r = parseDeckYaml('name: T\ndynasty:\n  - 700 Soldier Plain');
    assert.equal(r.dynasty[0].name, '700 Soldier Plain');
    assert.equal(r.dynasty[0].count, 1);
  });
  it('parses card name with bullet character', () => {
    const r = parseDeckYaml('name: T\ndynasty:\n  - Kuni Yori \u2022 Experienced [Pearl Edition]');
    assert.equal(r.dynasty[0].name, 'Kuni Yori \u2022 Experienced');
    assert.equal(r.dynasty[0].setName, 'Pearl Edition');
  });
  it('returns empty sections for empty input', () => {
    const r = parseDeckYaml('');
    assert.deepEqual(r.pre_game, []);
    assert.deepEqual(r.dynasty, []);
    assert.deepEqual(r.fate, []);
  });
  it('ignores lines outside a section', () => {
    const r = parseDeckYaml('name: T\n  - Stray Entry');
    assert.deepEqual(r.fate, []);
    assert.deepEqual(r.dynasty, []);
  });
});
describe('serializeDeck', () => {
  it('includes deck name', () => {
    setDeckName('Test Deck');
    assert.ok(serializeDeck(getDeck()).includes('name: Test Deck'));
  });
  it('quotes deck name containing a colon', () => {
    setDeckName('Deck: The Return');
    assert.ok(serializeDeck(getDeck()).includes('"Deck: The Return"'));
  });
  it('round-trips through serialize then parse', () => {
    setDeckName('Crane Classic');
    addCard('doji_hoturi', 'DYNASTY', CARD_PERS, 10, 'Imperial Edition');
    addCard('doji_hoturi', 'DYNASTY', CARD_PERS, 10, 'Imperial Edition');
    addCard('ambush',      'FATE',    CARD_STR,  20, 'Lotus Edition');
    addCard('kyuden_doji', 'PRE_GAME', CARD_SH,  30, 'Gold Edition');
    const parsed = parseDeckYaml(serializeDeck(getDeck()));
    assert.equal(parsed.name, 'Crane Classic');
    assert.equal(parsed.dynasty[0].count, 2);
    assert.equal(parsed.dynasty[0].setName, 'Imperial Edition');
    assert.equal(parsed.fate[0].name, 'Ambush');
    assert.equal(parsed.pre_game[0].name, 'Kyuden Doji');
  });
  it('round-trips multi-print card with different sets', () => {
    setDeckName('Multi-Print');
    addCard('ambush', 'FATE', CARD_STR, 10, 'Imperial Edition');
    addCard('ambush', 'FATE', CARD_STR, 20, 'Lotus Edition');
    addCard('ambush', 'FATE', CARD_STR, 20, 'Lotus Edition');
    const parsed = parseDeckYaml(serializeDeck(getDeck()));
    assert.equal(parsed.fate.length, 2);
    const imperial = parsed.fate.find((e) => e.setName === 'Imperial Edition');
    const lotus = parsed.fate.find((e) => e.setName === 'Lotus Edition');
    assert.equal(imperial.count, 1);
    assert.equal(lotus.count, 2);
  });
  it('omits empty sections', () => {
    addCard('ambush', 'FATE', CARD_STR, 10, 'Imperial Edition');
    const yaml = serializeDeck(getDeck());
    assert.ok(!yaml.includes('Dynasty:'));
    assert.ok(!yaml.includes('Pre-Game:'));
    assert.ok(yaml.includes('Fate:'));
  });
  it('omits count prefix when count is 1', () => {
    addCard('ambush', 'FATE', CARD_STR, 10, 'Imperial Edition');
    const yaml = serializeDeck(getDeck());
    assert.ok(!yaml.includes('1x'));
    assert.ok(yaml.includes('  - Ambush'));
  });
  it('round-trips card name starting with digits', () => {
    const CARD_NUM = makeCard({ card_id: '700_soldier_plain', name: '700 Soldier Plain', extended_title: '700 Soldier Plain', types: ['Holding'], decks: ['Dynasty'] });
    addCard('700_soldier_plain', 'DYNASTY', CARD_NUM, 50, 'Diamond Edition');
    const parsed = parseDeckYaml(serializeDeck(getDeck()));
    assert.equal(parsed.dynasty[0].name, '700 Soldier Plain');
    assert.equal(parsed.dynasty[0].count, 1);
    assert.equal(parsed.dynasty[0].setName, 'Diamond Edition');
  });
  it('serializes empty deck as name + date', () => {
    setDeckName('Empty');
    assert.equal(serializeDeck(getDeck(), '2026-06-01'), 'name: Empty\ndate: 2026-06-01\n');
  });
  it('writes author when set, and round-trips it', () => {
    setDeckName('Authored');
    setDeckAuthor('Ada');
    addCard('ambush', 'FATE', CARD_STR, 10, 'Imperial Edition');
    const yaml = serializeDeck(getDeck(), '2026-06-01');
    assert.ok(yaml.includes('author: Ada'));
    assert.ok(yaml.includes('date: 2026-06-01'));
    assert.equal(parseDeckYaml(yaml).author, 'Ada');
  });
  it('omits the author line when unset', () => {
    setDeckName('Anon');
    addCard('ambush', 'FATE', CARD_STR, 10, 'Imperial Edition');
    assert.ok(!serializeDeck(getDeck()).includes('author:'));
  });
  it('groups a section by card type with counted subheaders', () => {
    setDeckName('Grouped');
    addCard('doji_hoturi', 'DYNASTY', CARD_PERS, 10, 'Imperial Edition');
    addCard('doji_hoturi', 'DYNASTY', CARD_PERS, 10, 'Imperial Edition');
    addCard('kobune_port', 'DYNASTY', CARD_HOLD, 11, 'Imperial Edition');
    const yaml = serializeDeck(getDeck(), '2026-06-01');
    assert.ok(yaml.includes('Dynasty: # (3)'));
    assert.ok(yaml.includes('  # Holdings (1)'));
    assert.ok(yaml.includes('  # Personalities (2)'));
    // Subheaders are comments; the parser still recovers the cards.
    assert.equal(parseDeckYaml(yaml).dynasty.length, 2);
  });
  it('ends with a single newline', () => {
    addCard('ambush', 'FATE', CARD_STR, 10, 'Imperial Edition');
    const yaml = serializeDeck(getDeck());
    assert.ok(yaml.endsWith('\n'));
    assert.ok(!yaml.endsWith('\n\n'));
  });
});
describe('confusing deck round-trip', () => {
  const CONFUSING_YAML = [
    'name: confusing deck',
    '',
    'dynasty:',
    '  - Kuni Yori [Battle of Beiden Pass]',
    '  - Kuni Yori [Emerald Edition]',
    '  - Kuni Yori [Imperial Edition]',
    '  - Kuni Yori [Obsidian Edition]',
    '  - Kuni Yori [Pearl Edition]',
    '  - Kuni Yori \u2022 Experienced [Celestial Edition 15th Anniversary]',
    '  - Kuni Yori \u2022 Experienced [Forbidden Knowledge]',
    '  - Kuni Yori \u2022 Experienced [Jade Edition]',
    '  - Kuni Yori \u2022 Experienced [Pearl Edition]',
    '  - Kuni Yori \u2022 Experienced 2 [Hidden Emperor 3]',
    '  - Kuni Yori \u2022 Experienced 2KYD [1,000 Years of Darkness]',
    '  - Kuni Yori \u2022 Experienced 3 [Honor Bound]',
    '  - Kuni Yori, the Corruptor \u2022 Inexperienced [Siege: Clan War]',
    '  - Writings of Kuni Yori [Jade Edition]',
    '',
    'fate:',
    '  - Ambush [Celestial Edition]',
    '  - Ambush [Diamond Edition]',
    '  - Ambush [Emerald Edition]',
    '  - Ambush [Emperor Edition]',
    '  - Ambush [Gold Edition]',
    '  - Ambush [Imperial Edition]',
    '  - Ambush [Ivory Edition]',
    '  - Ambush [Jade Edition]',
    '  - Ambush [Lotus Edition]',
    '  - Ambush [Obsidian Edition]',
    '  - Ambush [Onyx Edition]',
    '  - Ambush [Pearl Edition]',
    '  - Ambush [Promotional\u2013Emperor]',
    '  - Ambush [Samurai Edition]',
    '  - Ambush [Shattered Empire]',
    '  - Ambush [Training Grounds 2]',
  ].join('\n') + '\n';

  it('parses all entries with correct counts', () => {
    const r = parseDeckYaml(CONFUSING_YAML);
    assert.equal(r.name, 'confusing deck');
    assert.equal(r.dynasty.length, 14);
    assert.equal(r.fate.length, 16);
    r.dynasty.forEach((e) => assert.equal(e.count, 1));
    r.fate.forEach((e) => assert.equal(e.count, 1));
  });
  it('distinguishes Kuni Yori variants by extended title', () => {
    const r = parseDeckYaml(CONFUSING_YAML);
    const names = r.dynasty.map((e) => e.name);
    assert.ok(names.includes('Kuni Yori'));
    assert.ok(names.includes('Kuni Yori \u2022 Experienced'));
    assert.ok(names.includes('Kuni Yori \u2022 Experienced 2'));
    assert.ok(names.includes('Kuni Yori \u2022 Experienced 2KYD'));
    assert.ok(names.includes('Kuni Yori \u2022 Experienced 3'));
    assert.ok(names.includes('Kuni Yori, the Corruptor \u2022 Inexperienced'));
    assert.ok(names.includes('Writings of Kuni Yori'));
  });
  it('preserves set names with special characters', () => {
    const r = parseDeckYaml(CONFUSING_YAML);
    const sets = new Set(r.dynasty.map((e) => e.setName));
    assert.ok(sets.has('1,000 Years of Darkness'));
    assert.ok(sets.has('Siege: Clan War'));
    assert.ok(sets.has('Celestial Edition 15th Anniversary'));
    const fateSets = new Set(r.fate.map((e) => e.setName));
    assert.ok(fateSets.has('Promotional\u2013Emperor'));
    assert.ok(fateSets.has('Training Grounds 2'));
  });
  it('survives serialize then re-parse', () => {
    const first = parseDeckYaml(CONFUSING_YAML);
    const allCards = {};
    const addParsedEntries = (entries, side) => {
      entries.forEach((e, i) => {
        const cardId = e.name.toLowerCase().replace(/[^a-z0-9]/g, '_') + '_' + i;
        const card = makeCard({ card_id: cardId, name: e.name, extended_title: e.name });
        const printId = i + 1;
        for (let c = 0; c < e.count; c++) addCard(cardId, side, card, printId, e.setName);
        allCards[cardId] = card;
      });
    };
    setDeckName(first.name);
    addParsedEntries(first.dynasty, 'DYNASTY');
    addParsedEntries(first.fate, 'FATE');
    const reYaml = serializeDeck(getDeck());
    const second = parseDeckYaml(reYaml);
    assert.equal(second.name, first.name);
    assert.equal(second.dynasty.length, first.dynasty.length);
    assert.equal(second.fate.length, first.fate.length);
    const firstDynNames = first.dynasty.map((e) => e.name).sort();
    const secondDynNames = second.dynasty.map((e) => e.name).sort();
    assert.deepEqual(secondDynNames, firstDynNames);
    const firstDynSets = first.dynasty.map((e) => e.setName).sort();
    const secondDynSets = second.dynasty.map((e) => e.setName).sort();
    assert.deepEqual(secondDynSets, firstDynSets);
  });
});
describe('custom-print art trailer', () => {
  it('parses a {art: Donor [Set]} trailer alongside the recipient set', () => {
    const r = parseDeckYaml('name: T\nfate:\n  - Ambush [Imperial Edition] {art: Doji Hoturi [Lotus Edition]}');
    assert.deepEqual(r.fate[0], {
      name: 'Ambush',
      count: 1,
      setName: 'Imperial Edition',
      art: { donorName: 'Doji Hoturi', donorSet: 'Lotus Edition' },
    });
  });
  it('leaves art null for a plain entry', () => {
    assert.equal(parseDeckYaml('name: T\nfate:\n  - Ambush [Imperial Edition]').fate[0].art, null);
  });
  it('serializes a custom print with the art trailer', () => {
    setDeckName('Borrowed');
    const deck = {
      PRE_GAME: {},
      DYNASTY: {},
      FATE: {
        ambush: {
          card: CARD_STR,
          prints: {
            'art:1:2': {
              qty: 1,
              set_name: 'Imperial Edition',
              art: { donorName: 'Doji Hoturi', donorSet: 'Lotus Edition' },
            },
          },
        },
      },
    };
    assert.match(serializeDeck(deck), /Ambush \[Imperial Edition\] \{art: Doji Hoturi \[Lotus Edition\]\}/);
  });
  it('round-trips a custom print back to the same art recipe', () => {
    setDeckName('Borrowed');
    const deck = {
      PRE_GAME: {},
      DYNASTY: {},
      FATE: {
        ambush: {
          card: CARD_STR,
          prints: {
            'art:1:2': {
              qty: 2,
              set_name: 'Imperial Edition',
              art: { donorName: 'Doji Hoturi', donorSet: 'Lotus Edition' },
            },
          },
        },
      },
    };
    const entry = parseDeckYaml(serializeDeck(deck)).fate[0];
    assert.equal(entry.count, 2);
    assert.equal(entry.setName, 'Imperial Edition');
    assert.deepEqual(entry.art, { donorName: 'Doji Hoturi', donorSet: 'Lotus Edition' });
  });
});
describe('getDeckName / setDeckName', () => {
  it('defaults to empty string', () => {
    assert.equal(getDeckName(), '');
  });
  it('stores and retrieves name', () => {
    setDeckName('Test');
    assert.equal(getDeckName(), 'Test');
  });
});
