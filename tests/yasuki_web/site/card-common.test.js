import { describe, it, beforeEach, mock } from 'node:test';
import assert from 'node:assert/strict';

globalThis.fetch = mock.fn();

const { displayName, fallbackSrc, fetchImageBase, fetchConfig } = await import(
  '../../../src/yasuki_web/static/site/card-common.js'
);

beforeEach(() => {
  fetch.mock.resetCalls();
});

describe('displayName', () => {
  it('prefers the extended title over the plain name', () => {
    assert.equal(displayName({ name: 'Togashi', extended_title: 'Togashi (Experienced)' }), 'Togashi (Experienced)');
  });

  it('falls back to the name when there is no extended title', () => {
    assert.equal(displayName({ name: 'Hida Kisada' }), 'Hida Kisada');
  });

  it('prefixes a diamond for unique cards', () => {
    assert.equal(displayName({ name: 'Hida Kisada', is_unique: true }), '◆ Hida Kisada');
  });

  it('returns an empty string when the card has no title', () => {
    assert.equal(displayName({}), '');
  });
});

describe('fallbackSrc', () => {
  it('maps the first card type to its generic art under the image base', () => {
    assert.equal(
      fallbackSrc({ types: ['Personality'] }, '/images'),
      '/images/defaults/generic_personality.jpg',
    );
  });

  it('uses the clan frame for an aligned personality', () => {
    assert.equal(
      fallbackSrc({ types: ['Personality'], clans: ['Crane'] }, '/images'),
      '/images/defaults/generic_personality_crane.jpg',
    );
  });

  it('falls back to the base personality frame for a non-great-clan alignment', () => {
    assert.equal(
      fallbackSrc({ types: ['Personality'], clans: ['Ratling'] }, '/images'),
      '/images/defaults/generic_personality.jpg',
    );
  });

  it('returns null for an unknown type', () => {
    assert.equal(fallbackSrc({ types: ['Mystery'] }, '/images'), null);
  });

  it('returns null when the card has no types', () => {
    assert.equal(fallbackSrc({}, '/images'), null);
  });
});

describe('fetchImageBase', () => {
  it('returns the configured image base URL', async () => {
    fetch.mock.mockImplementation(() =>
      Promise.resolve({ json: () => Promise.resolve({ image_base_url: 'https://cdn.example/r2' }) }),
    );
    assert.equal(await fetchImageBase(), 'https://cdn.example/r2');
    assert.equal(fetch.mock.calls[0].arguments[0], '/api/config');
  });

  it('defaults to the local mount when config omits the base', async () => {
    fetch.mock.mockImplementation(() => Promise.resolve({ json: () => Promise.resolve({}) }));
    assert.equal(await fetchImageBase(), '/images');
  });

  it('defaults to the local mount when the request fails', async () => {
    fetch.mock.mockImplementation(() => Promise.reject(new Error('offline')));
    assert.equal(await fetchImageBase(), '/images');
  });
});

describe('fetchConfig', () => {
  it('returns the image base, debug flag, and dev-login flag from config', async () => {
    fetch.mock.mockImplementation(() =>
      Promise.resolve({
        json: () =>
          Promise.resolve({ image_base_url: 'https://cdn.example/r2', debug: true, dev_login: true }),
      }),
    );
    assert.deepEqual(await fetchConfig(), {
      imageBase: 'https://cdn.example/r2',
      debug: true,
      devLogin: true,
    });
  });

  it('defaults flags off and to the local mount when config is empty', async () => {
    fetch.mock.mockImplementation(() => Promise.resolve({ json: () => Promise.resolve({}) }));
    assert.deepEqual(await fetchConfig(), { imageBase: '/images', debug: false, devLogin: false });
  });

  it('defaults flags off when the request fails', async () => {
    fetch.mock.mockImplementation(() => Promise.reject(new Error('offline')));
    assert.deepEqual(await fetchConfig(), { imageBase: '/images', debug: false, devLogin: false });
  });
});
