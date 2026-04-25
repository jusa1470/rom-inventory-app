// ─────────────────────────────────────────────────────────────────────────────
// RecordSync Frontend
// Pure vanilla JS — no framework dependencies.
// All state lives in `App`. All API calls go through `api.*`.
// The router maps page keys to render functions.
// Auth gate: every page checks App.authed before rendering.
// ─────────────────────────────────────────────────────────────────────────────

const BASE = '/api';

// ── State ────────────────────────────────────────────────────────────────────
// ── State ──────────────────────────────────────────────────────────────────
const SESSION_KEY = 'rs_authed';


const App = {
  authed: sessionStorage.getItem(SESSION_KEY) === '1',
  page: sessionStorage.getItem(SESSION_KEY) === '1' ? 'dashboard' : 'lock',
  syncStatus: {},
  running: null,        // null = idle, string = label of active sync
  _lastResultAcked: null, // timestamp of last result we've shown
  _pollTimer: null,     // setInterval handle for running-state polling
  toast: null,
  _toastTimer: null,
};

// ── API layer ─────────────────────────────────────────────────────────────────
const api = {
  async _req(method, path, body, signal) {
    // Sync endpoints can run for many minutes — no timeout on those.
    // All other requests time out after 15 seconds.
    const isSyncCall = path.startsWith('/sync/') && method === 'POST';
    const controller = new AbortController();
    let timer;
    if (!isSyncCall && !signal) {
      timer = setTimeout(() => controller.abort(), 15_000);
      signal = controller.signal;
    }
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    if (signal) opts.signal = signal;
    try {
      const res = await fetch(BASE + path, opts);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw Object.assign(new Error(err.detail || 'Request failed'), { status: res.status });
      }
      return res.json();
    } catch(e) {
      if (e.name === 'AbortError' && !signal?.aborted) {
        throw Object.assign(new Error('Request timed out'), { status: 408 });
      }
      throw e;
    } finally {
      clearTimeout(timer);
    }
  },
  get:    (p)       => api._req('GET',    p),
  post:   (p, b)    => api._req('POST',   p, b),
  put:    (p, b)    => api._req('PUT',    p, b),
  delete: (p, b)    => api._req('DELETE', p, b),

  // Auth
  verify: (pw)      => api.post('/auth/verify', { password: pw }),

  // Sync status
  syncStatus:  ()   => api.get('/sync/status'),
  syncRunning: ()   => api.get('/sync/running'),
  ackResult:   ()   => api.post('/sync/ack-result'),

  // Webami
  webamiOrders:   (q='') => api.get(`/webami/orders?q=${encodeURIComponent(q)}`),
  webamiProducts: (q='') => api.get(`/webami/products?q=${encodeURIComponent(q)}`),
  syncWebamiOrdersFull:        (sig) => api._req('POST', '/sync/webami/orders/full',        undefined, sig),
  syncWebamiOrdersIncremental: (sig) => api._req('POST', '/sync/webami/orders/incremental', undefined, sig),
  syncWebamiProductsFull:      (sig) => api._req('POST', '/sync/webami/products/full',      undefined, sig),
  syncWebamiPrices: (upcs, sig)      => api._req('POST', '/sync/webami/prices', { upcs: upcs || null }, sig),

  // Shopify
  shopifyProducts: (q='') => api.get(`/shopify/products?q=${encodeURIComponent(q)}`),
  syncShopifyFull:         (sig) => api._req('POST', '/sync/shopify/full',        undefined, sig),
  syncShopifyIncremental:  (sig) => api._req('POST', '/sync/shopify/incremental', undefined, sig),
  bridgePrices: (upcs, sig)      => api._req('POST', '/sync/bridge/prices', { upcs: upcs || null }, sig),
  fillGaps: (ids, sig)           => api._req('POST', '/sync/bridge/fill-gaps', { product_ids: ids || null }, sig),
  createProducts: (products)    => api.post('/shopify/products', { products }),
  updateProduct:  (id, data)    => api.put(`/shopify/products/${encodeURIComponent(id)}`, data),
  deleteProduct:  (id)          => api.delete(`/shopify/products/${encodeURIComponent(id)}`),
  bulkDelete:     (ids)         => api.delete('/shopify/products/bulk', { product_ids: ids }),
  bulkUpdate:     (products)    => api.put('/shopify/products/bulk', { products }),
};

// ── Utilities ─────────────────────────────────────────────────────────────────
function h(tag, attrs={}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'class') el.className = v;
    else if (k === 'html') el.innerHTML = v;
    else el.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  return el;
}

function fmt(isoStr) {
  if (!isoStr) return '—';
  const d = new Date(isoStr);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    + ' ' + d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
}

function fmtPrice(n) {
  if (n == null) return '—';
  return '$' + Number(n).toFixed(2);
}

function badge(text, cls) {
  return h('span', { class: `badge ${cls}` }, text);
}

function statusBadge(status) {
  const map = { ACTIVE: 'badge-active', DRAFT: 'badge-draft', ARCHIVED: 'badge-used' };
  return badge(status || '—', map[status] || 'badge-draft');
}

function spinner() {
  return h('span', { class: 'spinner' });
}

