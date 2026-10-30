import { API } from '../api.js';
import { Toast } from '../components/toast.js';
import { Fmt, esc } from '../util.js';

const METAFIELD_GROUPS = [
  {
    title: 'Product metafields',
    rows: [
      { label: 'Genres', ns: 'shopify_genres_ns', key: 'shopify_genres_key' },
      { label: 'Type', ns: 'shopify_type_ns', key: 'shopify_type_key' },
    ],
  },
  {
    title: 'Variant metafields',
    rows: [
      { label: 'UPC', ns: 'shopify_upc_ns', key: 'shopify_upc_key' },
      { label: 'Description', ns: 'shopify_description_ns', key: 'shopify_description_key' },
      { label: 'Release date', ns: 'shopify_release_date_ns', key: 'shopify_release_date_key' },
      { label: 'Variant tags', ns: 'shopify_variant_tags_ns', key: 'shopify_variant_tags_key' },
    ],
  },
];

const TEXT_FIELDS = [
  'shopify_api_version',
  ...METAFIELD_GROUPS.flatMap(g => g.rows.flatMap(r => [r.ns, r.key])),
];
const STORE_LABELS = { main: 'Main store', test: 'Test store' };
const POLL_MS = 1500;
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

export class SettingsPage {
  constructor() {
    this._destroyed = false;
  }

  destroy() {
    this._destroyed = true;
  }

  async render(container) {
    this.c = container;
    container.innerHTML = `
      <div class="page">
        <div class="page-title">Settings</div>
        <div id="settings-body" class="muted">Loading…</div>
      </div>`;
    try {
      this._renderForm(await API.get('/api/settings'));
    } catch (e) {
      Toast.error('Failed to load settings: ' + e.message);
    }
  }

  _input(name, label, value, attrs = '') {
    return `
      <div class="input-group">
        <label class="input-label">${label}</label>
        <input class="input" name="${name}" value="${esc(value)}" ${attrs}>
      </div>`;
  }

  _renderForm(s) {
    const body = this.c.querySelector('#settings-body');
    body.className = '';
    body.innerHTML = `
      <div class="card">
        <div class="section-label" style="margin-top:0">Connection (from vault)</div>
        <div class="form-grid">
          ${Object.entries(s.stores).map(([key, st]) => `
            <div>
              <div class="input-label">${STORE_LABELS[key]}</div>
              <div>${esc(st.store || '—')}
                <span class="badge ${st.token_set ? 'badge-new' : 'badge-error'}">${st.token_set ? 'Token set' : 'No token'}</span></div>
            </div>`).join('')}
            <span class="badge ${s.shopify_token_set ? 'badge-new' : 'badge-error'}">${s.shopify_token_set ? 'Set' : 'Missing'}</span></div>
          <div><div class="input-label">Location ID</div><div class="mono">${esc(s.shopify_location_id || '—')}</div></div>
          <div><div class="input-label">Last sync</div><div>${Fmt.datetime(s.last_shopify_sync)}</div></div>
        </div>
      </div>

      <form class="card" id="settings-form">
        <div class="form-grid">
          ${this._input('shopify_api_version', 'API version', s.shopify_api_version, 'placeholder="2025-01"')}
          ${this._input('page_size', 'Page size', s.page_size, 'type="number" min="10" max="200"')}
        </div>

        ${METAFIELD_GROUPS.map(g => `
          <div class="section-label">${g.title}</div>
          ${g.rows.map(r => `
            <div class="mf-row">
              <div class="mf-name">${r.label}</div>
              ${this._input(r.ns, 'Namespace', s[r.ns])}
              ${this._input(r.key, 'Key', s[r.key])}
            </div>`).join('')}
        `).join('')}

        <label class="check-row">
          <input type="checkbox" name="dry_run" ${s.dry_run ? 'checked' : ''}>
          <span>Test mode <span class="muted">(no writes to Shopify)</span></span>
        </label>

        <div class="form-actions">
          <button class="btn btn-primary" id="save-btn">Save settings</button>
        </div>
      </form>`;
    body.querySelector('#settings-form').addEventListener('submit', e => {
      e.preventDefault();
      this._save();
    });
    body.insertAdjacentHTML('beforeend', this._tokenCard(s));
    this._bindTokenCard(s);
  }

