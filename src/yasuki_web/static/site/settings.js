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
} from './account-api.js';
import { fetchConfig } from './card-common.js';
import { drawCardAvatar, loadImage } from './avatar.js';
import { createCropEditor } from './card-crop.js';

const SEARCH_DEBOUNCE_MS = 300;
// The admin pane's tab and content stay hidden/empty for non-admins; the server is the real gate.
const PANES = ['display', 'privacy', 'delete', 'admin'];

// Map a URL hash (without the leading '#') to a pane id, falling back to the first pane for an
// unknown or empty hash.
export function resolvePane(hash) {
  return PANES.includes(hash) ? hash : PANES[0];
}

async function init() {
  initPanes();
  const user = await getMe();
  if (!user) {
    window.location.href = '/auth/login';
    return;
  }
  initDisplayName(user);
  initDeleteAccount();
  if (user.role === 'admin') initAdmin(user);
  const { imageBase } = await fetchConfig().catch(() => ({ imageBase: '/images' }));
  initAvatarEditor(user, imageBase);
}

// Reveal and populate the admin pane. Gated on the role the server reports; every action it offers
// is re-checked server-side, so this is convenience, not the security boundary.
function initAdmin(user) {
  document.querySelector('.settings-tab[data-pane="admin"]').classList.remove('hidden');
  const tbody = document.getElementById('adminUsers');
  const status = document.getElementById('adminStatus');
  const run = async (working, action) => {
    status.textContent = working;
    const ok = await action();
    status.textContent = ok ? '' : 'Could not update the account.';
    if (ok) await load();
  };
  const load = async () => {
    const [accounts, roles] = await Promise.all([listAccounts(), listRoles()]);
    renderAdminUsers(tbody, accounts, {
      selfId: user.id,
      roles: roles.map((role) => role.name),
      onSetRole: (id, role) => run('Updating role…', () => setRole(id, role)),
      onBan: (id, isBanned) =>
        run(isBanned ? 'Lifting ban…' : 'Banning…', () =>
          isBanned ? unbanAccount(id) : banAccount(id),
        ),
    });
  };

  const nameInput = document.getElementById('newRoleName');
  document.getElementById('addRoleForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const name = nameInput.value.trim();
    if (!name) return;
    status.textContent = 'Adding role…';
    const updated = await createRole(name);
    status.textContent = updated.length ? '' : 'Could not add the role.';
    if (updated.length) {
      nameInput.value = '';
      await load();
    }
  });

  load();
}

const formatDay = (iso) => (iso ? new Date(iso).toLocaleDateString() : '—');

// Fill the admin table body with one row per account. The role cell is a picker of the defined
// roles; the local admin's own row shows its role as plain text and gets no ban, since changing
// your own role or banning yourself would lock you out (both also refused server-side). `opts` is
// { selfId, roles, onSetRole(id, role), onBan(id, isBanned) }.
export function renderAdminUsers(tbody, accounts, { selfId, roles, onSetRole, onBan }) {
  const cell = (text) => {
    const td = document.createElement('td');
    td.textContent = text;
    return td;
  };
  tbody.replaceChildren(
    ...accounts.map((account) => {
      const isSelf = account.id === selfId;
      const row = document.createElement('tr');
      row.append(cell(account.display_name), roleCell(account, isSelf, roles, onSetRole));
      row.append(
        cell(account.is_banned ? 'Banned' : 'Active'),
        cell(formatDay(account.created_at)),
        cell(formatDay(account.last_seen)),
      );
      const actions = document.createElement('td');
      if (!isSelf) {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = account.is_banned ? 'btn-unban' : 'btn-ban';
        button.textContent = account.is_banned ? 'Unban' : 'Ban';
        button.addEventListener('click', () => onBan(account.id, account.is_banned));
        actions.append(button);
      }
      row.append(actions);
      return row;
    }),
  );
}

