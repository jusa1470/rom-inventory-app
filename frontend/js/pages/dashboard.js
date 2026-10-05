class DashboardPage {
  constructor() { this._cancelIds = {}; }

  async render(container) {
    container.innerHTML = `
      <div class="page">
        <div class="page-title">Dashboard</div>
        <div class="row" style="margin-bottom:20px;flex-wrap:wrap">
          ${this._statCard('total-products', 'Shopify Products', '—', 'var(--text-primary)')}
          ${this._statCard('auto-mapped',    'Auto-mapped',       '—', 'var(--green)')}
          ${this._statCard('pending-review', 'Needs Review',      '—', 'var(--orange)')}
          ${this._statCard('unmatched',      'Unmatched',         '—', 'var(--red)')}
          ${this._statCard('dup-pending',    'Dup Groups',        '—', 'var(--text-secondary)')}
        </div>
        <div class="row" style="margin-bottom:20px;flex-wrap:wrap">
          ${this._statCard('total-orders',    'Orders',           '—', 'var(--blue)')}
          ${this._statCard('pending-receive', 'Items to Receive', '—', 'var(--orange)')}
          ${this._statCard('webami-cached',   'Webami Cached',    '—', 'var(--text-secondary)')}
          ${this._statCard('unknown-features','Unknown Features', '—', 'var(--text-secondary)')}
        </div>
        <div class="col" style="gap:12px;margin-bottom:24px">
          ${this._syncCard('shopify', 'Shopify Sync', 'last-shopify-sync', 'Pull all products from Shopify', 'btn-primary', 'Sync Shopify')}
          ${this._syncCard('matcher', 'Run Matcher',  'last-matcher',      'Match products to Webami catalog (UPC + fuzzy title)', 'btn-success', 'Run Matcher')}
          ${this._syncCard('duplicates', 'Duplicate Check', 'last-dupes', 'Rescan all products for duplicates', 'btn-warning', 'Run Duplicate Check')}
          ${this._syncCard('orders',  'Webami Orders','last-order-sync',   'Pull all submitted orders from Webami', 'btn-warning', 'Sync Orders')}
        </div>
        <div class="sync-card" style="margin-bottom:24px">
          <div class="sync-card-info">
            <div class="sync-card-title">Push UPCs to Shopify</div>
            <div class="sync-card-meta">Push UPC metafield for all actively mapped products</div>
          </div>
          <button class="btn btn-primary" id="push-upcs-btn">Push All UPCs</button>
        </div>
        <div class="section-label">Recent Activity</div>
        <div id="log-list"></div>
      </div>`;

    await this._loadStats();
    this._loadLog();
    this._bindSync();
    this._checkRunning();
    document.getElementById('push-upcs-btn').addEventListener('click', () => this._pushAllUpcs());
  }

  async _pushAllUpcs() {
    const btn = document.getElementById('push-upcs-btn');
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Checking…';
    try {
      const data = await API.post('/api/products/push-all-upcs');
      if (data.dry_run) {
        this._showUpcPreview(data.items || []);
      } else {
        Toast.success(`Pushed ${data.pushed} UPCs${data.errors?.length ? `, ${data.errors.length} errors` : ''}`);
      }
    } catch (e) {
      Toast.error(e.message);
    } finally {
      btn.disabled = false; btn.textContent = 'Push All UPCs';
    }
  }

  _showUpcPreview(items) {
    const bodyEl = document.createElement('div');
    bodyEl.innerHTML = `
      <p style="font-size:13px;color:var(--text-secondary);margin-bottom:12px">Dry run — ${items.length} UPCs would be pushed:</p>
      <div class="table-wrap" style="max-height:400px;overflow-y:auto">
        <table>
          <thead><tr><th style="text-align:left">Title</th><th style="text-align:left">UPC</th></tr></thead>
          <tbody>${items.map(i => `
            <tr>
              <td class="cell-truncate" style="text-align:left">${esc(i.title||'—')}</td>
              <td class="mono" style="text-align:left;font-size:12px">${esc(i.webami_upc)}</td>
            </tr>`).join('')}</tbody>
        </table>
      </div>`;
    Modal.open({ title: 'UPC Push Preview', body: bodyEl,
      buttons: [{ label: 'Close', cls: 'btn-ghost', onClick: Modal.close }] });
  }

  _syncCard(key, title, metaId, defaultMeta, btnCls, btnLabel) {
    return `
      <div class="sync-card">
        <div class="sync-card-info">
          <div class="sync-card-title">${title}</div>
          <div class="sync-card-meta" id="${metaId}">${defaultMeta}</div>
          <div id="${key}-progress" style="display:none">
            <div class="progress-bar-wrap"><div class="progress-bar" id="${key}-bar" style="width:0%"></div></div>
            <div style="font-size:12px;color:var(--text-muted);margin-top:4px" id="${key}-msg">Starting…</div>
          </div>
        </div>
        <div style="display:flex;gap:8px;align-items:center">
          <button class="btn ${btnCls}" id="btn-${key}">${btnLabel}</button>
          <button class="btn btn-ghost btn-sm" id="btn-cancel-${key}" style="display:none">Cancel</button>
        </div>
      </div>`;
  }

  _statCard(id, label, value, color) {
    return `
      <div class="stat-card flex-1" style="min-width:140px">
        <div class="stat-label">${label}</div>
        <div class="stat-value" id="stat-${id}" style="color:${color}">${value}</div>
      </div>`;
  }

  async _loadStats() {
    try {
      const s = await API.get('/api/stats');
      const set = (id, v) => { const el = document.getElementById(`stat-${id}`); if (el) el.textContent = v ?? '—'; };
      set('total-products',  s.total_products?.toLocaleString());
      set('auto-mapped',     s.auto_mapped?.toLocaleString());
      set('pending-review',  s.pending_review?.toLocaleString());
      set('unmatched',       s.unmatched?.toLocaleString());
      set('dup-pending',     s.dup_pending?.toLocaleString());
      set('total-orders',    s.total_orders?.toLocaleString());
      set('pending-receive', s.pending_receive?.toLocaleString());
      set('webami-cached',   s.webami_cached?.toLocaleString());
      set('unknown-features',s.unknown_features?.toLocaleString());
    } catch (e) { Toast.error('Failed to load stats: ' + e.message); }

    try {
      const cfg = await API.get('/api/settings');
      if (cfg.last_shopify_sync) document.getElementById('last-shopify-sync').textContent = 'Last synced: ' + Fmt.datetime(cfg.last_shopify_sync);
      if (cfg.last_matcher_run)  document.getElementById('last-matcher').textContent      = 'Last run: '    + Fmt.datetime(cfg.last_matcher_run);
    } catch (_) {}
    try {
      const log = await API.get('/api/log?limit=50');
      const os = (log.items||[]).find(l => l.action==='webami_order_sync' && l.status==='done');
      if (os) document.getElementById('last-order-sync').textContent = 'Last synced: ' + Fmt.datetime(os.created_at) + (os.details ? ' — '+os.details : '');
    } catch (_) {}
  }

  async _loadLog() {
    try {
      const data = await API.get('/api/log?limit=10');
      const el = document.getElementById('log-list');
      if (!data.items?.length) { el.innerHTML = '<div class="empty-state"><div class="empty-state-text">No activity yet</div></div>'; return; }
      el.innerHTML = data.items.map(l => `
        <div class="pending-item">
          <div class="item-info">
            <div class="item-title">${esc(l.action)}</div>
            <div class="item-meta">${esc(l.details||'')} — ${Fmt.date(l.created_at)}</div>
          </div>
          <span class="badge ${l.status==='done'?'badge-new':'badge-used'}">${esc(l.status)}</span>
        </div>`).join('');
    } catch (_) {}
  }

  _bindSync() {
    const jobs = {
      shopify:    { url: '/api/sync/shopify',       label: 'Sync Shopify' },
      orders:     { url: '/api/orders/sync-webami', label: 'Sync Orders'  },
      matcher:    { url: '/api/sync/matcher',       label: 'Run Matcher'  },
      duplicates: { url: '/api/sync/duplicates',    label: 'Run Duplicate Check' },
    };
    Object.entries(jobs).forEach(([key, cfg]) => {
      document.getElementById(`btn-${key}`).addEventListener('click', () => this._runJob(key, cfg.url, cfg.label));
      document.getElementById(`btn-cancel-${key}`).addEventListener('click', () => this._cancelJob(key));
    });
  }

  async _checkRunning() {
    const NAME_KEY = {
      'Shopify Sync':      'shopify',
      'Webami Order Sync': 'orders',
      'Batch Matcher':     'matcher',
      'Duplicate Check':   'duplicates',
    };
    const KEY_LABEL = { shopify:'Sync Shopify', orders:'Sync Orders', matcher:'Run Matcher', duplicates:'Run Duplicate Check' };
    try {
      const { jobs } = await API.get('/api/sync/running');
      for (const job of (jobs || [])) {
        const key = NAME_KEY[job.name];
        if (!key || this._cancelIds[key]) continue;
        this._cancelIds[key] = job.id;
        const btn    = document.getElementById(`btn-${key}`);
        const cancel = document.getElementById(`btn-cancel-${key}`);
        const prog   = document.getElementById(`${key}-progress`);
        const bar    = document.getElementById(`${key}-bar`);
        const msg    = document.getElementById(`${key}-msg`);
        if (btn)    { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>'; }
        if (cancel)   cancel.style.display = 'inline-flex';
        if (prog)     prog.style.display   = 'block';
        if (msg)      msg.textContent = job.message || '…';
        if (bar && job.total) bar.style.width = `${Math.round((job.progress/job.total)*100)}%`;
        this._pollJob(job.id, s => {
          const pct = s.total ? Math.round((s.progress/s.total)*100) : 0;
          if (bar) bar.style.width = `${pct}%`;
          if (msg) msg.textContent = s.message || '…';
        }).then(() => { this._loadStats(); this._loadLog(); })
          .catch(() => {})
          .finally(() => {
            if (btn)    { btn.disabled = false; btn.textContent = KEY_LABEL[key]; }
            if (cancel)   cancel.style.display = 'none';
            if (prog)     prog.style.display   = 'none';
            delete this._cancelIds[key];
          });
      }
    } catch (_) {}
  }

  async _cancelJob(key) {
    const jobId = this._cancelIds[key];
    if (!jobId) return;
    try { await API.post(`/api/sync/cancel/${jobId}`); Toast.info('Cancelling…'); } catch (_) {}
  }

  async _runJob(key, startUrl, label) {
    const btn    = document.getElementById(`btn-${key}`);
    const cancel = document.getElementById(`btn-cancel-${key}`);
    const prog   = document.getElementById(`${key}-progress`);
    const bar    = document.getElementById(`${key}-bar`);
    const msg    = document.getElementById(`${key}-msg`);
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
    cancel.style.display = 'inline-flex';
    prog.style.display = 'block';
    try {
      const { job_id } = await API.post(startUrl);
      this._cancelIds[key] = job_id;
      await this._pollJob(job_id, s => {
        const pct = s.total ? Math.round((s.progress/s.total)*100) : 0;
        bar.style.width = `${pct}%`; msg.textContent = s.message || '…';
      });
      Toast.success(`${label} complete`);
      await this._loadStats(); this._loadLog();
    } catch (e) {
      if (!e.message?.includes('cancel')) Toast.error(e.message);
    } finally {
      btn.disabled = false; btn.textContent = label;
      cancel.style.display = 'none'; prog.style.display = 'none';
      delete this._cancelIds[key];
    }
  }

  _pollJob(jobId, onProgress) {
    return new Promise((resolve, reject) => {
      const poll = setInterval(async () => {
        try {
          const s = await API.get(`/api/sync/status/${jobId}`);
          onProgress(s);
          if (s.status === 'done')      { clearInterval(poll); resolve(s); }
          if (s.status === 'error')     { clearInterval(poll); reject(new Error(s.error || 'Job failed')); }
          if (s.status === 'cancelled') { clearInterval(poll); resolve(s); }
        } catch (e) { clearInterval(poll); reject(e); }
      }, 5000);
    });
  }
}