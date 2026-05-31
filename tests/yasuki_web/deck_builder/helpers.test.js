import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import {
  displayName,
  pluralize,
  titleCase,
  esc,
  deckSide,
  primaryDeck,
} from '../../../src/yasuki_web/static/deck_builder/js/helpers.js';

describe('displayName', () => {
  it('returns name for non-unique card', () => {
    assert.equal(displayName({ name: 'Hida Kisada' }), 'Hida Kisada');
  });

  it('prefixes diamond for unique card', () => {
    assert.equal(displayName({ name: 'Hida Kisada', is_unique: true }), '◆ Hida Kisada');
  });

  it('prefers extended_title when present', () => {
    const card = { name: 'Hida Kisada', extended_title: 'Hida Kisada \u2022 Experienced' };
    assert.equal(displayName(card), 'Hida Kisada \u2022 Experienced');
  });

  it('prefixes diamond on extended_title for unique', () => {
    const card = { name: 'Hida Kisada', extended_title: 'Hida Kisada \u2022 Exp', is_unique: true };
    assert.equal(displayName(card), '\u25C6 Hida Kisada \u2022 Exp');
  });
});

describe('pluralize', () => {
  it('adds s to regular words', () => {
    assert.equal(pluralize('Holding'), 'Holdings');
  });

  it('changes y to ies', () => {
    assert.equal(pluralize('Strategy'), 'Strategies');
  });

  it('adds es for sibilants', () => {
    assert.equal(pluralize('strongbox'), 'strongboxes');
  });

  it('preserves initial capitalization', () => {
    assert.equal(pluralize('event'), 'events');
  });
});

describe('titleCase', () => {
  it('title-cases simple words', () => {
    assert.equal(titleCase('DYNASTY'), 'Dynasty');
    assert.equal(titleCase('FATE'), 'Fate');
  });

  it('replaces underscores with spaces', () => {
    assert.equal(titleCase('PRE_GAME'), 'Pre Game');
  });
});

describe('esc', () => {
  it('escapes HTML entities', () => {
    assert.equal(esc('<b>hi</b>'), '&lt;b&gt;hi&lt;/b&gt;');
    assert.equal(esc('a & b'), 'a &amp; b');
  });
});

describe('deckSide', () => {
  it('maps a Fate card to the FATE bucket', () => {
    assert.equal(deckSide({ decks: ['Fate'] }), 'FATE');
  });

  it('maps a Dynasty card to the DYNASTY bucket', () => {
    assert.equal(deckSide({ decks: ['Dynasty'] }), 'DYNASTY');
  });

  it('maps anything else (Pre-Game, Other, missing) to PRE_GAME', () => {
    assert.equal(deckSide({ decks: ['Pre-Game'] }), 'PRE_GAME');
    assert.equal(deckSide({ decks: ['Other'] }), 'PRE_GAME');
    assert.equal(deckSide({}), 'PRE_GAME');
  });

  it('prefers Fate when a card is in both decks', () => {
    assert.equal(deckSide({ decks: ['Dynasty', 'Fate'] }), 'FATE');
  });
});

describe('primaryDeck', () => {
  it('returns the first deck', () => {
    assert.equal(primaryDeck({ decks: ['Dynasty'] }), 'Dynasty');
  });

  it('returns empty string when there are no decks', () => {
    assert.equal(primaryDeck({}), '');
  });
});