function emptyState(icon, text) {
  return h('div', { class: 'empty-state' },
    h('div', { class: 'empty-state-icon' }, icon),
    h('div', { class: 'empty-state-text' }, text)
  );
}

function showToast(msg, type='info') {
  if (App._toastTimer) clearTimeout(App._toastTimer);
  App.toast = { msg, type };
  renderToast();
  App._toastTimer = setTimeout(() => { App.toast = null; renderToast(); }, 4000);
}

function renderToast() {
  let el = document.getElementById('toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    el.style.cssText = 'position:fixed;bottom:24px;right:24px;z-index:9999;min-width:260px;max-width:400px;';
    document.body.appendChild(el);
  }
  if (!App.toast) { el.innerHTML = ''; return; }
  const typeMap = { info: 'alert-info', success: 'alert-success', error: 'alert-error', warning: 'alert-warning' };
  el.innerHTML = `<div class="alert ${typeMap[App.toast.type] || 'alert-info'}" style="box-shadow:var(--shadow-lg)">${App.toast.msg}</div>`;
}

async function withLoading(btn, fn) {
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';
  try { return await fn(); }
  finally { btn.disabled = false; btn.innerHTML = orig; }
}

function parseJSON(str) {
  try { return JSON.parse(str); } catch { return null; }
}

// ── Router ────────────────────────────────────────────────────────────────────
function navigate(page) {
  if (!App.authed && page !== 'lock') { showToast('Please unlock the app first.', 'warning'); return; }
  App.page = page;
  render();
}

// ── Running-state polling ─────────────────────────────────────────────────────
async function pollRunning() {
  if (!App.authed) return;
  try {
    const res = await api.syncRunning();
    const was = App.running;
    App.running = res.running;
    if (was !== App.running) renderActivePageBanner();

    // Handle last_result — show it once then ack so it doesn't repeat
    const r = res.last_result;
    if (r && !App._lastResultAcked) {
      App._lastResultAcked = r.at;   // use timestamp as idempotency key
      // Only surface results that weren't already handled by an active runSync()
      // (runSync() clears App.running itself, so if App.running was null we
      //  know the page may have been on dashboard or user navigated away)
      if (!was) {
        // Synthesise an addLog call if the sync log panel exists
        const logEl = document.querySelector('#sync-activity-log');
        if (logEl) {
          const color = r.status === 'completed' ? 'var(--green)'
                      : r.status === 'cancelled' ? 'var(--orange)'
                      : 'var(--red)';
          const level = r.status === 'failed' ? 'ERROR'
                      : r.status === 'cancelled' ? 'WARN' : 'INFO';
          const detail = r.detail ? ` — ${r.detail}` : '';
          const counts = Object.entries(r.counts || {})
            .map(([k,v]) => `${k}: ${v}`).join(', ');
          const summary = counts ? ` (${counts})` : '';
          appendLogLine(logEl, `${r.label} ${r.status}${summary}${detail}`, level, color);
        }
        if (r.status === 'failed') {
          showToast(`${r.label} failed${r.detail ? ': ' + r.detail : ''}`, 'error');
        }
      }
      // Ack so backend clears it
      fetch('/api/sync/ack-result', { method: 'POST' }).catch(() => {});
    } else if (!r) {
      App._lastResultAcked = null;
    }
  } catch {}
}

// Append a log line to an existing log element (used by poll for out-of-band results)
function appendLogLine(el, msg, level='INFO', color='var(--text-secondary)') {
  const now = new Date();
  const date = now.toLocaleDateString('en-CA');
  const time = now.toLocaleTimeString('en-GB', { hour12: false });
  const ms   = String(now.getMilliseconds()).padStart(3, '0');
  const line = document.createElement('div');
  line.style.color = color;
  line.textContent = `${date} ${time},${ms} [${level}] ui — ${msg}`;
  if (el.textContent === 'Sync log will appear here…') el.textContent = '';
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

function startPolling() {
  if (App._pollTimer) return;
  App._pollTimer = setInterval(pollRunning, 2500);
  pollRunning();  // immediate first check
}

function stopPolling() {
  clearInterval(App._pollTimer);
  App._pollTimer = null;
}

// Refresh just the running banner without a full re-render
function renderActivePageBanner() {
  const banner = document.getElementById('running-banner');
  if (!banner) return;
  updateRunningBanner(banner);
}

function updateRunningBanner(el) {
  if (App.running) {
    el.style.display = '';
    el.querySelector('.banner-label').textContent = App.running;
  } else {
    el.style.display = 'none';
    el.querySelector('.banner-label').textContent = '';
  }
  // Enable/disable all sync-trigger buttons on the page
  document.querySelectorAll('.sync-trigger').forEach(b => {
    b.disabled = !!App.running;
  });
}

function makeSyncBanner() {
  const el = h('div', {
    id: 'running-banner',
    class: 'alert alert-info',
    style: 'display:none;margin-bottom:20px;align-items:center;gap:12px;',
  },
    h('span', { class: 'spinner', style: 'border-top-color:var(--blue);border-color:rgba(0,113,188,0.3);border-top-color:#60a8e0;flex-shrink:0;' }),
    h('span', { style: 'flex:1;' },
      'Sync in progress: ',
      h('span', { class: 'banner-label', style: 'font-weight:600;' }, App.running || ''),
    ),
    h('button', {
      class: 'btn btn-danger btn-sm',
      style: 'flex-shrink:0;',
      onClick: async (e) => {
        e.currentTarget.disabled = true;
        e.currentTarget.textContent = 'Cancelling…';
        try { await fetch('/api/sync/cancel', { method: 'POST' }); } catch {}
      },
    }, 'Cancel'),
  );
  updateRunningBanner(el);
  return el;
}

// ── Top-level render ──────────────────────────────────────────────────────────
function render() {
  const root = document.getElementById('root');
  root.innerHTML = '';
  if (!App.authed) { stopPolling(); root.appendChild(renderLockScreen()); return; }
  root.appendChild(renderShell());
  startPolling();
}

// ── Lock screen ───────────────────────────────────────────────────────────────
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
    h('div', { class: 'connect-form' },
      errMsg,
      pwInput,
      btn,
    ),
  );

  // inject shake keyframes once
  if (!document.getElementById('shake-style')) {
    const s = document.createElement('style');
    s.id = 'shake-style';
    s.textContent = '@keyframes shake{0%,100%{transform:translateX(0)}20%,60%{transform:translateX(-8px)}40%,80%{transform:translateX(8px)}}';
    document.head.appendChild(s);
  }

  return h('div', { class: 'connect-page' }, box);
}

