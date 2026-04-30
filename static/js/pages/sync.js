import { api } from '../api.js';
import { h, showToast } from '../utils.js';
import { makeSyncBanner, updateRunningBanner, renderActivePageBanner, App } from '../core.js';

export function renderSync() {
  const wrap = h('div', {});
  wrap.appendChild(h('div', { class: 'page-title' }, 'Sync'));
  wrap.appendChild(makeSyncBanner());

  const log = h('div', {
    id: 'sync-activity-log',
    style: 'background:var(--bg-surface);border:1px solid var(--border);border-radius:var(--radius);padding:14px;font-family:"DM Mono",monospace;font-size:12px;color:var(--text-secondary);min-height:100px;max-height:220px;overflow-y:auto;',
  });
  log.textContent = 'Sync log will appear here…';

  function addLog(msg, level='INFO', color='var(--text-secondary)') {
    const now = new Date();
    const ts  = `${now.toLocaleDateString('en-CA')} ${now.toLocaleTimeString('en-GB', { hour12: false })},${String(now.getMilliseconds()).padStart(3,'0')}`;
    const line = document.createElement('div');
    line.style.color = color;
    line.textContent = `${ts} [${level}] ui — ${msg}`;
    if (log.textContent === 'Sync log will appear here…') log.textContent = '';
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
  }

  let activeAbort = null;
  let isRunning   = false;

  const cancelBtn = h('button', {
    class: 'btn btn-danger btn-sm',
    style: 'display:none;',
    onClick: async () => {
      if (!isRunning) return;
      addLog('Cancelling — finishing current item…', 'WARN', 'var(--orange)');
      cancelBtn.disabled = true;
      cancelBtn.textContent = 'Cancelling…';
      if (activeAbort) activeAbort.abort();
      try { await fetch('/api/sync/cancel', { method: 'POST' }); } catch {}
    },
  }, 'Cancel');

  function setRunning(running) {
    isRunning = running;
    const banner = wrap.querySelector('#running-banner');
    if (banner) updateRunningBanner(banner);
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
        addLog(`${label} cancelled — ${formatResult(res)}`, 'WARN', 'var(--orange)');
        showToast(`${label} cancelled`, 'warning');
      } else {
        addLog(`${label} complete — ${formatResult(res)}`, 'INFO', 'var(--green)');
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

  function formatResult(res) {
    const parts = [];
    if (res.orders_processed != null) parts.push(`${res.orders_processed}${res.orders_total != null ? '/'+res.orders_total : ''} orders`);
    if (res.products_scraped  != null) parts.push(`${res.products_scraped} products scraped`);
    if (res.products_synced   != null) parts.push(`${res.products_synced} products synced`);
    if (res.prices_updated    != null) parts.push(`${res.prices_updated}${res.prices_total != null ? '/'+res.prices_total : ''} prices`);
    if (res.filled            != null) parts.push(`${res.filled} filled`);
    if (res.updated           != null) parts.push(`${res.updated} price(s) pushed`);
    return parts.length ? parts.join(', ') : JSON.stringify(res);
  }

  function syncCard(opts) {
    const descCol = h('div', { class: 'sync-card-info' }, h('div', { class: 'sync-card-title' }, opts.title));
    if (opts.incBtn && opts.fullBtn) {
      descCol.appendChild(h('div', { style: 'display:flex;align-items:flex-start;gap:12px;margin-top:8px;' },
        h('div', { style: 'flex:1;' },
          h('div', { style: 'font-size:12px;font-weight:600;color:var(--text-secondary);margin-bottom:2px;' }, 'Recent Only'),
          h('div', { class: 'sync-card-meta' }, opts.incDesc),
        ),
      ));
      descCol.appendChild(h('div', { style: 'display:flex;align-items:flex-start;gap:12px;margin-top:6px;' },
        h('div', { style: 'flex:1;' },
          h('div', { style: 'font-size:12px;font-weight:600;color:var(--text-secondary);margin-bottom:2px;' }, 'Full'),
          h('div', { class: 'sync-card-meta' }, opts.fullDesc),
        ),
      ));
      return h('div', { class: 'sync-card', style: 'margin-bottom:10px;align-items:flex-start;flex-wrap:wrap;gap:16px;' },
        descCol,
        h('div', { class: 'col', style: 'gap:6px;flex-shrink:0;align-items:stretch;min-width:120px;' }, opts.incBtn, opts.fullBtn),
      );
    } else {
      descCol.appendChild(h('div', { class: 'sync-card-meta', style: 'margin-top:4px;' }, opts.incDesc || opts.fullDesc));
      return h('div', { class: 'sync-card', style: 'margin-bottom:10px;' },
        descCol,
        h('div', { class: 'row center', style: 'gap:8px;flex-shrink:0;' }, opts.singleBtn),
      );
    }
  }

  function makeBtn(label, cls, onClick) {
    return h('button', { class: `btn ${cls} btn-sm sync-trigger`, 'data-label': label, onClick }, label);
  }

  // Webami
  wrap.appendChild(h('div', { class: 'section-label', style: 'margin-bottom:12px;margin-top:8px;' }, 'Webami'));
  const woIncBtn  = makeBtn('Recent Only', 'btn-ghost',   () => runSync('Webami orders (recent)', api.syncWebamiOrdersRecent, woIncBtn));
  const woFullBtn = makeBtn('Full sync',   'btn-primary', () => runSync('Webami orders (full)',        api.syncWebamiOrdersFull,        woFullBtn));
  wrap.appendChild(syncCard({ title: 'Orders', incDesc: 'Checks only the most recent order pages for anything new since last sync.', fullDesc: 'Paginates through every order ever placed. Use on first run or if you suspect gaps.', incBtn: woIncBtn, fullBtn: woFullBtn }));

  const wpFullBtn = makeBtn('Full sync', 'btn-primary', () => runSync('Webami products (full)', api.syncWebamiProductsFull, wpFullBtn));
  wrap.appendChild(syncCard({ title: 'Products', fullDesc: 'Re-scrapes every known product page to refresh metadata. Slow — one request per product.', singleBtn: wpFullBtn }));

  const wPriceBtn = makeBtn('Sync prices', 'btn-warning', () => runSync('Webami prices', api.syncWebamiPrices, wPriceBtn));
  wrap.appendChild(syncCard({ title: 'Prices', fullDesc: 'Hits the fast Webami price endpoint for every known UPC. No page scraping involved.', singleBtn: wPriceBtn }));

  // Shopify
  wrap.appendChild(h('div', { class: 'section-label', style: 'margin-bottom:12px;margin-top:20px;' }, 'Shopify'));
  const sIncBtn  = makeBtn('Recent', 'btn-ghost',   () => runSync('Shopify (recent)', api.syncShopifyRecent, sIncBtn));
  const sFullBtn = makeBtn('Full sync',   'btn-primary', () => runSync('Shopify (full)',        api.syncShopifyFull,        sFullBtn));
  wrap.appendChild(syncCard({ title: 'Products', incDesc: 'Fetches only products updated since the last sync timestamp.', fullDesc: 'Pulls every product from Shopify. Use on first run or if local DB is out of sync.', incBtn: sIncBtn, fullBtn: sFullBtn }));

  // Bridge
  wrap.appendChild(h('div', { class: 'section-label', style: 'margin-bottom:12px;margin-top:20px;' }, 'Bridge'));
  const bPriceBtn = makeBtn('Push prices', 'btn-warning', () => runSync('Price bridge', () => api.bridgePrices(), bPriceBtn));
  wrap.appendChild(syncCard({ title: 'Price bridge', fullDesc: 'Compares every Webami cost against Shopify variant price and pushes updates for any drift.', singleBtn: bPriceBtn }));

  const bGapBtn = makeBtn('Fill gaps', 'btn-ghost', () => runSync('Gap fill', () => api.fillGaps(null), bGapBtn));
  wrap.appendChild(syncCard({ title: 'Field gap filler', fullDesc: 'Scans Shopify products for missing images, tags, or categories and fills them from Webami data.', singleBtn: bGapBtn }));

  // Log
  wrap.appendChild(h('div', { class: 'row center', style: 'margin-top:24px;margin-bottom:10px;' },
    h('div', { class: 'section-label', style: 'flex:1;margin:0;border:none;padding:0;' }, 'Activity Log'),
    cancelBtn,
  ));
  wrap.appendChild(log);

  return wrap;
}