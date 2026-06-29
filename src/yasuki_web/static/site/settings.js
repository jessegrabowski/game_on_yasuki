import {
  getMe,
  updateDisplayName,
  searchCards,
  setAvatar,
  clearAvatar,
  deleteAccount,
} from './account-api.js';
import { fetchConfig } from './card-common.js';
import { drawCardAvatar, loadImage } from './avatar.js';
import { createCropEditor } from './card-crop.js';

const SEARCH_DEBOUNCE_MS = 300;
const PANES = ['display', 'privacy', 'delete'];

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
  const { imageBase } = await fetchConfig().catch(() => ({ imageBase: '/images' }));
  initAvatarEditor(user, imageBase);
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
