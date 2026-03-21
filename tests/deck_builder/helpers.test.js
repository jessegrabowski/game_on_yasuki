import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { displayName, pluralize, titleCase, esc } from '../../app/assets/deck_builder/js/helpers.js';

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
    assert.equal(pluralize('Item'), 'Items');
    assert.equal(pluralize('Follower'), 'Followers');
    assert.equal(pluralize('Ring'), 'Rings');
  });

  it('changes y to ies', () => {
    assert.equal(pluralize('Strategy'), 'Strategies');
    assert.equal(pluralize('Personality'), 'Personalities');
  });

  it('adds es for sibilants', () => {
    assert.equal(pluralize('strongbox'), 'strongboxes');
  });

  it('preserves initial capitalization', () => {
    assert.equal(pluralize('event'), 'events');
    assert.equal(pluralize('Event'), 'Events');
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

  it('returns empty string for empty input', () => {
    assert.equal(esc(''), '');
  });
});
