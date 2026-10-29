import { API } from '../api.js';
import { Toast } from '../components/toast.js';
import { Fmt, esc } from '../util.js';

const POLL_MS = 1000;
const EXPORT_RE = /preparing the export/i;
const LOG_BADGES = { done: 'badge-new', partial: 'badge-used', cancelled: 'badge-draft', error: 'badge-error' };
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

export class DashboardPage {
  constructor() {
    this._jobId = null;
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
          <div class="stat-card">
            <div class="stat-label">Products synced</div>
            <div class="stat-value" id="stat-products">—</div>
          </div>
          <div class="stat-card">
            <div class="stat-label">Last sync</div>
            <div class="stat-value small" id="stat-last-sync">—</div>
          </div>
        </div>

        <div class="sync-card">
          <div class="sync-card-info">
            <div class="sync-card-title">Shopify Sync</div>
            <div class="sync-card-meta">Pull products, variants and variant images from Shopify</div>
            <div id="sync-progress" style="display:none">
            <div class="progress-bar-wrap"><div class="progress-bar indeterminate" id="sync-bar"></div></div>
              <div class="progress-msg" id="sync-msg">Starting…</div>
            </div>
          </div>
          <div class="sync-actions">
            <button class="btn btn-primary" id="btn-sync">Sync</button>
            <button class="btn btn-ghost" id="btn-full">Full sync</button>
            <button class="btn btn-ghost btn-sm" id="btn-cancel" style="display:none">Cancel</button>
          </div>
        </div>

        <div class="section-label">Recent activity</div>
        <div id="log-list"></div>
      </div>`;

    this.$ = id => this.c.querySelector('#' + id);
    this.$('btn-sync').addEventListener('click', () => this._start(false));
    this.$('btn-full').addEventListener('click', () => this._start(true));
    this.$('btn-cancel').addEventListener('click', () => this._cancel());

    await Promise.all([this._loadStats(), this._loadLog()]);
    this._resumeRunning();
  }

  _setRunning(running) {
    if (this._destroyed) return;
    this.$('btn-sync').disabled = running;
    this.$('btn-full').disabled = running;
    this.$('btn-cancel').style.display = running ? 'inline-flex' : 'none';
    this.$('sync-progress').style.display = running ? 'block' : 'none';
  }

  _setProgress(job) {
    if (this._destroyed) return;
    const bar = this.$('sync-bar');
    const done = job.progress || 0;
    const total = job.total || 0;
    const elapsed = this._startedAt ? ((Date.now() - this._startedAt) / 1000).toFixed(0) : null;
    const timeStr = elapsed && elapsed > 0 ? ` — ${elapsed}s` : '';
    const exporting = EXPORT_RE.test(job.message || '');
    if (total > 0 && !exporting) {
      const pct = Math.min(100, Math.round((done / total) * 100));
      bar.classList.remove('indeterminate');
      bar.style.width = `${pct}%`;
      this.$('sync-msg').textContent =
        `${done.toLocaleString()} of ${total.toLocaleString()} products (${pct}%)${timeStr}`;
    } else {
      bar.classList.add('indeterminate');
      bar.style.width = '';
      this.$('sync-msg').textContent = (job.message || '…') + timeStr;
    }
  }

  async _start(full) {
    try {
      const { job_id } = await API.post(`/api/sync/shopify?full=${full}`);
      await this._follow(job_id);
    } catch (e) {
      if (e.status === 409) {
        Toast.warning(e.message);
        this._resumeRunning();
      } else {
        Toast.error(e.message);
      }
    }
  }

  async _resumeRunning() {
    try {
      const { jobs } = await API.get('/api/sync/running');
      const job = jobs.find(j => j.name === 'Shopify Sync');
      if (job && !this._destroyed) await this._follow(job.id);
    } catch (_) { /* non-critical */ }
  }

  async _follow(jobId) {
    this._jobId = jobId;
    this._startedAt = Date.now();
    this._setRunning(true);
    try {
      this._setProgress({});
      while (!this._destroyed) {
        const job = await API.get(`/api/sync/status/${jobId}`);
        this._setProgress(job);
        if (job.status !== 'running') {
          this._announce(job);
          break;
        }
        await sleep(POLL_MS);
      }
    } catch (e) {
      Toast.error(e.message);
    } finally {
      this._jobId = null;
      this._startedAt = null;
      this._setRunning(false);
    }
    if (!this._destroyed) await Promise.all([this._loadStats(), this._loadLog()]);
  }

  _announce(job) {
    const result = job.result || {};
    if (job.status === 'error') Toast.error(job.error || 'Sync failed');
    else if (job.status === 'cancelled') Toast.info('Sync cancelled');
    else if (result.status === 'partial') {
      Toast.warning(`Synced ${result.synced} products, ${result.errors} errors`);
    } else {
      const secs = this._startedAt ? ((Date.now() - this._startedAt) / 1000).toFixed(0) : null;
      const timeStr = secs ? ` in ${secs}s` : '';
      Toast.success(`Sync complete — ${result.synced ?? 0} products${timeStr}`);
    }
  }

  async _cancel() {
    if (!this._jobId) return;
    try {
      await API.post(`/api/sync/cancel/${this._jobId}`);
      Toast.info('Cancelling…');
    } catch (e) {
      Toast.error(e.message);
    }
  }

  async _loadStats() {
    try {
      const [cfg, products] = await Promise.all([
        API.get('/api/settings'),
        API.get('/api/products?per_page=1'),
      ]);
      if (this._destroyed) return;
      this.$('stat-products').textContent = products.total.toLocaleString();
      this.$('stat-last-sync').textContent = Fmt.datetime(cfg.last_shopify_sync);
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