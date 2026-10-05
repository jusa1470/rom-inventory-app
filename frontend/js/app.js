/* ─── App Router ──────────────────────────────────────────── */
const App = (() => {
  const NAV = [
    { hash: '#dashboard', label: 'Dashboard' },
    { hash: '#products',  label: 'Products'  },
    { hash: '#matching',  label: 'Matching'  },
    { hash: '#orders',    label: 'Orders'    },
    { hash: '#receiving', label: 'Receiving' },
    { hash: '#rules',     label: 'Rules'     },
    { hash: '#settings',  label: 'Settings'  },
  ];

  const PAGES = {
    '#dashboard': () => new DashboardPage(),
    '#products':  () => new ProductsPage(),
    '#matching':  () => new MatchingPage(),
    '#orders':    () => new OrdersPage(),
    '#receiving': () => new ReceivingPage(),
    '#rules':     () => new RulesPage(),
    '#settings':  () => new SettingsPage(),
  };

  let currentPage = null;
  let root;

  function renderShell() {
    root.innerHTML = `
      <div class="app-shell">
        <nav class="navbar">
          <span class="navbar-brand">VINYL<span>SYNC</span></span>
          ${NAV.map(n => `<button class="nav-btn" data-hash="${n.hash}">${n.label}</button>`).join('')}
          <div id="dry-run-banner" style="display:none;align-items:center;padding:0 14px;
            background:rgba(241,90,36,0.15);color:var(--orange);font-size:12px;
            font-weight:700;letter-spacing:.06em;border-radius:4px">⚠ DRY RUN</div><div class="nav-spacer"></div>
          <button class="nav-btn danger" id="nav-logout">Logout</button>
        </nav>
        <main id="page-content" class="page" style="padding:0;overflow-y:auto;flex:1"></main>
      </div>`;

    document.getElementById('nav-logout').addEventListener('click', logout);
    document.querySelectorAll('.nav-btn[data-hash]').forEach(btn => {
      btn.addEventListener('click', () => { location.hash = btn.dataset.hash; });
    });
  }

  /* FIX #2: strip query params from hash before looking up page */
  function _baseHash(hash) {
    return (hash || '#dashboard').split('?')[0].split('&')[0];
  }

  async function navigate(hash) {
    const base    = _baseHash(hash);
    const factory = PAGES[base] || PAGES['#dashboard'];

    document.querySelectorAll('.nav-btn[data-hash]').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.hash === base);
    });

    const content = document.getElementById('page-content');
    if (!content) return;
    content.innerHTML = '<div style="padding:24px;color:var(--text-muted);font-size:13px">Loading…</div>';

    currentPage = factory();
    await currentPage.render(content);
  }

  async function logout() {
    await API.post('/api/auth/logout').catch(() => {});
    location.hash = '';
    // Remove hashchange listener before re-init to avoid duplicate binding
    window.onhashchange = null;
    init();
  }

  async function init() {
    root = document.getElementById('root');
    root.innerHTML = '';

    let status;
    try {
      status = await API.get('/api/auth/status');
    } catch (e) {
      root.innerHTML = `<div style="padding:40px;color:var(--text-muted)">Cannot connect to server. Is the app running?</div>`;
      return;
    }

    if (status.setup_required) {
      await new LoginPage(true).render(root);
      return;
    }

    if (!status.authenticated) {
      await new LoginPage(false).render(root);
      return;
    }

    renderShell();
    navigate(location.hash || '#dashboard');
    API.get('/api/settings').then(s => {
      const b = document.getElementById('dry-run-banner');
      if (b) b.style.display = s.dry_run ? 'flex' : 'none';
    }).catch(() => {});
    window.onhashchange = () => navigate(location.hash);
  }

  function onAuthenticated() {
    renderShell();
    navigate('#dashboard');
    window.onhashchange = () => navigate(location.hash);
  }

  return { init, onAuthenticated };
})();

window.addEventListener('DOMContentLoaded', () => App.init());
