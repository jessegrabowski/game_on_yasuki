import { getMe, updateDisplayName } from './account-api.js';

async function init() {
  const user = await getMe();
  if (!user) {
    window.location.href = '/auth/login';
    return;
  }

  const form = document.getElementById('displayNameForm');
  const input = document.getElementById('displayNameInput');
  const status = document.getElementById('settingsStatus');
  input.value = user.display_name;

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    status.textContent = 'Saving…';
    const result = await updateDisplayName(input.value.trim());
    status.textContent = result.ok ? `Saved — you are now ${result.user.display_name}` : result.error;
  });
}

init();
