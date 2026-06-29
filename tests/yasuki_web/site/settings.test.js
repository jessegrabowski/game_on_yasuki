import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { resetDOM } from '../deck_builder/dom-shim.js';
import { resolvePane, renderAdminUsers } from '../../../src/yasuki_web/static/site/settings.js';

describe('resolvePane', () => {
  it('keeps a known pane id', () => {
    assert.equal(resolvePane('privacy'), 'privacy');
    assert.equal(resolvePane('delete'), 'delete');
    assert.equal(resolvePane('admin'), 'admin');
  });

  it('falls back to the first pane for an unknown or empty hash', () => {
    assert.equal(resolvePane(''), 'display');
    assert.equal(resolvePane('nope'), 'display');
  });
});

describe('renderAdminUsers', () => {
  beforeEach(resetDOM);

  const accounts = [
    { id: 1, display_name: 'Ada', role: 'admin', is_banned: false, created_at: '2026-01-01T00:00:00Z', last_seen: '2026-06-01T00:00:00Z' },
    { id: 2, display_name: 'Kenji', role: 'user', is_banned: false, created_at: '2026-01-02T00:00:00Z', last_seen: '2026-06-02T00:00:00Z' },
    { id: 3, display_name: 'Rogue', role: 'user', is_banned: true, created_at: '2026-01-03T00:00:00Z', last_seen: null },
  ];
  const opts = (over) => ({
    selfId: 1,
    roles: ['user', 'admin', 'moderator'],
    onSetRole() {},
    onBan() {},
    ...over,
  });

  it('renders name and status per account', () => {
    const tbody = document.createElement('tbody');
    renderAdminUsers(tbody, accounts, opts());
    assert.equal(tbody.children.length, 3);
    assert.equal(tbody.children[1].children[0].textContent, 'Kenji');
    assert.equal(tbody.children[1].children[2].textContent, 'Active');
    assert.equal(tbody.children[2].children[2].textContent, 'Banned');
  });

  it('shows a dash for an account that has never been seen', () => {
    const tbody = document.createElement('tbody');
    renderAdminUsers(tbody, accounts, opts());
    assert.equal(tbody.children[2].children[4].textContent, '—'); // Rogue: last_seen null
  });

  it('shows the role as a picker for others and plain text for self', () => {
    const tbody = document.createElement('tbody');
    renderAdminUsers(tbody, accounts, opts());
    assert.equal(tbody.children[0].children[1].textContent, 'admin'); // self: plain text
    const select = tbody.children[1].children[1].children[0];
    assert.equal(select.tagName, 'SELECT');
    assert.equal(select.value, 'user');
    assert.deepEqual(
      select.children.map((option) => option.value),
      ['user', 'admin', 'moderator'],
    );
  });

  it('gives others a Ban/Unban button but the local admin none', () => {
    const tbody = document.createElement('tbody');
    renderAdminUsers(tbody, accounts, opts());
    assert.equal(tbody.children[0].children[5].children.length, 0); // self: no action
    assert.equal(tbody.children[1].children[5].children[0].textContent, 'Ban');
    assert.equal(tbody.children[2].children[5].children[0].textContent, 'Unban');
  });

  it('calls onSetRole with the chosen role and onBan with the banned state', () => {
    const tbody = document.createElement('tbody');
    const calls = [];
    renderAdminUsers(
      tbody,
      accounts,
      opts({
        onSetRole: (id, role) => calls.push(['role', id, role]),
        onBan: (id, isBanned) => calls.push(['ban', id, isBanned]),
      }),
    );
    const select = tbody.children[1].children[1].children[0];
    select.value = 'moderator';
    select._emit('change', {});
    tbody.children[2].children[5].children[0]._emit('click', {}); // Rogue → Unban
    assert.deepEqual(calls, [
      ['role', 2, 'moderator'],
      ['ban', 3, true],
    ]);
  });
});