// ── App shell (navbar + page) ─────────────────────────────────────────────────
function renderShell() {
  const pages = [
    { key: 'dashboard', label: 'Dashboard' },
    { key: 'webami',    label: 'Webami' },
    { key: 'shopify',   label: 'Shopify' },
    { key: 'sync',      label: 'Sync' },
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
    dashboard: renderDashboard,
    webami:    renderWebami,
    shopify:   renderShopify,
    sync:      renderSyncPage,
  };

  const pageEl = h('main', { class: 'page' });
  const renderer = pageMap[App.page] || renderDashboard;
  pageEl.appendChild(renderer());

  return h('div', { class: 'app-shell' }, navbar, pageEl);
}

// ── Dashboard ─────────────────────────────────────────────────────────────────
function renderDashboard() {
  const wrap = h('div', {});

  wrap.appendChild(h('div', { class: 'page-title' }, 'Dashboard'));
  wrap.appendChild(makeSyncBanner());

  // Stat cards row — loaded async
  const statsRow = h('div', { class: 'row', style: 'margin-bottom:24px;gap:16px;' });
  wrap.appendChild(statsRow);

  // Sync status cards
  const syncSection = h('div', {});
  wrap.appendChild(h('div', { class: 'section-label', style: 'margin-bottom:12px;' }, 'Last Sync'));
  wrap.appendChild(syncSection);

  async function loadStats() {
    // Quick product counts from search with empty query
    const [webamiP, shopifyP, webamiO] = await Promise.allSettled([
      api.webamiProducts(''),
      api.shopifyProducts(''),
      api.webamiOrders(''),
    ]);

    const wCount  = webamiP.status  === 'fulfilled' ? webamiP.value.length  : '?';
    const sCount  = shopifyP.status === 'fulfilled' ? shopifyP.value.length : '?';
    const oCount  = webamiO.status  === 'fulfilled' ? webamiO.value.length  : '?';

    statsRow.innerHTML = '';
    statsRow.appendChild(statCard('Webami Products', wCount, 'var(--blue)'));
    statsRow.appendChild(statCard('Shopify Products', sCount, 'var(--green)'));
    statsRow.appendChild(statCard('Webami Orders', oCount, 'var(--orange)'));
  }

  function statCard(label, value, color) {
    return h('div', { class: 'stat-card flex-1' },
      h('div', { class: 'stat-label' }, label),
      h('div', { class: 'stat-value', style: `color:${color}` }, String(value)),
    );
  }

  async function loadStatus() {
    try {
      const status = await api.syncStatus();
      App.syncStatus = status;
      syncSection.innerHTML = '';

      const keys = {
        webami_orders:   { label: 'Webami Orders',   icon: '📦' },
        webami_products: { label: 'Webami Products',  icon: '🎵' },
        webami_prices:   { label: 'Webami Prices',    icon: '💰' },
        shopify_products:{ label: 'Shopify Products', icon: '🛍️' },
      };

      for (const [key, meta] of Object.entries(keys)) {
        const s = status[key] || {};
        const card = h('div', { class: 'sync-card', style: 'margin-bottom:10px;' },
          h('div', { style: 'font-size:24px;' }, meta.icon),
          h('div', { class: 'sync-card-info' },
            h('div', { class: 'sync-card-title' }, meta.label),
            h('div', { class: 'sync-card-meta' },
              s.last_sync ? 'Last synced ' + fmt(s.last_sync) : 'Never synced'
            ),
          ),
          h('div', { class: `badge ${s.last_sync ? 'badge-active' : 'badge-draft'}` },
            s.last_sync ? 'Synced' : 'Pending'
          ),
        );
        syncSection.appendChild(card);
      }
    } catch (e) {
      syncSection.innerHTML = '<div class="alert alert-error">Could not load sync status</div>';
    }
  }

  loadStats();
  loadStatus();
  return wrap;
}

