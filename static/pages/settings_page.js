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

export class SettingsPage {
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
          <div><div class="input-label">Store</div><div>${esc(s.shopify_store || '—')}</div></div>
          <div><div class="input-label">Admin token</div>
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
  }

  async _save() {
    const form = this.c.querySelector('#settings-form');
    const btn = form.querySelector('#save-btn');
    const data = new FormData(form);
    const payload = {};
    for (const name of TEXT_FIELDS) payload[name] = String(data.get(name) ?? '').trim();
    payload.page_size = parseInt(data.get('page_size'), 10);
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