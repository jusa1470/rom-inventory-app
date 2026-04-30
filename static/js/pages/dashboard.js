import { api } from '../api.js';
import { h, fmt, fmtPrice, badge, spinner, parseJSON } from '../utils.js';
import { makeSyncBanner, App } from '../core.js';

export function renderDashboard() {
  const wrap = h('div', {});
  wrap.appendChild(h('div', { class: 'page-title' }, 'Dashboard'));
  wrap.appendChild(makeSyncBanner());

  const statsRow = h('div', { class: 'row', style: 'margin-bottom:24px;gap:16px;' });
  wrap.appendChild(statsRow);

  const syncSection = h('div', {});
  wrap.appendChild(h('div', { class: 'section-label', style: 'margin-bottom:12px;' }, 'Last Sync'));
  wrap.appendChild(syncSection);

  async function loadStats() {
    const [webamiP, shopifyP, webamiO] = await Promise.allSettled([
      api.webamiProducts(''),
      api.shopifyProducts(''),
      api.webamiOrders(''),
    ]);
    const wCount = webamiP.status  === 'fulfilled' ? webamiP.value.length  : '?';
    const sCount = shopifyP.status === 'fulfilled' ? shopifyP.value.length : '?';
    const oCount = webamiO.status  === 'fulfilled' ? webamiO.value.length  : '?';
    statsRow.innerHTML = '';
    statsRow.appendChild(statCard('Webami Orders',    oCount, 'var(--orange)'));
    statsRow.appendChild(statCard('Webami Products',  wCount, 'var(--blue)'));
    statsRow.appendChild(statCard('Shopify Products', sCount, 'var(--green)'));
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
        webami_orders:    { label: 'Webami Orders',   icon: '📦' },
        webami_products:  { label: 'Webami Products', icon: '🎵' },
        shopify_products: { label: 'Shopify Products',icon: '🛍️' },
        webami_prices:    { label: 'Webami Prices',   icon: '💰' },
      };
      for (const [key, meta] of Object.entries(keys)) {
        const s = status[key] || {};
        syncSection.appendChild(h('div', { class: 'sync-card', style: 'margin-bottom:10px;' },
          h('div', { style: 'font-size:24px;' }, meta.icon),
          h('div', { class: 'sync-card-info' },
            h('div', { class: 'sync-card-title' }, meta.label),
            h('div', { class: 'sync-card-meta' }, s.last_sync ? 'Last synced ' + fmt(s.last_sync) : 'Never synced'),
          ),
          h('div', { class: `badge ${s.last_sync ? 'badge-active' : 'badge-draft'}` }, s.last_sync ? 'Synced' : 'Not synced'),
        ));
      }
    } catch {
      syncSection.innerHTML = '<div class="alert alert-error">Could not load sync status</div>';
    }
  }

  loadStats();
  loadStatus();
  return wrap;
}