async function loadSyncStatus() {
  try { App.syncStatus = await api.syncStatus(); } catch {}
}

// ── Webami page ───────────────────────────────────────────────────────────────
function renderWebami() {
  const wrap = h('div', {});
  wrap.appendChild(h('div', { class: 'page-title' }, 'Webami'));

  // Sub-tabs: Products | Orders
  let subTab = 'products';
  const tabBar = h('div', { class: 'row center', style: 'margin-bottom:20px;gap:6px;' });
  const contentArea = h('div', {});
  wrap.appendChild(tabBar);
  wrap.appendChild(contentArea);

  function setTab(t) {
    subTab = t;
    tabBar.querySelectorAll('.nav-btn').forEach(b => b.classList.remove('active'));
    tabBar.querySelector(`[data-tab="${t}"]`).classList.add('active');
    if (t === 'products') renderWebamiProducts();
    else renderWebamiOrders();
  }

  tabBar.appendChild(h('button', { class: 'nav-btn active', 'data-tab': 'products', onClick: () => setTab('products') }, 'Products'));
  tabBar.appendChild(h('button', { class: 'nav-btn',        'data-tab': 'orders',   onClick: () => setTab('orders')   }, 'Orders'));

  // ── Products sub-view ──
  function renderWebamiProducts() {
    contentArea.innerHTML = '';
    const searchInput = h('input', { class: 'input', placeholder: 'Search album, artist, UPC…', style: 'max-width:320px;' });
    const tableWrap   = h('div', { class: 'table-wrap' });
    const toolbar     = h('div', { class: 'row center', style: 'margin-bottom:14px;gap:10px;' },
      searchInput,
    );
    contentArea.appendChild(toolbar);
    contentArea.appendChild(tableWrap);

    let debounce;
    searchInput.addEventListener('input', () => {
      clearTimeout(debounce);
      debounce = setTimeout(() => load(searchInput.value), 300);
    });

    async function load(q='') {
      tableWrap.innerHTML = '';
      tableWrap.appendChild(h('div', { class: 'empty-state' }, spinner(), h('span',{},'Loading…')));
      try {
        const rows = await api.webamiProducts(q);
        renderWebamiProductTable(tableWrap, rows);
      } catch(e) {
        tableWrap.innerHTML = `<div class="alert alert-error" style="margin:16px">${e.message}</div>`;
      }
    }
    load();
  }

  function renderWebamiProductTable(container, rows) {
    container.innerHTML = '';
    if (!rows.length) { container.appendChild(emptyState('🎵', 'No products found')); return; }
    const thead = h('thead', {},
      h('tr', {},
        h('th', {}, ''),
        h('th', {}, 'UPC'),
        h('th', {}, 'Album'),
        h('th', {}, 'Artist'),
        h('th', {}, 'Format'),
        h('th', {}, 'Cost'),
        h('th', {}, 'Last Scraped'),
      )
    );
    const tbody = h('tbody', {});
    for (const r of rows) {
      const images = parseJSON(r.image_urls);
      const thumb = images && images[0]
        ? h('img', { class: 'product-thumb', src: images[0], alt: '' })
        : h('div', { class: 'product-thumb-placeholder' }, '♪');
      tbody.appendChild(h('tr', {},
        h('td', {}, thumb),
        h('td', { class: 'mono', style: 'font-size:12px;color:var(--text-secondary)' }, r.upc || '—'),
        h('td', {}, r.album || h('span', { style: 'color:var(--text-muted)' }, '—')),
        h('td', {}, r.artist || h('span', { style: 'color:var(--text-muted)' }, '—')),
        h('td', {}, r.format ? badge(r.format, 'badge-new') : '—'),
        h('td', { style: 'color:var(--green);font-weight:600;' }, fmtPrice(r.cost)),
        h('td', { style: 'color:var(--text-muted);font-size:12px;' }, fmt(r.last_scraped)),
      ));
    }
    container.appendChild(h('table', {}, thead, tbody));
  }

  // ── Orders sub-view ──
  function renderWebamiOrders() {
    contentArea.innerHTML = '';
    const searchInput = h('input', { class: 'input', placeholder: 'Search by UPC…', style: 'max-width:320px;' });
    const tableWrap   = h('div', { class: 'table-wrap' });
    contentArea.appendChild(h('div', { class: 'row center', style: 'margin-bottom:14px;' }, searchInput));
    contentArea.appendChild(tableWrap);

    let debounce;
    searchInput.addEventListener('input', () => {
      clearTimeout(debounce);
      debounce = setTimeout(() => load(searchInput.value), 300);
    });

    async function load(q='') {
      tableWrap.innerHTML = '';
      tableWrap.appendChild(h('div', { class: 'empty-state' }, spinner(), h('span',{},'Loading…')));
      try {
        const rows = await api.webamiOrders(q);
        renderOrderTable(tableWrap, rows);
      } catch(e) {
        tableWrap.innerHTML = `<div class="alert alert-error" style="margin:16px">${e.message}</div>`;
      }
    }
    load();
  }

  function renderOrderTable(container, rows) {
    container.innerHTML = '';
    if (!rows.length) { container.appendChild(emptyState('📦', 'No orders found')); return; }
    const thead = h('thead', {},
      h('tr', {},
        h('th', {}, 'GUID'),
        h('th', {}, 'Order Date'),
        h('th', {}, 'Synced'),
        h('th', {}, 'Items'),
      )
    );
    const tbody = h('tbody', {});
    for (const r of rows) {
      const upcs = parseJSON(r.raw_upcs) || [];
      tbody.appendChild(h('tr', {},
        h('td', { class: 'mono', style: 'font-size:11px;color:var(--text-muted);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;' }, r.guid),
        h('td', {}, fmt(r.order_date)),
        h('td', { style: 'color:var(--text-muted);font-size:12px;' }, fmt(r.synced_at)),
        h('td', {}, h('span', { class: 'badge badge-new' }, String(upcs.length) + ' UPCs')),
      ));
    }
    container.appendChild(h('table', {}, thead, tbody));
  }

  // Init
  renderWebamiProducts();
  return wrap;
}

