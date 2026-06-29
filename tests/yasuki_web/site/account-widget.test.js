import { describe, it, beforeEach, mock } from 'node:test';
import assert from 'node:assert/strict';

import { resetDOM } from '../deck_builder/dom-shim.js';

globalThis.fetch = mock.fn();

import { getMe, updateDisplayName } from '../../../src/yasuki_web/static/site/account-api.js';
import { buildAccountControl } from '../../../src/yasuki_web/static/site/account-widget.js';

const respond = (body, { ok = true, status = 200 } = {}) =>
  Promise.resolve({ ok, status, json: () => Promise.resolve(body) });

beforeEach(() => {
  resetDOM();
  fetch.mock.resetCalls();
});

describe('getMe', () => {
  it('returns the user when signed in', async () => {
    fetch.mock.mockImplementation(() => respond({ user: { id: 1, display_name: 'StoicCrane204' } }));
    assert.deepEqual(await getMe(), { id: 1, display_name: 'StoicCrane204' });
  });

  it('returns null when signed out', async () => {
    fetch.mock.mockImplementation(() => respond({ user: null }));
    assert.equal(await getMe(), null);
  });
});

describe('updateDisplayName', () => {
  it('PATCHes the new name and returns the updated user', async () => {
    fetch.mock.mockImplementation(() => respond({ user: { id: 1, display_name: 'Hida Kisada' } }));
    const result = await updateDisplayName('Hida Kisada');

    assert.deepEqual(result, { ok: true, user: { id: 1, display_name: 'Hida Kisada' } });
    const [url, options] = fetch.mock.calls[0].arguments;
    assert.equal(url, '/api/me');
    assert.equal(options.method, 'PATCH');
    assert.deepEqual(JSON.parse(options.body), { display_name: 'Hida Kisada' });
  });

  it('surfaces a validation message from a 422', async () => {
    const body = { detail: [{ msg: 'String should have at most 40 characters' }] };
    fetch.mock.mockImplementation(() => respond(body, { ok: false, status: 422 }));
    const result = await updateDisplayName('N'.repeat(41));
    assert.equal(result.ok, false);
    assert.match(result.error, /40 characters/);
  });

  it('maps a 401 to a sign-in prompt', async () => {
    fetch.mock.mockImplementation(() => respond({}, { ok: false, status: 401 }));
    assert.deepEqual(await updateDisplayName('Anon'), {
      ok: false,
      error: 'Sign in to change your name',
    });
  });
});

describe('buildAccountControl', () => {
  it('shows a Sign in link when logged out', () => {
    const widget = buildAccountControl(null);
    const link = widget.children[0];
    assert.equal(link.textContent, 'Sign in');
    assert.equal(link.href, '/auth/login');
  });

  it('shows the name, an initials avatar, and a hidden Settings/Log out menu', () => {
    const widget = buildAccountControl({ display_name: 'Hida Kisada' });
    const [button, menu] = widget.children;
    assert.equal(button.children[0].textContent, 'Hida Kisada');
    assert.equal(button.children[1].textContent, 'HK'); // initials avatar, right of the name
    assert.ok(menu.classList.contains('hidden'), 'menu starts hidden');
    assert.deepEqual(
      menu.children.map((c) => c.textContent),
      ['Settings', 'Log out'],
    );
    assert.equal(menu.children[0].href, '/settings');
  });

  it('toggles the menu open when the name button is clicked', () => {
    const widget = buildAccountControl({ display_name: 'StoicCrane204' });
    const [button, menu] = widget.children;
    button._emit('click', {});
    assert.ok(!menu.classList.contains('hidden'), 'menu opens on click');
  });

  it('logs out and runs onLogout when Log out is clicked', async () => {
    fetch.mock.mockImplementation(() => respond({}));
    let loggedOut = false;
    const widget = buildAccountControl(
      { display_name: 'StoicCrane204' },
      { onLogout: () => (loggedOut = true) },
    );
    widget.children[1].children[1]._emit('click', {}); // menu > Log out
    await new Promise((resolve) => setTimeout(resolve, 0)); // let the async handler settle

    assert.ok(
      fetch.mock.calls.some((c) => c.arguments[0] === '/auth/logout'),
      'posts to the logout endpoint',
    );
    assert.ok(loggedOut, 'runs the onLogout callback');
  });
});