function roleCell(account, isSelf, roles, onSetRole) {
  const td = document.createElement('td');
  if (isSelf) {
    td.textContent = account.role;
    return td;
  }
  const select = document.createElement('select');
  select.className = 'role-select';
  // The current role is always an option, even if it is somehow no longer in the defined set, so
  // the picker never silently misrepresents it.
  for (const name of roles.includes(account.role) ? roles : [account.role, ...roles]) {
    const option = document.createElement('option');
    option.value = name;
    option.textContent = name;
    select.append(option);
  }
  select.value = account.role;
  select.addEventListener('change', () => onSetRole(account.id, select.value));
  td.append(select);
  return td;
}

// Left-column tabs select a pane via the URL hash, so each is bookmarkable.
function initPanes() {
  const show = () => {
    const target = resolvePane(location.hash.slice(1));
    for (const name of PANES) {
      document.getElementById(`pane-${name}`).classList.toggle('active', name === target);
    }
    for (const tab of document.querySelectorAll('.settings-tab')) {
      tab.classList.toggle('active', tab.dataset.pane === target);
    }
  };
  window.addEventListener('hashchange', show);
  show();
}

function initDeleteAccount() {
  const status = document.getElementById('deleteStatus');
  document.getElementById('deleteAccountBtn').addEventListener('click', async () => {
    const confirmed = window.confirm(
      'Delete your account? This erases your profile, saved decks, and sessions, and cannot be undone.',
    );
    if (!confirmed) return;
    status.textContent = 'Deleting…';
    if (await deleteAccount()) {
      window.location.href = '/';
    } else {
      status.textContent = 'Could not delete the account.';
    }
  });
}

function initDisplayName(user) {
  const form = document.getElementById('displayNameForm');
  const input = document.getElementById('displayNameInput');
  const status = document.getElementById('settingsStatus');
  input.value = user.display_name;
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    status.textContent = 'Saving…';
    const result = await updateDisplayName(input.value.trim());
    status.textContent = result.ok
      ? `Saved — you are now ${result.user.display_name}`
      : result.error;
  });
}

function initAvatarEditor(user, imageBase) {
  const searchInput = document.getElementById('cardSearch');
  const results = document.getElementById('cardResults');
  const cropCanvas = document.getElementById('cropCanvas');
  const preview = document.getElementById('avatarPreview');
  const status = document.getElementById('avatarStatus');

  let selected = null; // { cardId, crop }

  function pickCard(card, initialCrop = null) {
    return loadImage(`${imageBase}/${card.image_path}`).then((image) => {
      createCropEditor(
        cropCanvas,
        image,
        (crop) => {
          selected = { cardId: card.card_id, crop };
          drawCardAvatar(preview, image, crop);
        },
        initialCrop,
      );
    });
  }

  // Keep the player's current avatar card on screen, ready to re-crop.
  if (user.avatar) {
    pickCard(
      { card_id: user.avatar.card_id, image_path: user.avatar.image_path },
      user.avatar.crop,
    ).catch(() => {});
  }

  let timer = null;
  searchInput.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const cards = await searchCards(searchInput.value.trim());
      results.replaceChildren(...cards.map((card) => cardResult(card, pickCard, status)));
    }, SEARCH_DEBOUNCE_MS);
  });

  document.getElementById('saveAvatar').addEventListener('click', async () => {
    if (!selected) {
      status.textContent = 'Pick a card first.';
      return;
    }
    status.textContent = 'Saving…';
    const ok = await setAvatar(selected.cardId, selected.crop);
    status.textContent = ok ? 'Avatar saved.' : 'Could not save the avatar.';
  });

  document.getElementById('clearAvatar').addEventListener('click', async () => {
    status.textContent = (await clearAvatar()) ? 'Using your initials.' : 'Could not clear it.';
  });
}

function cardResult(card, pickCard, status) {
  const li = document.createElement('li');
  li.className = 'card-result';
  li.textContent = card.extended_title || card.name;
  li.addEventListener('click', () => {
    pickCard(card).catch(() => {
      status.textContent = 'Could not load that card image.';
    });
  });
  return li;
}

if (typeof window !== 'undefined') init();
