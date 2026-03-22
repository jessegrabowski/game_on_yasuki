import { describe, it, beforeEach, mock } from 'node:test';
import assert from 'node:assert/strict';

import { resetDOM } from './dom-shim.js';

const fetchMock = mock.fn();
globalThis.fetch = fetchMock;

import {
  initPreview,
  getCurrentPrintId,
  getCurrentSetName,
  showPreview,
} from '../../../src/yasuki_web/static/deck_builder/js/preview.js';

const PRINTS = [
  { print_id: 10, set_name: 'Imperial Edition', image_path: 'img/ie.jpg', flavor_text: 'Flavor IE' },
  { print_id: 20, set_name: 'Ivory Edition', image_path: 'img/ivory.jpg', flavor_text: '' },
  { print_id: 30, set_name: 'Twenty Festivals', image_path: 'img/tf.jpg', flavor_text: 'Flavor TF' },
];

const CARD = { id: 'card1', name: 'Hida Kisada', type: 'Personality', side: 'DYNASTY' };

function mockFetchPrints(prints) {
  fetchMock.mock.mockImplementation(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve({ card: CARD, prints }) }),
  );
}

beforeEach(() => {
  resetDOM();
  initPreview('/images');
  fetchMock.mock.resetCalls();
});

describe('preview state', () => {

  it('loads first print by default', async () => {
    mockFetchPrints(PRINTS);
    await showPreview(CARD, null, '/api');

    assert.equal(getCurrentPrintId(), 10);
    assert.equal(getCurrentSetName(), 'Imperial Edition');
  });

  it('selects preferred print when specified', async () => {
    mockFetchPrints(PRINTS);
    await showPreview(CARD, 30, '/api');

    assert.equal(getCurrentPrintId(), 30);
    assert.equal(getCurrentSetName(), 'Twenty Festivals');
  });

  it('falls back to first print for unknown preferred id', async () => {
    mockFetchPrints(PRINTS);
    await showPreview(CARD, 999, '/api');

    assert.equal(getCurrentPrintId(), 10);
  });

  it('handles card with no prints', async () => {
    mockFetchPrints([]);
    await showPreview(CARD, null, '/api');

    assert.equal(getCurrentPrintId(), null);
    assert.equal(getCurrentSetName(), '');
  });

  it('handles fetch failure gracefully', async () => {
    fetchMock.mock.mockImplementation(() => Promise.reject(new Error('network')));
    await showPreview(CARD, null, '/api');

    assert.equal(getCurrentPrintId(), null);
  });
});

describe('preview rendering', () => {
  it('renders print nav with correct count', async () => {
    mockFetchPrints(PRINTS);
    await showPreview(CARD, null, '/api');

    const el = document.getElementById('preview');
    assert.ok(el.innerHTML.includes('1/3'));
    assert.ok(el.innerHTML.includes('Imperial Edition'));
  });

  it('disables nav buttons for single print', async () => {
    mockFetchPrints([PRINTS[0]]);
    await showPreview(CARD, null, '/api');

    const el = document.getElementById('preview');
    assert.ok(el.innerHTML.includes('disabled'));
    assert.ok(el.innerHTML.includes('1/1'));
  });

  it('renders stats table', async () => {
    const card = { ...CARD, force: 5, chi: 3 };
    mockFetchPrints(PRINTS);
    await showPreview(card, null, '/api');

    const el = document.getElementById('preview');
    assert.ok(el.innerHTML.includes('Force'));
    assert.ok(el.innerHTML.includes('5'));
    assert.ok(el.innerHTML.includes('Chi'));
    assert.ok(el.innerHTML.includes('3'));
  });

  it('renders flavor text from current print', async () => {
    mockFetchPrints(PRINTS);
    await showPreview(CARD, null, '/api');

    const el = document.getElementById('preview');
    assert.ok(el.innerHTML.includes('Flavor IE'));
  });

  it('renders rules text', async () => {
    const card = { ...CARD, text: 'Battle: Bow this card.' };
    mockFetchPrints(PRINTS);
    await showPreview(card, null, '/api');

    const el = document.getElementById('preview');
    assert.ok(el.innerHTML.includes('Battle: Bow this card.'));
  });

  it('renders image src from current print', async () => {
    mockFetchPrints(PRINTS);
    await showPreview(CARD, null, '/api');

    const el = document.getElementById('preview');
    assert.ok(el.innerHTML.includes('/images/img/ie.jpg'));
  });

  it('renders fallback image when print has no image_path', async () => {
    mockFetchPrints([{ print_id: 10, set_name: 'Test', image_path: null, flavor_text: '' }]);
    await showPreview(CARD, null, '/api');

    const el = document.getElementById('preview');
    assert.ok(el.innerHTML.includes('defaults/generic_personality.jpg'));
  });

  it('renders fallback image when card has no prints and no image_path', async () => {
    mockFetchPrints([]);
    const card = { ...CARD, image_path: null };
    await showPreview(card, null, '/api');

    const el = document.getElementById('preview');
    assert.ok(el.innerHTML.includes('defaults/generic_personality.jpg'));
  });

  it('renders onerror fallback on img tag when print has image_path', async () => {
    mockFetchPrints(PRINTS);
    await showPreview(CARD, null, '/api');

    const el = document.getElementById('preview');
    assert.ok(el.innerHTML.includes('onerror'));
    assert.ok(el.innerHTML.includes('defaults/generic_personality.jpg'));
  });

  it('renders flip button', async () => {
    mockFetchPrints(PRINTS);
    await showPreview(CARD, null, '/api');

    const el = document.getElementById('preview');
    assert.ok(el.innerHTML.includes('flipBtn'));
    assert.ok(el.innerHTML.includes('🔄'));
  });

  it('renders flip button even without prints', async () => {
    mockFetchPrints([]);
    await showPreview(CARD, null, '/api');

    const el = document.getElementById('preview');
    assert.ok(el.innerHTML.includes('flipBtn'));
  });
});
