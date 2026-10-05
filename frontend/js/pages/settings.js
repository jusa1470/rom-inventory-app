class SettingsPage {
  async render(container) {
    container.innerHTML = `
      <div class="page">
        <div class="page-title">Settings</div>

        <!-- ── Credentials ── -->
        <div class="card" style="margin-bottom:20px">
          <div class="section-label">Shopify</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
            <div class="input-group">
              <label class="input-label">Store Domain</label>
              <input id="s-store" class="input" placeholder="mystore.myshopify.com">
            </div>
            <div class="input-group">
              <label class="input-label">API Version</label>
              <input id="s-apiversion" class="input" placeholder="2025-01">
            </div>
            <div class="input-group" style="grid-column:1/-1">
              <label class="input-label">Admin API Token <span style="color:var(--text-muted)">(leave blank to keep current)</span></label>
              <input id="s-token" class="input" type="password" placeholder="shpat_… (leave blank to keep)">
            </div>
          </div>

          <div class="section-label" style="margin-top:12px">Shopify Metafields</div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px">
            <div class="input-group">
              <label class="input-label">UPC Namespace</label>
              <input id="s-upc-ns" class="input" placeholder="custom">
            </div>
            <div class="input-group">
              <label class="input-label">UPC Key</label>
              <input id="s-upc-key" class="input" placeholder="upc">
            </div>
            <div class="input-group">
              <label class="input-label">Genres Namespace</label>
              <input id="s-genres-ns" class="input" placeholder="custom">
            </div>
            <div class="input-group">
              <label class="input-label">Genres Key</label>
              <input id="s-genres-key" class="input" placeholder="genres">
            </div>
          </div>
        </div>

        <div class="card" style="margin-bottom:20px">
          <div class="section-label">Webami</div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
            <div class="input-group">
              <label class="input-label">Base URL</label>
              <input id="s-wurl" class="input" placeholder="https://aent-m.com">
            </div>
            <div class="input-group">
              <label class="input-label">Username / Email</label>
              <input id="s-wuser" class="input" placeholder="email@example.com">
            </div>
            <div class="input-group">
              <label class="input-label">Password <span style="color:var(--text-muted)">(leave blank to keep)</span></label>
              <input id="s-wpw" class="input" type="password" placeholder="leave blank to keep">
            </div>
          </div>
        </div>

        <div class="card" style="margin-bottom:20px">
          <div class="section-label">Pricing</div>
          <div style="display:grid;grid-template-columns:200px 1fr;gap:12px;align-items:center">
            <div class="input-group" style="margin:0">
              <label class="input-label">Target Margin (%)</label>
              <div class="row center" style="gap:10px">
                <input id="s-margin" class="input" type="number" min="1" max="99" step="0.5" style="width:80px">
                <span id="margin-label" style="font-size:13px;color:var(--text-secondary)"></span>
              </div>
            </div>
            <div style="font-size:12px;color:var(--text-muted)">
              Suggested price = cost ÷ (1 − margin). At 34% margin: $10 cost → $15.15 price.
            </div>
            <label style="display:flex;align-items:center;gap:8px;cursor:pointer;margin-top:8px;font-size:13px">
              <input type="checkbox" id="s-dryrun"> Dry run (skip all Shopify writes)
            </label>
          </div>
        </div>

        <div class="row" style="margin-bottom:20px">
          <div style="flex:1"></div>
          <div class="input-group" style="width:300px;margin:0">
            <label class="input-label">Current Password (required to save credentials)</label>
            <input id="s-current-pw" class="input" type="password" placeholder="Your app password">
          </div>
          <button class="btn btn-primary" id="save-settings-btn" style="margin-top:22px;margin-left:10px">Save Settings</button>
        </div>

        <!-- ── Change Password ── -->
        <div class="card" style="margin-bottom:20px">
          <div class="section-label">Change App Password</div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px">
            <div class="input-group">
              <label class="input-label">Current Password</label>
              <input id="cp-old" class="input" type="password">
            </div>
            <div class="input-group">
              <label class="input-label">New Password</label>
              <input id="cp-new" class="input" type="password">
            </div>
            <div class="input-group" style="justify-content:flex-end">
              <label class="input-label">&nbsp;</label>
              <button class="btn btn-warning" id="change-pw-btn">Change Password</button>
            </div>
          </div>
        </div>

        <!-- ── Artist Aliases ── -->
        <div class="section-label">Artist / Vendor Aliases</div>
        <p style="font-size:12px;color:var(--text-muted);margin-bottom:12px">
          When Webami says "alias", use "canonical" instead. Case-insensitive.
        </p>
        <div class="row" style="gap:8px;margin-bottom:12px">
          <input id="alias-from" class="input" placeholder="e.g. Beatles" style="max-width:200px">
          <span style="color:var(--text-secondary);align-self:center">→</span>
          <input id="alias-to" class="input" placeholder="e.g. The Beatles" style="max-width:200px">
          <button class="btn btn-primary btn-sm" id="add-alias-btn">Add</button>
        </div>
        <div id="aliases-list" style="margin-bottom:24px"></div>

        <!-- ── UPC Aliases ── -->
        <div class="section-label">UPC Aliases (Retired → Active)</div>
        <p style="font-size:12px;color:var(--text-muted);margin-bottom:12px">
          These are auto-populated when Webami redirects a retired UPC. You can add them manually too.
        </p>
        <div class="row" style="gap:8px;margin-bottom:12px">
          <input id="upc-retired" class="input" placeholder="Retired UPC" style="max-width:160px">
          <span style="color:var(--text-secondary);align-self:center">→</span>
          <input id="upc-active" class="input" placeholder="Active UPC" style="max-width:160px">
          <button class="btn btn-primary btn-sm" id="add-upc-alias-btn">Add</button>
        </div>
        <div id="upc-aliases-list"></div>
      </div>`;

    await this._loadSettings();
    this._bindEvents(container);
    await this._loadAliases();
    await this._loadUpcAliases();
  }

  async _loadSettings() {
    try {
      const s = await API.get('/api/settings');
      document.getElementById('s-store').value      = s.shopify_store || '';
      document.getElementById('s-apiversion').value = s.shopify_api_version || '2025-01';
      document.getElementById('s-upc-ns').value     = s.shopify_upc_ns || 'custom';
      document.getElementById('s-upc-key').value    = s.shopify_upc_key || 'upc';
      document.getElementById('s-genres-ns').value   = s.shopify_genres_ns || 'custom';
      document.getElementById('s-genres-key').value  = s.shopify_genres_key || 'genres';
      document.getElementById('s-wurl').value       = s.webami_base_url || '';

      const margin = Math.round((s.target_margin || 0.34) * 100);
      document.getElementById('s-margin').value = margin;
      document.getElementById('s-dryrun').checked = s.dry_run === 1;
      document.getElementById('margin-label').textContent = `(${margin}%)`;
    } catch (e) { Toast.error('Failed to load settings: ' + e.message); }
  }

  _bindEvents(container) {
    container.querySelector('#s-margin').addEventListener('input', e => {
      document.getElementById('margin-label').textContent = `(${e.target.value}%)`;
    });

    container.querySelector('#save-settings-btn').addEventListener('click', () => this._saveSettings());
    container.querySelector('#change-pw-btn').addEventListener('click', () => this._changePassword());

    container.querySelector('#add-alias-btn').addEventListener('click', () => {
      const from = container.querySelector('#alias-from').value.trim();
      const to   = container.querySelector('#alias-to').value.trim();
      if (!from || !to) { Toast.warning('Both fields required'); return; }
      API.post('/api/aliases', { alias_name: from, canonical_name: to })
        .then(() => {
          container.querySelector('#alias-from').value = '';
          container.querySelector('#alias-to').value   = '';
          this._loadAliases();
        }).catch(e => Toast.error(e.message));
    });

    container.querySelector('#add-upc-alias-btn').addEventListener('click', () => {
      const retired = container.querySelector('#upc-retired').value.trim();
      const active  = container.querySelector('#upc-active').value.trim();
      if (!retired || !active) { Toast.warning('Both UPCs required'); return; }
      API.post('/api/upc-aliases', { retired_upc: retired, active_upc: active })
        .then(() => {
          container.querySelector('#upc-retired').value = '';
          container.querySelector('#upc-active').value  = '';
          this._loadUpcAliases();
        }).catch(e => Toast.error(e.message));
    });
  }

  async _saveSettings() {
    const marginPct = parseFloat(document.getElementById('s-margin').value) || 34;
    const payload = {
      shopify_store:       document.getElementById('s-store').value.trim(),
      shopify_api_version: document.getElementById('s-apiversion').value.trim(),
      shopify_upc_ns:      document.getElementById('s-upc-ns').value.trim(),
      shopify_upc_key:     document.getElementById('s-upc-key').value.trim(),
      shopify_genres_ns:    document.getElementById('s-genres-ns').value.trim(),
      shopify_genres_key:   document.getElementById('s-genres-key').value.trim(),
      webami_base_url:     document.getElementById('s-wurl').value.trim(),
      target_margin:       marginPct / 100,
      dry_run:             document.getElementById('s-dryrun')?.checked ? 1 : 0,
      password:            document.getElementById('s-current-pw').value,
    };

    const token  = document.getElementById('s-token').value.trim();
    const wuser  = document.getElementById('s-wuser').value.trim();
    const wpw    = document.getElementById('s-wpw').value.trim();
    if (token)  payload.shopify_token   = token;
    if (wuser)  payload.webami_username = wuser;
    if (wpw)    payload.webami_password = wpw;

    try {
      await API.post('/api/settings', payload);
      Toast.success('Settings saved');
      document.getElementById('s-token').value = '';
      document.getElementById('s-wpw').value   = '';
      document.getElementById('s-current-pw').value = '';
      const banner = document.getElementById('dry-run-banner');
      if (banner) banner.style.display = payload.dry_run ? 'flex' : 'none';
    } catch (e) { Toast.error(e.message); }
  }

  async _changePassword() {
    const oldPw = document.getElementById('cp-old').value.trim();
    const newPw = document.getElementById('cp-new').value.trim();
    if (!oldPw || !newPw) { Toast.warning('Both fields required'); return; }
    try {
      await API.post('/api/auth/change-password', { old_password: oldPw, new_password: newPw });
      Toast.success('Password changed');
      document.getElementById('cp-old').value = '';
      document.getElementById('cp-new').value = '';
    } catch (e) { Toast.error(e.message); }
  }

  async _loadAliases() {
    const el = document.getElementById('aliases-list');
    try {
      const data = await API.get('/api/aliases');
      if (!data.items?.length) {
        el.innerHTML = '<div style="color:var(--text-muted);font-size:12px">No aliases yet</div>';
        return;
      }
      el.innerHTML = data.items.map(a => `
        <div class="pending-item">
          <div class="item-info">
            <span class="mono">${esc(a.alias_name)}</span>
            <span style="color:var(--text-muted);margin:0 8px">→</span>
            <span class="mono">${esc(a.canonical_name)}</span>
          </div>
          <button class="btn btn-danger btn-sm del-alias" data-id="${a.id}">Remove</button>
        </div>`).join('');
      el.querySelectorAll('.del-alias').forEach(btn =>
        btn.addEventListener('click', () =>
          API.delete(`/api/aliases/${btn.dataset.id}`)
            .then(() => this._loadAliases())
            .catch(e => Toast.error(e.message))));
    } catch (e) { el.innerHTML = `<div class="alert alert-error">${esc(e.message)}</div>`; }
  }

  async _loadUpcAliases() {
    const el = document.getElementById('upc-aliases-list');
    try {
      const data = await API.get('/api/upc-aliases');
      if (!data.items?.length) {
        el.innerHTML = '<div style="color:var(--text-muted);font-size:12px">No UPC aliases yet</div>';
        return;
      }
      el.innerHTML = `
        <div class="table-wrap" style="max-height:300px;overflow-y:auto">
          <table>
            <thead><tr><th>Retired UPC</th><th>Active UPC</th><th>Notes</th><th>Added</th><th></th></tr></thead>
            <tbody>${data.items.map(a => `
              <tr>
                <td class="mono" style="font-size:12px">${esc(a.retired_upc)}</td>
                <td class="mono" style="font-size:12px">${esc(a.active_upc)}</td>
                <td style="font-size:12px">${esc(a.notes || '—')}</td>
                <td style="font-size:12px">${Fmt.date(a.created_at)}</td>
                <td><button class="btn btn-danger btn-sm del-upc-alias" data-id="${esc(a.retired_upc)}">×</button></td>
              </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
      el.querySelectorAll('.del-upc-alias').forEach(btn =>
        btn.addEventListener('click', () =>
          API.delete(`/api/upc-aliases/${encodeURIComponent(btn.dataset.id)}`)
            .then(() => this._loadUpcAliases())
            .catch(e => Toast.error(e.message))));
    } catch (e) { el.innerHTML = `<div class="alert alert-error">${esc(e.message)}</div>`; }
  }
}
