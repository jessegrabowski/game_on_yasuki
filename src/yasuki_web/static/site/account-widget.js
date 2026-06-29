// The top-right account control in the nav, shared across every page. Shows a Sign in link when
// logged out, or the player's name with a dropdown (Settings, Log out) when logged in. Built with
// createElement so it stays CSP-safe under style-src 'self'.

import { fetchConfig } from './card-common.js';
import { getMe, logout } from './account-api.js';
import { buildAvatarElement } from './avatar.js';

// Build the control for `user` (null = logged out). `onLogout` runs after a successful logout;
// it defaults to a full reload so the page re-renders in the signed-out state. `imgBase` resolves
// a card-crop avatar's image; it's unused for the initials fallback.
export function buildAccountControl(user, { onLogout, imgBase } = {}) {
  const widget = document.createElement('div');
  widget.className = 'account-widget';

  if (!user) {
    const signIn = document.createElement('a');
    signIn.className = 'account-signin';
    signIn.href = '/auth/login';
    signIn.textContent = 'Sign in';
    widget.append(signIn);
    return widget;
  }

  const button = document.createElement('button');
  button.type = 'button';
  button.className = 'account-button';
  const name = document.createElement('span');
  name.className = 'account-name';
  name.textContent = user.display_name;
  button.append(name, buildAvatarElement(user, imgBase));

  const menu = document.createElement('div');
  menu.className = 'account-menu';
  menu.classList.add('hidden');

  const settings = document.createElement('a');
  settings.href = '/settings';
  settings.textContent = 'Settings';

  const signOut = document.createElement('button');
  signOut.type = 'button';
  signOut.className = 'account-menu-item';
  signOut.textContent = 'Log out';
  signOut.addEventListener('click', async () => {
    await logout();
    (onLogout ?? (() => window.location.reload()))();
  });

  menu.append(settings, signOut);
  button.addEventListener('click', () => menu.classList.toggle('hidden'));
  widget.append(button, menu);
  return widget;
}

export async function initAccountWidget() {
  const nav = document.querySelector('.ribbon-nav');
  if (!nav) return;
  const [user, config] = await Promise.all([
    getMe(),
    fetchConfig().catch(() => ({ imageBase: '/images' })),
  ]);
  nav.append(buildAccountControl(user, { imgBase: config.imageBase }));
}

initAccountWidget();
