import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

import { predictSnapshot } from '../../../src/yasuki_web/static/site/optimistic.js';

// A snapshot with one battlefield card and one province card, both flags clear.
const base = () => ({
  seq: 5,
  your_seat: 'P1',
  battlefield: [{ id: 'b1', bowed: false, inverted: false, shown: false }],
  zones: { 'P1:province:0': [{ id: 'pv0', bowed: false, inverted: false }] },
});

const card = (snapshot, id) =>
  [snapshot.battlefield, ...Object.values(snapshot.zones)].flat().find((c) => c.id === id);

describe('predictSnapshot', () => {
  it('bows the targeted card and leaves the rest untouched', () => {
    const next = predictSnapshot(base(), { op: 'BOW', card_ids: ['b1'] });
    assert.equal(card(next, 'b1').bowed, true);
    assert.equal(card(next, 'pv0').bowed, false);
  });

  it('unbows the targeted card', () => {
    const snapshot = base();
    snapshot.battlefield[0].bowed = true;
    const next = predictSnapshot(snapshot, { op: 'UNBOW', card_ids: ['b1'] });
    assert.equal(card(next, 'b1').bowed, false);
  });

  it('toggles invert from its current value', () => {
    const up = predictSnapshot(base(), { op: 'INVERT', card_ids: ['b1'] });
    assert.equal(card(up, 'b1').inverted, true);
    const down = predictSnapshot(up, { op: 'INVERT', card_ids: ['b1'] });
    assert.equal(card(down, 'b1').inverted, false);
  });

  it('shows a single card addressed by card_id', () => {
    const next = predictSnapshot(base(), { op: 'SHOW', card_id: 'b1' });
    assert.equal(card(next, 'b1').shown, true);
  });

  it('stops showing a single card addressed by card_id', () => {
    const snapshot = base();
    snapshot.battlefield[0].shown = true;
    const next = predictSnapshot(snapshot, { op: 'UNSHOW', card_id: 'b1' });
    assert.equal(card(next, 'b1').shown, false);
  });

  it('applies a batch across the battlefield and a zone in one pass', () => {
    const next = predictSnapshot(base(), { op: 'BOW', card_ids: ['b1', 'pv0'] });
    assert.equal(card(next, 'b1').bowed, true);
    assert.equal(card(next, 'pv0').bowed, true);
  });

  it('returns null for an intent it does not predict', () => {
    assert.equal(predictSnapshot(base(), { op: 'MOVE_CARD', card_id: 'b1' }), null);
  });

  it('returns null when no targeted card matches, so the caller skips the render', () => {
    assert.equal(predictSnapshot(base(), { op: 'BOW', card_ids: ['ghost'] }), null);
  });

  it('never mutates the input snapshot', () => {
    const snapshot = base();
    const next = predictSnapshot(snapshot, { op: 'BOW', card_ids: ['b1'] });
    assert.notEqual(next, snapshot);
    assert.equal(snapshot.battlefield[0].bowed, false, 'original card flag unchanged');
  });
});