// ── Shopify page ──────────────────────────────────────────────────────────────
function renderShopify() {
  const wrap = h('div', {});
  wrap.appendChild(h('div', { class: 'page-title' }, 'Shopify Products'));

  const selectedIds = new Set();
  let allRows = [];

  // Toolbar
  const searchInput  = h('input', { class: 'input', placeholder: 'Search title, vendor, UPC…', style: 'max-width:280px;' });
  const bulkDeleteBtn = h('button', { class: 'btn btn-danger btn-sm', style: 'display:none;', onClick: doBulkDelete }, 'Delete selected');
  const bulkGapBtn    = h('button', { class: 'btn btn-warning btn-sm', style: 'display:none;', onClick: doBulkGap   }, 'Fill gaps');
  const selCount      = h('span',   { style: 'font-size:12px;color:var(--text-muted);display:none;' }, '');
  const toolbar = h('div', { class: 'row center', style: 'margin-bottom:14px;gap:10px;flex-wrap:wrap;' },
    searchInput, selCount, bulkGapBtn, bulkDeleteBtn,
  );
  wrap.appendChild(toolbar);

  const tableWrap = h('div', { class: 'table-wrap' });
  wrap.appendChild(tableWrap);

  function updateBulkControls() {
    const n = selectedIds.size;
    const show = n > 0;
    bulkDeleteBtn.style.display = show ? '' : 'none';
    bulkGapBtn.style.display    = show ? '' : 'none';
    selCount.style.display      = show ? '' : 'none';
    selCount.textContent        = `${n} selected`;
  }

  async function doBulkDelete() {
    if (!selectedIds.size) return;
    if (!confirm(`Delete ${selectedIds.size} product(s) from Shopify? This cannot be undone.`)) return;
    await withLoading(bulkDeleteBtn, async () => {
      try {
        const res = await api.bulkDelete([...selectedIds]);
        showToast(`Deleted ${res.deleted?.length || 0} product(s)`, 'success');
        selectedIds.clear();
        load(searchInput.value);
      } catch(e) { showToast(e.message, 'error'); }
    });
  }

  async function doBulkGap() {
    if (!selectedIds.size) return;
    await withLoading(bulkGapBtn, async () => {
      try {
        const res = await api.fillGaps([...selectedIds]);
        showToast(`Filled gaps for ${res.filled || 0} product(s)`, 'success');
      } catch(e) { showToast(e.message, 'error'); }
    });
  }

  let debounce;
  searchInput.addEventListener('input', () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => load(searchInput.value), 300);
  });

  async function load(q='') {
    tableWrap.innerHTML = '';
    tableWrap.appendChild(h('div', { class: 'empty-state' }, spinner(), h('span',{},'Loading…')));
    try {
      allRows = await api.shopifyProducts(q);
      renderTable(allRows);
    } catch(e) {
      tableWrap.innerHTML = `<div class="alert alert-error" style="margin:16px">${e.message}</div>`;
    }
  }

  function renderTable(rows) {
    tableWrap.innerHTML = '';
    if (!rows.length) { tableWrap.appendChild(emptyState('🛍️', 'No products found')); return; }

    const allCb = h('input', { type: 'checkbox', title: 'Select all' });
    allCb.addEventListener('change', () => {
      rows.forEach(r => {
        if (allCb.checked) selectedIds.add(r.product_id);
        else selectedIds.delete(r.product_id);
      });
      tableWrap.querySelectorAll('tbody input[type=checkbox]').forEach(cb => cb.checked = allCb.checked);
      updateBulkControls();
    });

    const thead = h('thead', {},
      h('tr', {},
        h('th', { style: 'width:36px;' }, allCb),
        h('th', {}, ''),
        h('th', {}, 'Title'),
        h('th', {}, 'Vendor'),
        h('th', {}, 'UPC'),
        h('th', {}, 'Status'),
        h('th', {}, 'Price'),
        h('th', {}, 'Updated'),
        h('th', {}, ''),
      )
    );
    const tbody = h('tbody', {});

    for (const r of rows) {
      const cb = h('input', { type: 'checkbox' });
      cb.checked = selectedIds.has(r.product_id);
      cb.addEventListener('change', () => {
        if (cb.checked) selectedIds.add(r.product_id);
        else selectedIds.delete(r.product_id);
        updateBulkControls();
      });

      const images = parseJSON(r.image_urls);
      const thumb = images && images[0]
        ? h('img', { class: 'product-thumb', src: images[0], alt: '' })
        : h('div', { class: 'product-thumb-placeholder' }, '♪');

      const variants  = parseJSON(r.variants) || [];
      const price     = variants[0]?.price ? fmtPrice(variants[0].price) : '—';

      const editBtn = h('button', { class: 'btn btn-ghost btn-sm', onClick: () => openEditModal(r) }, 'Edit');
      const delBtn  = h('button', { class: 'btn btn-danger btn-sm', onClick: () => doDelete(r.product_id, r.title) }, 'Del');

      tbody.appendChild(h('tr', {},
        h('td', { class: 'checkbox-cell' }, cb),
        h('td', {}, thumb),
        h('td', { style: 'max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500;' }, r.title || '—'),
        h('td', { style: 'color:var(--text-secondary);' }, r.vendor || '—'),
        h('td', { class: 'mono', style: 'font-size:11px;color:var(--text-muted);' }, r.upc || '—'),
        h('td', {}, statusBadge(r.status)),
        h('td', { style: 'color:var(--green);font-weight:600;' }, price),
        h('td', { style: 'color:var(--text-muted);font-size:12px;' }, fmt(r.updated_at)),
        h('td', { class: 'row center', style: 'gap:6px;' }, editBtn, delBtn),
      ));
    }

    tableWrap.appendChild(h('table', {}, thead, tbody));
  }

  async function doDelete(id, title) {
    if (!confirm(`Delete "${title || id}" from Shopify? This cannot be undone.`)) return;
    try {
      await api.deleteProduct(id);
      showToast('Product deleted', 'success');
      load(searchInput.value);
    } catch(e) { showToast(e.message, 'error'); }
  }

  function openEditModal(product) {
    const variants = parseJSON(product.variants) || [];
    const price = variants[0]?.price || '';

    const titleInput  = h('input', { class: 'input', value: product.title || '' });
    const vendorInput = h('input', { class: 'input', value: product.vendor || '' });
    const priceInput  = h('input', { class: 'input', type: 'number', step: '0.01', value: price });
    const statusSel   = h('select', { class: 'select' });
    ['ACTIVE','DRAFT','ARCHIVED'].forEach(s => {
      const opt = document.createElement('option');
      opt.value = s; opt.textContent = s;
      if (s === product.status) opt.selected = true;
      statusSel.appendChild(opt);
    });

    const saveBtn   = h('button', { class: 'btn btn-primary', onClick: doSave }, 'Save');
    const cancelBtn = h('button', { class: 'btn btn-ghost',   onClick: closeModal }, 'Cancel');

    async function doSave() {
      await withLoading(saveBtn, async () => {
        try {
          const updatedVariants = variants.map((v, i) => i === 0 ? { ...v, price: priceInput.value } : v);
          await api.updateProduct(product.product_id, {
            title:    titleInput.value,
            vendor:   vendorInput.value,
            status:   statusSel.value,
            variants: updatedVariants,
          });
          showToast('Product updated', 'success');
          closeModal();
          load(searchInput.value);
        } catch(e) { showToast(e.message, 'error'); }
      });
    }

    const modal = renderModal('Edit Product',
      h('div', { class: 'col', style: 'gap:14px;' },
        h('div', { class: 'input-group' }, h('div', { class: 'input-label' }, 'Title'),  titleInput),
        h('div', { class: 'input-group' }, h('div', { class: 'input-label' }, 'Vendor'), vendorInput),
        h('div', { class: 'input-group' }, h('div', { class: 'input-label' }, 'Price'),  priceInput),
        h('div', { class: 'input-group' }, h('div', { class: 'input-label' }, 'Status'), statusSel),
      ),
      h('div', { class: 'row', style: 'gap:10px;justify-content:flex-end;margin-top:20px;' }, cancelBtn, saveBtn),
    );
    document.body.appendChild(modal);
  }

  load();
  return wrap;
}

