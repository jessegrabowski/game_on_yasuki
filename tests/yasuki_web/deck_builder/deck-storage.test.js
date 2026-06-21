import { describe, it, beforeEach, afterEach } from 'node:test';
import assert from 'node:assert/strict';
import {
  saveDeckSnapshot,
  loadDeckSnapshot,
  clearDeckSnapshot,
} from '../../../src/yasuki_web/static/deck_builder/js/deck-storage.js';

// Minimal localStorage stand-in. `failOn` lets a test force a method to throw, mimicking quota
// errors and privacy modes the real storage raises.
function fakeStorage(failOn = new Set()) {
  const map = new Map();
  return {
    getItem(k) {
      if (failOn.has('getItem')) throw new Error('blocked');
      return map.has(k) ? map.get(k) : null;
    },
    setItem(k, v) {
      if (failOn.has('setItem')) throw new Error('quota');
      map.set(k, String(v));
    },
    removeItem(k) {
      if (failOn.has('removeItem')) throw new Error('blocked');
      map.delete(k);
    },
  };
}

const original = globalThis.localStorage;
afterEach(() => {
  globalThis.localStorage = original;
});

describe('deck snapshot persistence', () => {
  beforeEach(() => {
    globalThis.localStorage = fakeStorage();
  });

  it('round-trips a saved snapshot', () => {
    const yaml = 'name: Crane Honor\nDynasty:\n  - 3x Doji Hoturi\n';
    saveDeckSnapshot(yaml);
    assert.equal(loadDeckSnapshot(), yaml);
  });

  it('returns null when nothing is saved', () => {
    assert.equal(loadDeckSnapshot(), null);
  });

  it('clear removes the snapshot so it does not resurrect', () => {
    saveDeckSnapshot('name: T\nFate:\n  - Ambush\n');
    clearDeckSnapshot();
    assert.equal(loadDeckSnapshot(), null);
  });
});

describe('deck snapshot persistence is best-effort', () => {
  it('does nothing and never throws when localStorage is absent', () => {
    globalThis.localStorage = undefined;
    assert.doesNotThrow(() => saveDeckSnapshot('x'));
    assert.equal(loadDeckSnapshot(), null);
    assert.doesNotThrow(() => clearDeckSnapshot());
  });

  it('swallows a quota error on save and persists nothing', () => {
    globalThis.localStorage = fakeStorage(new Set(['setItem']));
    assert.doesNotThrow(() => saveDeckSnapshot('x'));
    assert.equal(loadDeckSnapshot(), null);
  });

  it('returns null when reads are blocked', () => {
    globalThis.localStorage = fakeStorage(new Set(['getItem']));
    assert.equal(loadDeckSnapshot(), null);
  });

  it('swallows errors when clearing is blocked', () => {
    globalThis.localStorage = fakeStorage(new Set(['removeItem']));
    assert.doesNotThrow(() => clearDeckSnapshot());
  });
});
