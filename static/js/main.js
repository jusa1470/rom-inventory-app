// ─────────────────────────────────────────────────────────────────────────────
// RecordSync Frontend
// Pure vanilla JS — no framework dependencies.
// All state lives in `App`. All API calls go through `api.*`.
// The router maps page keys to render functions.
// Auth gate: every page checks App.authed before rendering.
// ─────────────────────────────────────────────────────────────────────────────

import { api } from './api.js';
import { App, startPolling, stopPolling, navigate, SESSION_KEY, loadSyncStatus } from './core.js';
import { h, withLoading } from './utils.js';

import { renderDashboard } from './pages/dashboard.js';
import { renderTrackOrders } from './pages/trackOrders.js';
import { renderWebami } from './pages/webami.js';
import { renderShopify } from './pages/shopify.js';
import { renderSync } from './pages/sync.js';

// expose render globally so core.js can call it
// @ts-ignore
window.render = render;

// ── Top-level render ───────────────────────────────────────────────────────────
function render() {
  const root = document.getElementById('root');
  root.innerHTML = '';
  if (!App.authed) { stopPolling(); root.appendChild(renderLockScreen()); return; }
  root.appendChild(renderShell());
  startPolling();
}

// ── Lock screen ────────────────────────────────────────────────────────────────
function renderLockScreen() {
  let shaking = false;

  const pwInput = h('input', {
    class: 'input',
    type: 'password',
    placeholder: 'Enter app password',
    id: 'pw-input',
    style: 'font-size:15px;height:46px;text-align:center;letter-spacing:0.1em;',
  });

  const errMsg = h('div', {
    class: 'alert alert-error',
    style: 'display:none;width:100%;text-align:center;',
  }, 'Incorrect password');

  const btn = h('button', {
    class: 'btn btn-primary btn-lg',
    style: 'width:100%;',
    onClick: doAuth,
  }, 'Unlock');

  async function doAuth() {
    const pw = pwInput.value.trim();
    if (!pw) return;
    await withLoading(btn, async () => {
      try {
        await api.verify(pw);
        App.authed = true;
        App.page = 'dashboard';
        sessionStorage.setItem(SESSION_KEY, '1');
        render();
        loadSyncStatus();
      } catch (e) {
        errMsg.style.display = 'flex';
        if (!shaking) {
          shaking = true;
          box.style.animation = 'none';
          box.style.animation = 'shake 0.4s ease';
          setTimeout(() => { shaking = false; box.style.animation = ''; }, 400);
        }
        pwInput.value = '';
        pwInput.focus();
      }
    });
  }

  pwInput.addEventListener('keydown', e => { if (e.key === 'Enter') doAuth(); });

  const box = h('div', { class: 'connect-box' },
    h('div', { class: 'vinyl-ring' }),
    h('div', { class: 'connect-logo' }, 'Record', h('span', {}, 'Sync')),
    h('div', { class: 'connect-subtitle' }, 'Inventory Management'),
    h('div', { class: 'connect-form' }, errMsg, pwInput, btn),
  );

  if (!document.getElementById('shake-style')) {
    const s = document.createElement('style');
    s.id = 'shake-style';
    s.textContent = '@keyframes shake{0%,100%{transform:translateX(0)}20%,60%{transform:translateX(-8px)}40%,80%{transform:translateX(8px)}}';
    document.head.appendChild(s);
  }

  return h('div', { class: 'connect-page' }, box);
}

// ── App shell ──────────────────────────────────────────────────────────────────
function renderShell() {
  const pages = [
    { key: 'dashboard',    label: 'Dashboard' },
    { key: 'trackOrders',  label: 'Track Orders' },
    { key: 'webami',       label: 'Webami' },
    { key: 'shopify',      label: 'Shopify' },
    { key: 'sync',         label: 'Sync' },
  ];

  const navBtns = pages.map(p =>
    h('button', {
      class: `nav-btn${App.page === p.key ? ' active' : ''}`,
      onClick: () => navigate(p.key),
    }, p.label)
  );

  const lockBtn = h('button', {
    class: 'nav-btn danger',
    onClick: () => { App.authed = false; App.page = 'lock'; sessionStorage.removeItem(SESSION_KEY); render(); },
  }, 'Lock');

  const navbar = h('nav', { class: 'navbar' },
    h('div', { class: 'navbar-brand' }, 'Record', h('span', {}, 'Sync')),
    ...navBtns,
    h('div', { class: 'nav-spacer' }),
    lockBtn,
  );

  const pageMap = {
    dashboard:   renderDashboard,
    trackOrders: renderTrackOrders,
    webami:      renderWebami,
    shopify:     renderShopify,
    sync:        renderSync,
  };

  const pageEl = h('main', { class: 'page' });
  const renderer = pageMap[App.page] || renderDashboard;
  pageEl.appendChild(renderer());

  return h('div', { class: 'app-shell' }, navbar, pageEl);
}

// ── Boot ───────────────────────────────────────────────────────────────────────
render();