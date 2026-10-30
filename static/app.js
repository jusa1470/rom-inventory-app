import { API, setUnauthorizedHandler } from './api.js';
import { DashboardPage } from './pages/dashboard_page.js';
import { OrdersPage } from './pages/orders_page.js';
import { ProductsPage } from './pages/products_page.js';
import { renderLogin } from './pages/login_page.js';
import { SettingsPage } from './pages/settings_page.js';

const NAV = [
  { hash: '#dashboard', label: 'Dashboard' },
  { hash: '#products', label: 'Products' },
  { hash: '#orders', label: 'Orders' },
  { hash: '#settings', label: 'Settings' },
];

const PAGES = {
  '#dashboard': DashboardPage,
  '#products': ProductsPage,
  '#orders': OrdersPage,
  '#settings': SettingsPage,
};

const root = document.getElementById('root');
let currentPage = null;

function renderShell() {
  root.innerHTML = `
    <div class="app-shell">
      <nav class="navbar">
        <span class="navbar-brand">Record<span>Sync</span></span>
        ${NAV.map(n => `<button class="nav-btn" data-hash="${n.hash}">${n.label}</button>`).join('')}
        <div id="dry-run-banner" class="test-banner" style="display:none">TEST MODE</div>
        <div class="nav-spacer"></div>
        <button class="nav-btn danger" id="nav-logout">Lock</button>
      </nav>
      <main id="page-content"></main>
    </div>`;
  document.getElementById('nav-logout').addEventListener('click', logout);
  root.querySelectorAll('.nav-btn[data-hash]').forEach(btn =>
    btn.addEventListener('click', () => { location.hash = btn.getAttribute('data-hash'); }));
}

function baseHash(hash) {
  const base = (hash || '#dashboard').split('?')[0];
  return PAGES[base] ? base : '#dashboard';
}

async function navigate(hash) {
  const base = baseHash(hash);
  root.querySelectorAll('.nav-btn[data-hash]').forEach(btn =>
    btn.classList.toggle('active', btn.getAttribute('data-hash') === base));
  const content = document.getElementById('page-content');
  if (!content) return;
  if (currentPage && currentPage.destroy) currentPage.destroy();
  content.innerHTML = '<div class="page muted">Loading…</div>';
  currentPage = new PAGES[base]();
  await currentPage.render(content);
}

function showLogin() {
  window.onhashchange = null;
  if (currentPage && currentPage.destroy) currentPage.destroy();
  currentPage = null;
  renderLogin(root, start);
}

async function logout() {
  await API.post('/api/logout').catch(() => {});
  location.hash = '';
  showLogin();
}

async function start() {
  renderShell();
  window.onhashchange = () => navigate(location.hash);
  navigate(location.hash);
  API.get('/api/settings')
    .then(s => {
      const banner = document.getElementById('dry-run-banner');
      if (banner) banner.style.display = s.dry_run ? 'flex' : 'none';
    })
    .catch(() => {});
}

async function init() {
  setUnauthorizedHandler(showLogin);
  try {
    await API.get('/api/me');
    start();
  } catch (_) {
    showLogin();
  }
}

init();