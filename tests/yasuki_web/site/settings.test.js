import { describe, it, beforeEach } from 'node:test';
import assert from 'node:assert/strict';

import { resetDOM } from '../deck_builder/dom-shim.js';
import {
  resolvePane,
  renderAdminUsers,
  renderNotice,
} from '../../../src/yasuki_web/static/site/settings.js';

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

describe('renderNotice', () => {
  beforeEach(resetDOM);

  const notice = () => document.createElement('div');

  it('prompts a nameless account to onboard', () => {
    const el = notice();
    renderNotice(el, { display_name: null, is_approved: false });
    assert.match(el.textContent, /Choose a display name/);
    assert.ok(!el.classList.contains('hidden'));
  });

  it('shows the awaiting-approval notice once named but unapproved', () => {
    const el = notice();
    renderNotice(el, { display_name: 'Ada', is_approved: false });
    assert.match(el.textContent, /awaiting approval/);
    assert.ok(!el.classList.contains('hidden'));
  });

  it('hides once named and approved', () => {
    const el = notice();
    renderNotice(el, { display_name: 'Ada', is_approved: true });
    assert.ok(el.classList.contains('hidden'));
  });
});

describe('renderAdminUsers', () => {
  beforeEach(resetDOM);

  const accounts = [
    { id: 1, display_name: 'Ada', role: 'admin', is_approved: true, is_banned: false, created_at: '2026-01-01T00:00:00Z', last_seen: '2026-06-01T00:00:00Z' },
    { id: 2, display_name: 'Kenji', role: 'user', is_approved: true, is_banned: false, created_at: '2026-01-02T00:00:00Z', last_seen: '2026-06-02T00:00:00Z' },
    { id: 3, display_name: 'Rogue', role: 'user', is_approved: true, is_banned: true, created_at: '2026-01-03T00:00:00Z', last_seen: null },
    { id: 4, display_name: 'Newbie', role: 'user', is_approved: false, is_banned: false, created_at: '2026-01-04T00:00:00Z', last_seen: '2026-06-04T00:00:00Z' },
  ];
  const opts = (over) => ({
    selfId: 1,
    roles: ['user', 'admin', 'moderator'],
    onSetRole() {},
    onBan() {},
    onApprove() {},
    ...over,
  });

  it('renders the status as Active, Banned, or Pending', () => {
    const tbody = document.createElement('tbody');
    renderAdminUsers(tbody, accounts, opts());
    assert.equal(tbody.children.length, 4);
    assert.equal(tbody.children[1].children[0].textContent, 'Kenji');
    assert.equal(tbody.children[1].children[2].textContent, 'Active');
    assert.equal(tbody.children[2].children[2].textContent, 'Banned');
    assert.equal(tbody.children[3].children[2].textContent, 'Pending');
  });

  it('shows (unnamed) for an account that has not picked a name yet', () => {
    const tbody = document.createElement('tbody');
    const nameless = { id: 5, display_name: null, role: 'user', is_approved: false, is_banned: false, created_at: '2026-01-05T00:00:00Z', last_seen: null };
    renderAdminUsers(tbody, [nameless], opts());
    assert.equal(tbody.children[0].children[0].textContent, '(unnamed)');
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

  it('gives each row the right actions: none for self, Approve+Ban for pending', () => {
    const tbody = document.createElement('tbody');
    renderAdminUsers(tbody, accounts, opts());
    const labels = (row) => tbody.children[row].children[5].children.map((b) => b.textContent);
    assert.deepEqual(labels(0), []); // self
    assert.deepEqual(labels(1), ['Ban']); // active
    assert.deepEqual(labels(2), ['Unban']); // banned
    assert.deepEqual(labels(3), ['Approve', 'Ban']); // pending
  });

  it('wires role, ban, and approve clicks to their handlers', () => {
    const tbody = document.createElement('tbody');
    const calls = [];
    renderAdminUsers(
      tbody,
      accounts,
      opts({
        onSetRole: (id, role) => calls.push(['role', id, role]),
        onBan: (id, isBanned) => calls.push(['ban', id, isBanned]),
        onApprove: (id) => calls.push(['approve', id]),
      }),
    );
    const select = tbody.children[1].children[1].children[0];
    select.value = 'moderator';
    select._emit('change', {});
    tbody.children[2].children[5].children[0]._emit('click', {}); // Rogue → Unban
    tbody.children[3].children[5].children[0]._emit('click', {}); // Newbie → Approve
    assert.deepEqual(calls, [
      ['role', 2, 'moderator'],
      ['ban', 3, true],
      ['approve', 4],
    ]);
  });
});
