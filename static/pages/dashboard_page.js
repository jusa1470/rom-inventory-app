import { API } from '../api.js';
import { Toast } from '../components/toast.js';
import { Fmt, esc } from '../util.js';

const POLL_MS = 1000;
const EXPORT_RE = /preparing the export/i;
const LOG_BADGES = { done: 'badge-new', partial: 'badge-used', cancelled: 'badge-draft', error: 'badge-error' };
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

const SYNCS = [
  { key: 'shopify', name: 'Shopify Sync', url: '/api/sync/shopify', unit: 'products', full: true,
    meta: 'Pull products, variants, and variant images from Shopify' },
  { key: 'webami', name: 'WebAMI Sync', url: '/api/sync/webami', unit: 'orders',
    meta: 'Pull new WebAMI orders and order items' },
  { key: 'webami-products', name: 'WebAMI Products', url: '/api/sync/webami-products',
    unit: 'order items', hidden: true },
];

export class DashboardPage {
  constructor() {
    this._jobs = {};
    this._starts = {};
    this._destroyed = false;
  }

  destroy() {
    this._destroyed = true;
  }

  async render(container) {
    this.c = container;
    container.innerHTML = `
      <div class="page">
        <div class="page-title">Dashboard</div>
        <div class="row" style="margin-bottom:20px">
          <div class="stat-card"><div class="stat-label">Products synced</div>
            <div class="stat-value" id="stat-products">—</div></div>
          <div class="stat-card"><div class="stat-label">Last Shopify sync</div>
            <div class="stat-value small" id="stat-last-sync">—</div></div>
          <div class="stat-card"><div class="stat-label">WebAMI orders</div>
            <div class="stat-value" id="stat-orders">—</div></div>
          <div class="stat-card"><div class="stat-label">WebAMI order items</div>
            <div class="stat-value" id="stat-items">—</div></div>
          <div class="stat-card"><div class="stat-label">WebAMI products</div>
            <div class="stat-value" id="stat-wproducts">—</div></div>
          <div class="stat-card"><div class="stat-label">Last WebAMI sync</div>
            <div class="stat-value small" id="stat-last-webami">—</div></div>
        </div>

        ${SYNCS.filter(s => !s.hidden).map(s => `
          <div class="sync-card" style="margin-bottom:12px">
            <div class="sync-card-info">
              <div class="sync-card-title">${s.name}</div>
              <div class="sync-card-meta">${s.meta}</div>
              <div id="progress-${s.key}" style="display:none">
                <div class="progress-bar-wrap"><div class="progress-bar indeterminate" id="bar-${s.key}"></div></div>
                <div class="progress-msg" id="msg-${s.key}">Starting…</div>
              </div>
            </div>
            <div class="sync-actions">
              <button class="btn btn-primary" id="btn-${s.key}">Sync</button>
              ${s.key === 'webami' ? '<button class="btn btn-ghost" id="btn-webami-products">Fetch products</button>' : ''}
              ${s.full ? `<button class="btn btn-ghost" id="btn-full-${s.key}">Full sync</button>` : ''}
              <button class="btn btn-ghost btn-sm" id="btn-cancel-${s.key}" style="display:none">Cancel</button>
            </div>
          </div>`).join('')}

        <div class="section-label">Recent activity</div>
        <div id="log-list"></div>
      </div>`;

    this.$ = id => this.c.querySelector('#' + id);
    SYNCS.filter(s => !s.hidden).forEach(s => {
      this.$(`btn-${s.key}`).addEventListener('click', () => this._start(s, false));
      if (s.full) this.$(`btn-full-${s.key}`).addEventListener('click', () => this._start(s, true));
      this.$(`btn-cancel-${s.key}`).addEventListener('click', () => this._cancel(s));
    });
    const wp = SYNCS.find(s => s.key === 'webami-products');
    const wm = SYNCS.find(s => s.key === 'webami');
    this.$('btn-webami-products').addEventListener('click', () => this._start(wp, false, wm));

    await Promise.all([this._loadStats(), this._loadLog()]);
    SYNCS.forEach(s => this._resumeRunning(s));
  }

  _setRunning(s, running) {
    if (this._destroyed) return;
    this.$(`btn-${s.key}`).disabled = running;
    if (s.full) this.$(`btn-full-${s.key}`).disabled = running;
    this.$(`btn-cancel-${s.key}`).style.display = running ? 'inline-flex' : 'none';
    this.$(`progress-${s.key}`).style.display = running ? 'block' : 'none';
    const fp = this.$('btn-webami-products');
    if (fp && s.key === 'webami') fp.disabled = running;
  }

