import { getMe, updateDisplayName, searchCards, setAvatar, clearAvatar } from './account-api.js';
import { fetchConfig } from './card-common.js';
import { drawCardAvatar, loadImage } from './avatar.js';
import { createCropEditor } from './card-crop.js';

const SEARCH_DEBOUNCE_MS = 300;

async function init() {
  const user = await getMe();
  if (!user) {
    window.location.href = '/auth/login';
    return;
  }
  initDisplayName(user);
  const { imageBase } = await fetchConfig().catch(() => ({ imageBase: '/images' }));
  initAvatarEditor(user, imageBase);
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

init();