  _tokenCard(s) {
    if (!s.oauth_ready) {
      return `
        <div class="card">
          <div class="section-label" style="margin-top:0">Shopify token</div>
          <p class="muted">Add <span class="mono">shopify_client_id</span> and
            <span class="mono">shopify_client_secret</span> to the vault (tools/build_vault.py)
            to enable token refresh.</p>
        </div>`;
    }
    return `
      <form class="card" id="token-form">
        <div class="section-label" style="margin-top:0">Refresh Shopify token</div>
        <div class="form-grid">
          <div class="input-group">
            <label class="input-label">Store</label>
            <select class="input" name="store">
              ${Object.entries(s.stores).map(([key, st]) =>
                `<option value="${key}" ${st.store ? '' : 'disabled'}>${STORE_LABELS[key]} — ${esc(st.store || 'not in vault')}</option>`).join('')}
            </select>
          </div>
          <div class="input-group">
            <label class="input-label">App password</label>
            <input class="input" type="password" name="password" autocomplete="current-password">
          </div>
        </div>

        <div class="input-group" style="margin-top:12px">
          <label class="input-label">Scopes <span class="muted">(comma separated)</span></label>
          <textarea class="input scope-box" name="scopes"></textarea>
        </div>
        <div class="scope-add">
          <input class="input" name="new_scope" placeholder="Add a scope, e.g. read_fulfillments">
          <button type="button" class="btn btn-ghost" id="add-scope-btn">Add scope</button>
        </div>

        <div class="form-actions">
          <button class="btn btn-primary" id="refresh-btn">Refresh token</button>
          <span class="muted" id="token-msg"></span>
        </div>
      </form>`;
  }

  _bindTokenCard(s) {
    const form = this.c.querySelector('#token-form');
    if (!form) return;
    const setScopes = () => {
      const current = s.stores[form.elements.store.value].scope;
      form.elements.scopes.value = current || s.default_scopes;
    };
    form.elements.store.value = Object.keys(s.stores).find(k => s.stores[k].store) || 'main';
    setScopes();
    form.elements.store.addEventListener('change', setScopes);

    const addScope = () => {
      const scope = form.elements.new_scope.value.trim();
      if (!scope) return;
      const list = form.elements.scopes.value.split(/[,\s]+/).filter(Boolean);
      if (!list.includes(scope)) list.push(scope);
      form.elements.scopes.value = list.join(',');
      form.elements.new_scope.value = '';
    };
    form.querySelector('#add-scope-btn').addEventListener('click', addScope);
    form.elements.new_scope.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        e.preventDefault();
        addScope();
      }
    });
    form.addEventListener('submit', e => {
      e.preventDefault();
      this._refreshToken(form);
    });
  }

  async _refreshToken(form) {
    const btn = form.querySelector('#refresh-btn');
    const msg = form.querySelector('#token-msg');
    // Open the tab now, inside the click, so popup blockers allow it.
    const tab = window.open('', '_blank');
    btn.disabled = true;
    msg.textContent = 'Starting…';
    try {
      const { state, url } = await API.post('/api/shopify/oauth/start', {
        store: form.elements.store.value,
        scopes: form.elements.scopes.value,
        password: form.elements.password.value,
      });
      form.elements.password.value = '';
      if (tab) tab.location.href = url;
      else msg.innerHTML = `Popup blocked — <a href="${esc(url)}" target="_blank" rel="noopener">open the Shopify authorization page</a>`;
      if (tab) msg.textContent = 'Approve the app in the Shopify tab…';
      await this._awaitAuthorization(state, msg);
    } catch (e) {
      if (tab) tab.close();
      msg.textContent = '';
      Toast.error(e.message);
      btn.disabled = false;
    }
  }

  async _awaitAuthorization(state, msg) {
    while (!this._destroyed) {
      await sleep(POLL_MS);
      const r = await API.get(`/api/shopify/oauth/status/${state}`);
      if (r.status === 'pending' || r.status === 'working') continue;
      if (r.status === 'done') {
        Toast.success(r.message);
        this._renderForm(await API.get('/api/settings'));
      } else {
        msg.textContent = '';
        Toast.error(r.message || 'Token refresh failed');
        this.c.querySelector('#refresh-btn').disabled = false;
      }
      return;
    }
  }

  async _save() {
    const form = this.c.querySelector('#settings-form');
    const btn = form.querySelector('#save-btn');
    const data = new FormData(form);
    const payload = {};
    for (const name of TEXT_FIELDS) payload[name] = String(data.get(name) ?? '').trim();
    payload.page_size = parseInt(String(data.get('page_size')), 10);
    payload.dry_run = form.elements.dry_run.checked;

    btn.disabled = true;
    try {
      const saved = await API.put('/api/settings', payload);
      Toast.success('Settings saved');
      const banner = document.getElementById('dry-run-banner');
      if (banner) banner.style.display = saved.dry_run ? 'flex' : 'none';
      this._renderForm(saved);
    } catch (e) {
      Toast.error(e.message);
      btn.disabled = false;
    }
  }
}