  _setProgress(s, job) {
    if (this._destroyed) return;
    const bar = this.$(`bar-${s.key}`);
    const msg = this.$(`msg-${s.key}`);
    const done = job.progress || 0;
    const total = job.total || 0;
    const t0 = this._starts[s.key];
    const elapsed = t0 ? ((Date.now() - t0) / 1000).toFixed(0) : null;
    const timeStr = (elapsed && Number(elapsed) > 0 ? ` — ${elapsed}s` : '') + (job.workers ? `\n(${job.workers} workers)` : '');
    const exporting = EXPORT_RE.test(job.message || '');
    if (total > 0 && !exporting) {
      const pct = Math.min(100, Math.round((done / total) * 100));
      bar.classList.remove('indeterminate');
      bar.style.width = `${pct}%`;
      msg.textContent = `${done.toLocaleString()} of ${total.toLocaleString()} ${job.unit || s.unit} (${pct}%)${timeStr}`;
    } else {
      bar.classList.add('indeterminate');
      bar.style.width = '';
      msg.textContent = (job.message || '…') + timeStr;
    }
  }

  async _start(s, full, ui = s) {
    try {
      const { job_id } = await API.post(s.full ? `${s.url}?full=${full}` : s.url);
      await this._follow(ui, job_id, s);
    } catch (e) {
      if (e.status === 409) {
        Toast.warning(e.message);
        this._resumeRunning(s);
      } else {
        Toast.error(e.message);
      }
    }
  }

  async _resumeRunning(s) {
    try {
      const { jobs } = await API.get('/api/sync/running');
      const job = jobs.find(j => j.name === s.name || (s.key === 'webami' && j.name === 'WebAMI Products'));
      if (job && !this._destroyed) await this._follow(s, job.id);
    } catch (_) { /* non-critical */ }
  }

  async _follow(s, jobId, runner = s) {
    this._jobs[s.key] = jobId;
    this._starts[s.key] = Date.now();
    this._setRunning(s, true);
    try {
      this._setProgress(s, {});
      while (!this._destroyed) {
        const job = await API.get(`/api/sync/status/${jobId}`);
        this._setProgress(s, job);
        if (job.status !== 'running') {
          this._announce(runner, job);
          break;
        }
        await sleep(POLL_MS);
      }
    } catch (e) {
      Toast.error(e.message);
    } finally {
      this._jobs[s.key] = null;
      this._starts[s.key] = null;
      this._setRunning(s, false);
    }
    if (!this._destroyed) await Promise.all([this._loadStats(), this._loadLog()]);
  }

  _announce(s, job) {
    const result = job.result || {};
    if (job.status === 'error') Toast.error(job.error || 'Sync failed');
    else if (job.status === 'cancelled') Toast.info('Sync cancelled');
    else if (result.status === 'partial') {
      Toast.warning(`Synced ${result.synced} ${s.unit}, ${result.errors} errors`);
    } else {
      const t0 = this._starts[s.key];
      const secs = t0 ? ((Date.now() - t0) / 1000).toFixed(0) : null;
      Toast.success(`${s.name} complete — ${result.synced ?? 0} ${s.unit}${secs ? ` in ${secs}s` : ''}`);
    }
  }

  async _cancel(s) {
    const id = this._jobs[s.key];
    if (!id) return;
    try {
      await API.post(`/api/sync/cancel/${id}`);
      Toast.info('Cancelling…');
    } catch (e) {
      Toast.error(e.message);
    }
  }

  async _loadStats() {
    try {
      const [cfg, products, w] = await Promise.all([
        API.get('/api/settings'),
        API.get('/api/products?per_page=1'),
        API.get('/api/sync/webami-stats'),
      ]);
      if (this._destroyed) return;
      this.$('stat-products').textContent = products.total.toLocaleString();
      this.$('stat-last-sync').textContent = Fmt.datetime(cfg.last_shopify_sync);
      this.$('stat-orders').textContent = w.orders.toLocaleString();
      this.$('stat-items').textContent = w.items.toLocaleString();
      this.$('stat-wproducts').textContent = w.products.toLocaleString();
      this.$('stat-last-webami').textContent = Fmt.datetime(w.last_sync);
    } catch (e) {
      Toast.error('Failed to load stats: ' + e.message);
    }
  }

  async _loadLog() {
    try {
      const { items } = await API.get('/api/sync/log?limit=10');
      if (this._destroyed) return;
      this.$('log-list').innerHTML = items.length
        ? items.map(l => `
            <div class="log-item">
              <div>
                <div class="log-title">${esc(l.action)}</div>
                <div class="muted">${esc(l.details || '')} — ${Fmt.datetime(l.created_at)}</div>
              </div>
              <span class="badge ${LOG_BADGES[l.status] || 'badge-draft'}">${esc(l.status)}</span>
            </div>`).join('')
        : '<div class="muted">No activity yet</div>';
    } catch (_) { /* non-critical */ }
  }
}