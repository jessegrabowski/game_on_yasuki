import { describe, it, beforeEach, mock } from 'node:test';
import assert from 'node:assert/strict';

import { resetDOM } from '../deck_builder/dom-shim.js';

globalThis.fetch = mock.fn();

import {
  getMe,
  updateDisplayName,
  searchCards,
  setAvatar,
  clearAvatar,
  deleteAccount,
  listAccounts,
  banAccount,
  unbanAccount,
  setRole,
  listRoles,
  createRole,
} from '../../../src/yasuki_web/static/site/account-api.js';
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

describe('searchCards', () => {
  it('returns the cards array for a query', async () => {
    fetch.mock.mockImplementation(() => respond({ cards: [{ card_id: 'doji' }] }));
    assert.deepEqual(await searchCards('doji'), [{ card_id: 'doji' }]);
    assert.match(fetch.mock.calls[0].arguments[0], /\/api\/cards\?search=doji&limit=24/);
  });

  it('skips the request and returns empty for a blank query', async () => {
    assert.deepEqual(await searchCards('  '.trim()), []);
    assert.equal(fetch.mock.calls.length, 0);
  });
});

describe('setAvatar / clearAvatar', () => {
  it('POSTs the card id and crop', async () => {
    fetch.mock.mockImplementation(() => respond({ user: {} }));
    const crop = { left: 0.1, top: 0.1, right: 0.4, bottom: 0.4 };
    assert.equal(await setAvatar('doji', crop), true);
    const [url, options] = fetch.mock.calls[0].arguments;
    assert.equal(url, '/api/me/avatar');
    assert.equal(options.method, 'POST');
    assert.deepEqual(JSON.parse(options.body), { card_id: 'doji', crop });
  });

  it('DELETEs to clear', async () => {
    fetch.mock.mockImplementation(() => respond({ user: {} }));
    assert.equal(await clearAvatar(), true);
    assert.equal(fetch.mock.calls[0].arguments[1].method, 'DELETE');
  });
});

describe('deleteAccount', () => {
  it('DELETEs /api/me', async () => {
    fetch.mock.mockImplementation(() => respond({ deleted: true }));
    assert.equal(await deleteAccount(), true);
    const [url, options] = fetch.mock.calls[0].arguments;
    assert.equal(url, '/api/me');
    assert.equal(options.method, 'DELETE');
  });
});

describe('admin account actions', () => {
  it('lists accounts from the admin endpoint', async () => {
    fetch.mock.mockImplementation(() => respond({ users: [{ id: 1, display_name: 'Ada' }] }));
    assert.deepEqual(await listAccounts(), [{ id: 1, display_name: 'Ada' }]);
    assert.equal(fetch.mock.calls[0].arguments[0], '/api/admin/users');
  });

  it('returns empty when listing is forbidden', async () => {
    fetch.mock.mockImplementation(() => respond({}, { ok: false, status: 403 }));
    assert.deepEqual(await listAccounts(), []);
  });

  it('POSTs ban and unban to the account id', async () => {
    fetch.mock.mockImplementation(() => respond({ banned: true }));
    assert.equal(await banAccount(7), true);
    assert.deepEqual(
      [fetch.mock.calls[0].arguments[0], fetch.mock.calls[0].arguments[1].method],
      ['/api/admin/users/7/ban', 'POST'],
    );

    assert.equal(await unbanAccount(7), true);
    assert.deepEqual(
      [fetch.mock.calls[1].arguments[0], fetch.mock.calls[1].arguments[1].method],
      ['/api/admin/users/7/unban', 'POST'],
    );
  });

  it('POSTs a role change carrying the new role', async () => {
    fetch.mock.mockImplementation(() => respond({ role: 'admin' }));
    assert.equal(await setRole(5, 'admin'), true);
    const [url, options] = fetch.mock.calls[0].arguments;
    assert.equal(url, '/api/admin/users/5/role');
    assert.equal(options.method, 'POST');
    assert.deepEqual(JSON.parse(options.body), { role: 'admin' });
  });

  it('lists the defined roles', async () => {
    fetch.mock.mockImplementation(() => respond({ roles: [{ name: 'user' }, { name: 'admin' }] }));
    assert.deepEqual(await listRoles(), [{ name: 'user' }, { name: 'admin' }]);
    assert.equal(fetch.mock.calls[0].arguments[0], '/api/admin/roles');
  });

  it('creates a role and returns the refreshed list', async () => {
    fetch.mock.mockImplementation(() => respond({ roles: [{ name: 'user' }, { name: 'moderator' }] }));
    const roles = await createRole('moderator');
    assert.deepEqual(
      roles.map((role) => role.name),
      ['user', 'moderator'],
    );
    const [url, options] = fetch.mock.calls[0].arguments;
    assert.equal(url, '/api/admin/roles');
    assert.equal(options.method, 'POST');
    assert.deepEqual(JSON.parse(options.body), { name: 'moderator', description: '' });
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

  it('renders a canvas avatar when the user has a card crop', () => {
    const user = {
      display_name: 'Hida Kisada',
      avatar: { image_path: 'sets/x/doji.jpg', crop: { left: 0.1, top: 0.1, right: 0.4, bottom: 0.4 } },
    };
    const widget = buildAccountControl(user, { imgBase: '/images' });
    assert.equal(widget.children[0].children[1].tagName, 'CANVAS');
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