// ── Sync page ─────────────────────────────────────────────────────────────────
function renderSyncPage() {
  const wrap = h('div', {});
  wrap.appendChild(h('div', { class: 'page-title' }, 'Sync'));
  wrap.appendChild(makeSyncBanner());

  // ── Activity log ──
  const log = h('div', {
    id:    'sync-activity-log',
    style: 'background:var(--bg-surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px;font-family:"DM Mono",monospace;font-size:12px;color:var(--text-secondary);min-height:100px;max-height:220px;overflow-y:auto;',
  });
  log.textContent = 'Sync log will appear here…';

  function addLog(msg, level='INFO', color='var(--text-secondary)') {
    const now = new Date();
    const date = now.toLocaleDateString('en-CA');   // YYYY-MM-DD
    const time = now.toLocaleTimeString('en-GB', { hour12: false }); // HH:MM:SS
    const ms   = String(now.getMilliseconds()).padStart(3, '0');
    const ts   = `${date} ${time},${ms}`;
    const line = document.createElement('div');
    line.style.color = color;
    line.textContent = `${ts} [${level}] ui — ${msg}`;
    if (log.textContent === 'Sync log will appear here…') log.textContent = '';
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  }

  // ── Running state ──
  let activeAbort = null;   // AbortController for the current fetch
  let isRunning   = false;

  const cancelBtn = h('button', {
    class: 'btn btn-danger btn-sm',
    style: 'display:none;',
    onClick: async () => {
      if (!isRunning) return;
      addLog('Cancelling — finishing current item…', 'WARN', 'var(--orange)');
      cancelBtn.disabled = true;
      cancelBtn.textContent = 'Cancelling…';
      // Tell the backend to stop, and abort the pending fetch
      if (activeAbort) activeAbort.abort();
      try { await fetch('/api/sync/cancel', { method: 'POST' }); } catch {}
    },
  }, 'Cancel');

  function setRunning(running) {
    isRunning = running;
    // The banner in the sync page is the shared one — update it directly
    const banner = wrap.querySelector('#running-banner');
    if (banner) updateRunningBanner(banner);
    // Also update any banner on other pages (e.g. dashboard open in same tab)
    renderActivePageBanner();
  }

  async function runSync(label, apiFn, btn) {
    if (isRunning || App.running) return;
    activeAbort = new AbortController();
    App.running = label;
    setRunning(true);
    btn.innerHTML = '<span class="spinner"></span>';
    addLog(`${label} started…`, 'INFO', 'var(--blue)');
    try {
      const res = await apiFn(activeAbort.signal);
      if (res.cancelled) {
        addLog(`${label} cancelled — ${fmtResult(res)}`, 'WARN', 'var(--orange)');
        showToast(`${label} cancelled`, 'warning');
      } else {
        addLog(`${label} complete — ${fmtResult(res)}`, 'INFO', 'var(--green)');
        showToast(`${label} complete`, 'success');
      }
    } catch(e) {
      if (e.name === 'AbortError') {
        addLog(`${label} — request aborted`, 'WARN', 'var(--orange)');
      } else {
        addLog(`${label} failed — ${e.message}`, 'ERROR', 'var(--red)');
        showToast(`${label} failed: ${e.message}`, 'error');
      }
    } finally {
      btn.textContent = btn.dataset.label;
      activeAbort = null;
      App.running = null;
      setRunning(false);
    }
  }

  function fmtResult(res) {
    // Turn the result dict into a readable summary instead of raw JSON
    const parts = [];
    if (res.orders_processed != null) parts.push(`${res.orders_processed}${res.orders_total != null ? '/'+res.orders_total : ''} orders`);
    if (res.products_scraped  != null) parts.push(`${res.products_scraped} products scraped`);
    if (res.products_synced   != null) parts.push(`${res.products_synced} products synced`);
    if (res.prices_updated    != null) parts.push(`${res.prices_updated}${res.prices_total != null ? '/'+res.prices_total : ''} prices`);
    if (res.filled            != null) parts.push(`${res.filled} filled`);
    if (res.updated           != null) parts.push(`${res.updated} price(s) pushed`);
    return parts.length ? parts.join(', ') : JSON.stringify(res);
  }

  // ── Sync card builder ──
  // Each card shows title, two description lines (incremental vs full), and buttons.
  function syncCard(opts) {
    // opts: { title, incDesc, fullDesc, incBtn?, fullBtn?, singleBtn? }
    const descCol = h('div', { class: 'sync-card-info' },
      h('div', { class: 'sync-card-title' }, opts.title),
    );

    if (opts.incBtn && opts.fullBtn) {
      // Two-mode card: show both descriptions inline with their button context
      const incRow = h('div', { style: 'display:flex;align-items:flex-start;gap:12px;margin-top:8px;' },
        h('div', { style: 'flex:1;' },
          h('div', { style: 'font-size:12px;font-weight:600;color:var(--text-secondary);margin-bottom:2px;' }, 'Incremental'),
          h('div', { class: 'sync-card-meta' }, opts.incDesc),
        ),
      );
      const fullRow = h('div', { style: 'display:flex;align-items:flex-start;gap:12px;margin-top:6px;' },
        h('div', { style: 'flex:1;' },
          h('div', { style: 'font-size:12px;font-weight:600;color:var(--text-secondary);margin-bottom:2px;' }, 'Full'),
          h('div', { class: 'sync-card-meta' }, opts.fullDesc),
        ),
      );
      descCol.appendChild(incRow);
      descCol.appendChild(fullRow);

      return h('div', { class: 'sync-card', style: 'margin-bottom:10px;align-items:flex-start;flex-wrap:wrap;gap:16px;' },
        descCol,
        h('div', { class: 'col', style: 'gap:6px;flex-shrink:0;align-items:stretch;min-width:120px;' },
          opts.incBtn,
          opts.fullBtn,
        ),
      );
    } else {
      // Single-mode card
      descCol.appendChild(h('div', { class: 'sync-card-meta', style: 'margin-top:4px;' }, opts.incDesc || opts.fullDesc));
      return h('div', { class: 'sync-card', style: 'margin-bottom:10px;' },
        descCol,
        h('div', { class: 'row center', style: 'gap:8px;flex-shrink:0;' }, opts.singleBtn),
      );
    }
  }

  function makeBtn(label, cls, onClick) {
    const btn = h('button', {
      class: `btn ${cls} btn-sm sync-trigger`,
      'data-label': label,
      onClick,
    }, label);
    return btn;
  }

  // ── Webami section ──
  wrap.appendChild(h('div', { class: 'section-label', style: 'margin-bottom:12px;margin-top:8px;' }, 'Webami'));

  const woIncBtn  = makeBtn('Incremental', 'btn-ghost',   () => runSync('Webami orders (incremental)', api.syncWebamiOrdersIncremental, woIncBtn));
  const woFullBtn = makeBtn('Full sync',   'btn-primary', () => runSync('Webami orders (full)',        api.syncWebamiOrdersFull,        woFullBtn));
  wrap.appendChild(syncCard({
    title:   'Orders',
    incDesc: 'Checks only the most recent order pages for anything new since last sync. Fast — usually a few seconds.',
    fullDesc:'Paginates through every order ever placed and scrapes product pages for any UPCs not yet in the local database. Use this on first run or if you suspect gaps.',
    incBtn:  woIncBtn,
    fullBtn: woFullBtn,
  }));

  const wpFullBtn = makeBtn('Full sync', 'btn-primary', () => runSync('Webami products (full)', api.syncWebamiProductsFull, wpFullBtn));
  wrap.appendChild(syncCard({
    title:   'Products',
    fullDesc:'Re-scrapes every known product page to refresh album, artist, image, weight, and format. Slow — one HTTP request per product. Only needed if product metadata has changed on Webami.',
    singleBtn: wpFullBtn,
  }));

  const wPriceBtn = makeBtn('Sync prices', 'btn-warning', () => runSync('Webami prices', api.syncWebamiPrices, wPriceBtn));
  wrap.appendChild(syncCard({
    title:   'Prices',
    fullDesc:'Hits the fast Webami price endpoint for every known UPC to refresh cost data. Much faster than a full product sync — no page scraping involved.',
    singleBtn: wPriceBtn,
  }));

  // ── Shopify section ──
  wrap.appendChild(h('div', { class: 'section-label', style: 'margin-bottom:12px;margin-top:20px;' }, 'Shopify'));

  const sIncBtn  = makeBtn('Incremental', 'btn-ghost',   () => runSync('Shopify (incremental)', api.syncShopifyIncremental, sIncBtn));
  const sFullBtn = makeBtn('Full sync',   'btn-primary', () => runSync('Shopify (full)',        api.syncShopifyFull,        sFullBtn));
  wrap.appendChild(syncCard({
    title:   'Products',
    incDesc: 'Fetches only products updated in Shopify since the last sync timestamp. Fast — usually just a handful of products.',
    fullDesc:'Pulls every product from Shopify including all variants and metafields, replacing local data. Use this if the local database is out of sync or on first run.',
    incBtn:  sIncBtn,
    fullBtn: sFullBtn,
  }));

  // ── Bridge section ──
  wrap.appendChild(h('div', { class: 'section-label', style: 'margin-bottom:12px;margin-top:20px;' }, 'Bridge'));

  const bPriceBtn = makeBtn('Push prices', 'btn-warning', () => runSync('Price bridge', () => api.bridgePrices(), bPriceBtn));
  wrap.appendChild(syncCard({
    title:   'Price bridge',
    fullDesc:'Compares every Webami cost against the current Shopify variant price. Pushes an update to Shopify for any product where the price has drifted. Run after a Webami price sync.',
    singleBtn: bPriceBtn,
  }));

  const bGapBtn = makeBtn('Fill gaps', 'btn-ghost', () => runSync('Gap fill', () => api.fillGaps(null), bGapBtn));
  wrap.appendChild(syncCard({
    title:   'Field gap filler',
    fullDesc:'Scans all Shopify products for missing images, tags, or product categories and fills them in using the matching Webami product data.',
    singleBtn: bGapBtn,
  }));

  // ── Log + cancel row ──
  wrap.appendChild(
    h('div', { class: 'row center', style: 'margin-top:24px;margin-bottom:10px;' },
      h('div', { class: 'section-label', style: 'flex:1;margin:0;border:none;padding:0;' }, 'Activity Log'),
      cancelBtn,
    )
  );
  wrap.appendChild(log);

  return wrap;
}

// ── Modal helper ──────────────────────────────────────────────────────────────
function renderModal(title, ...bodyChildren) {
  const overlay = h('div', {
    style: 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:1000;display:flex;align-items:center;justify-content:center;animation:fadeIn 0.15s ease;',
    onClick: e => { if (e.target === overlay) closeModal(); },
  });

  const modal = h('div', {
    style: 'background:var(--bg-card);border:1px solid var(--border-light);border-radius:var(--radius-xl);padding:32px;width:480px;max-width:95vw;max-height:85vh;overflow-y:auto;box-shadow:var(--shadow-lg);',
  },
    h('h3', { style: 'margin-bottom:20px;font-size:20px;' }, title),
    ...bodyChildren,
  );

  overlay.appendChild(modal);
  overlay.id = 'modal-overlay';
  return overlay;
}

function closeModal() {
  const m = document.getElementById('modal-overlay');
  if (m) m.remove();
}

// ── Boot ──────────────────────────────────────────────────────────────────────
render();