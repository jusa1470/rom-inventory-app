const UNMATCHED_COLS = [
  { id:'title',    label:'Title',    sortKey:'title',    filterable:true, thStyle:'text-align:left' },
  { id:'vendor',   label:'Vendor',   sortKey:'vendor',   filterable:true, thStyle:'text-align:left' },
  { id:'category', label:'Category', sortKey:'category', filterable:true, thStyle:'text-align:left' },
  { id:'cost',     label:'Cost',     sortKey:'cost',      filterable:false, thStyle:'text-align:right' },
  { id:'actions',  label:'',         sortKey:null,        filterable:false },
];
const UNMATCHED_COL_W = { title:220, vendor:150, category:130, cost:80, actions:260 };

const MISSING_COLS = [
  { id:'check',   label:'',        sortKey:null,     filterable:false },
  { id:'thumb',   label:'',        sortKey:null,     filterable:false },
  { id:'title',   label:'Title',   sortKey:'title',  filterable:true  },
  { id:'vendor',  label:'Vendor',  sortKey:'vendor', filterable:true  },
  { id:'pstatus', label:'Status',  sortKey:'status', filterable:true,
    filterType:'select', options:['ACTIVE','DRAFT','ARCHIVED'] },
  { id:'category', label:'Category', sortKey:'category', filterable:true, thStyle:'text-align:center' },
  { id:'missing', label:'Missing', sortKey:null,     filterable:false },
  { id:'actions', label:'Actions', sortKey:null,     filterable:false },
];
const MISSING_COL_WIDTHS = { check:32, thumb:48, title:200, vendor:130, pstatus:80, category:120, missing:0, actions:160 };

class MatchingPage {
constructor() { this.tab = 'queue'; this.page = 1; this.fieldFilter = ''; this.selected = new Set(); this.selectedDupes = new Set(); this.mfSort = 'title_asc'; this.mfColFilters = {}; this.umSort = 'title_asc'; this.umColFilters = {}; this.hideDashU = false; }
  async render(container) {
    container.innerHTML = `
      <div class="page">
        <div class="page-title">Matching</div>
        <div class="tabs">
          <button class="tab-btn active" data-tab="queue">Review Queue</button>
          <button class="tab-btn" data-tab="dupes">Duplicate Groups</button>
          <button class="tab-btn" data-tab="missing">Missing Fields</button>
          <button class="tab-btn" data-tab="unmatched">Unmatched</button>
          <button class="tab-btn" data-tab="variances">Field Variances</button>
        </div>
        <div id="matching-content"></div>
      </div>`;

    container.querySelectorAll('.tab-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        container.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        this.tab  = btn.dataset.tab;
        this.page = 1;
        this._load();
      });
    });
    await this._load();
  }

  async _load() {
    if (this.tab === 'queue') await this._loadQueue();
    else if (this.tab === 'dupes') await this._loadDupes();
    else if (this.tab === 'missing') await this._loadMissing();
    else if (this.tab === 'unmatched') await this._loadUnmatched();
    else await this._loadVariances();
  }

  async _loadVariances() {
    const el = document.getElementById('matching-content');
    el.innerHTML = `
      <div class="row" style="margin-bottom:16px;gap:10px;align-items:center;flex-wrap:wrap">
        <span style="font-size:13px;color:var(--text-muted)">Compare fields:</span>
        ${['title','artist','cost','weight'].map(f => `
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px">
            <input type="checkbox" class="var-field-cb" value="${f}" ${['title','artist','cost'].includes(f)?'checked':''}> ${f}
          </label>`).join('')}
        <button class="btn btn-ghost btn-sm" id="var-refresh-btn">Refresh</button>
        <button class="btn btn-primary btn-sm" id="var-push-aliased-btn">Push All Alias-Mapped</button>
        <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px">
          <input type="checkbox" id="var-hide-u-cb" checked> Hide "- U" titles
        </label>
        <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px">
          <input type="checkbox" id="var-show-tags-cb" checked> Show tags
        </label>
      </div>
      <div id="variances-list"></div>
      <div id="variances-pager"></div>`;
    document.getElementById('var-refresh-btn').addEventListener('click', () => { this.page = 1; this._fetchVariances(); });
    document.getElementById('var-push-aliased-btn').addEventListener('click', () => this._pushAllAliased());
    document.getElementById('var-hide-u-cb').addEventListener('change', () => { this.page = 1; this._fetchVariances(); });
    document.getElementById('var-show-tags-cb').addEventListener('change', () => this._fetchVariances());
    await this._fetchVariances();
  }

  async _pushAllAliased() {
    const btn = document.getElementById('var-push-aliased-btn');
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>';
    try {
      const fields = [...document.querySelectorAll('.var-field-cb:checked')].map(cb => cb.value);
      const qs = new URLSearchParams({ fields: fields.join(','), page: 1, per_page: 1000 });
      const data = await API.get(`/api/matching/variances?${qs}`);
      const updates = (data.items || [])
        .filter(p => p.diffs.artist?.via_alias)
        .map(p => ({ product_id: p.product_id, variant_id: p.variant_id, fields: { artist: p.diffs.artist.new } }));

      if (!updates.length) { Toast.info('No alias-mapped items to push'); return; }

      const result = await API.post('/api/products/push-variance-fields', { updates });
      if (result.dry_run) Toast.warning(`Dry run — would update ${result.would_update} products`);
      else {
        const ok = result.results.filter(r => r.ok).length;
        const fail = result.results.filter(r => !r.ok).length;
        Toast.success(`Pushed ${ok} alias-mapped artists${fail ? `, ${fail} failed` : ''}`);
      }
      await this._fetchVariances();
    } catch (e) {
      Toast.error(e.message);
    } finally {
      btn.disabled = false; btn.textContent = 'Push All Alias-Mapped';
    }
  }

  async _fetchVariances() {
    const el = document.getElementById('variances-list');
    if (!el) return;
    el.innerHTML = '<div style="color:var(--text-muted);font-size:13px">Loading…</div>';
    const fields = [...document.querySelectorAll('.var-field-cb:checked')].map(cb => cb.value);
    const hideU = document.getElementById('var-hide-u-cb')?.checked ?? true;
    try {
      const qs = new URLSearchParams({ fields: fields.join(','), page: this.page, per_page: 20, hide_u: hideU ? '1' : '0' });
      const data = await API.get(`/api/matching/variances?${qs}`);
      if (!data.items?.length) {
        el.innerHTML = `<div class="empty-state"><div class="empty-state-icon">✅</div><div class="empty-state-text">No variances found</div></div>`;
        return;
      }
      this.selectedVariances = new Set();
      el.innerHTML = `
        <div class="row" style="margin-bottom:12px;gap:8px;align-items:center">
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px">
            <input type="checkbox" id="var-select-all"> All
          </label>
          <span style="font-size:13px;color:var(--text-muted);flex:1">${data.total} products differ</span>
          <button class="btn btn-primary btn-sm" id="var-push-sel-btn" disabled>Push Selected</button>
        </div>
        <div id="var-items"></div>
        <div id="var-pager2"></div>`;
      const showTags = document.getElementById('var-show-tags-cb')?.checked ?? true;
      document.getElementById('var-items').innerHTML = data.items.map(p => this._varCard(p, showTags)).join('');

      document.querySelectorAll('.var-cb').forEach(cb => {
        cb.addEventListener('change', () => {
          if (cb.checked) this.selectedVariances.add(cb.dataset.id);
          else this.selectedVariances.delete(cb.dataset.id);
          this._updateVarBtn();
        });
      });

      document.querySelectorAll('.card[data-id]').forEach(card => {
        card.style.cursor = 'pointer';
        card.addEventListener('click', e => {
          if (e.target.closest('button') || e.target.tagName === 'INPUT' || e.target.tagName === 'IMG') return;
          const cb = card.querySelector('.var-cb');
          if (cb) { cb.checked = !cb.checked; cb.dispatchEvent(new Event('change')); }
        });
      });
      document.getElementById('var-select-all').addEventListener('change', e => {
        document.querySelectorAll('.var-cb').forEach(cb => {
          cb.checked = e.target.checked;
          if (e.target.checked) this.selectedVariances.add(cb.dataset.id);
          else this.selectedVariances.delete(cb.dataset.id);
        });
        this._updateVarBtn();
      });
      document.getElementById('var-push-sel-btn').addEventListener('click', () => this._pushVariances(data.items));
      document.querySelectorAll('.var-map-btn').forEach(btn =>
        btn.addEventListener('click', () => this._openMapModal(btn.dataset.old, btn.dataset.new)));
      document.querySelectorAll('.var-lock-title-btn').forEach(btn =>
        btn.addEventListener('click', async () => {
          try {
            await API.post('/api/products/title-override', { product_id: btn.dataset.product, correct_title: btn.dataset.title });
            Toast.success('Title locked');
            await this._fetchVariances();
          } catch (e) { Toast.error(e.message); }
        }));
      document.querySelectorAll('.var-ignore-btn').forEach(btn =>
        btn.addEventListener('click', async (e) => {
          e.stopPropagation();
          try {
            await API.post('/api/matching/variances/ignore', {
              product_id: btn.dataset.product, field: btn.dataset.field,
              old_value: btn.dataset.old, new_value: btn.dataset.new,
            });
            Toast.info('Ignored');
            await this._fetchVariances();
          } catch (e2) { Toast.error(e2.message); }
        }));

      buildPager(document.getElementById('var-pager2'), data, p => { this.page = p; this._fetchVariances(); });
    } catch (e) {
      el.innerHTML = `<div class="alert alert-error">${esc(e.message)}</div>`;
    }
  }

  _varCard(p, showTags = true) {
    const diffRows = Object.entries(p.diffs).filter(([field]) => showTags || field !== 'tags').map(([field, d]) => `
      <div style="font-size:12px;display:flex;gap:8px;padding:4px 0;align-items:center;border-bottom:1px solid var(--border)">
        <input type="checkbox" class="var-field-select" data-product="${esc(p.product_id)}" data-field="${field}" checked>
        <span style="width:60px;color:var(--text-muted);text-transform:capitalize">${field}</span>
        <span style="flex:1;color:var(--text-muted)">${esc(String(d.old ?? '—'))}</span>
        <span>→</span>
        <input class="input var-new-value" data-product="${esc(p.product_id)}" data-field="${field}"
          value="${esc(String(d.new ?? ''))}" style="flex:1;height:28px;font-size:12px;color:var(--green)">
        ${d.via_alias ? '<span class="badge badge-active" style="font-size:10px">via alias</span>' : ''}
        ${field === 'artist' ? `<button class="btn btn-ghost btn-sm var-map-btn" data-product="${esc(p.product_id)}"
          data-old="${esc(d.old||'')}" data-new="${esc(d.new||'')}">Map</button>` : ''}
        ${field === 'title' ? `<button class="btn btn-ghost btn-sm var-lock-title-btn" data-product="${esc(p.product_id)}"
          data-title="${esc(d.old||'')}">Lock as Correct</button>` : ''}
        <button class="btn btn-ghost btn-sm var-ignore-btn" data-product="${esc(p.product_id)}"
          data-field="${field}" data-old="${esc(d.old||'')}" data-new="${esc(d.new||'')}">Ignore</button>
      </div>`).join('');

    return `
      <div class="card" data-id="${esc(p.product_id)}" style="margin-bottom:12px">
        <div class="row center" style="margin-bottom:10px">
          <input type="checkbox" class="var-cb" data-id="${esc(p.product_id)}" style="margin-right:8px">
          <div style="font-weight:600;font-size:14px;flex:1">${esc(p.sp_title)}</div>
          <span class="mono" style="font-size:11px;color:var(--text-muted)">UPC: ${esc(p.webami_upc||'—')}</span>
        </div>
        <div class="match-panel" style="margin-bottom:10px">
          <div class="match-side">
            <div class="match-side-label">Shopify</div>
            <div class="row center" style="gap:10px">
              ${p.sp_image ? `<img class="match-img" src="${esc(p.sp_image)}" onerror="this.style.display='none'">` : '<div class="match-img" style="display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:22px">♫</div>'}
              <div>
                <div class="match-title">${esc(p.sp_title||'—')}</div>
                <div class="match-meta">${esc(p.sp_vendor||'—')}</div>
                <div class="match-meta">Cost: ${Fmt.price(p.sp_cost)} · Price: ${Fmt.price(p.sp_price)}</div>
                <div class="match-meta">Weight: ${p.sp_weight||'—'} ${esc(p.sp_weight_unit||'')}</div>
              </div>
            </div>
          </div>
          <div class="match-side">
            <div class="match-side-label">Webami</div>
            <div class="row center" style="gap:10px">
              <div>
                <div class="match-title">${esc(p.wp_title||'—')}</div>
                <div class="match-meta">${esc(p.wp_artist||'—')}</div>
                <div class="match-meta">Cost: ${Fmt.price(p.wp_cost)}</div>
                <div class="match-meta">Weight: ${p.wp_weight_grams ? (p.wp_weight_grams/453.592).toFixed(3) : '—'} lb</div>
              </div>
            </div>
          </div>
        </div>
        <div class="section-label" style="margin-bottom:6px">Fields to Update</div>
        ${diffRows}
      </div>`;
  }

  _openMapModal(oldVal, newVal) {
    const bodyEl = document.createElement('div');
    bodyEl.innerHTML = `
      <div class="input-group" style="margin-bottom:12px">
        <label class="input-label">Alias (Shopify vendor)</label>
        <input id="map-alias" class="input" value="${esc(oldVal)}">
      </div>
      <div class="input-group">
        <label class="input-label">Canonical (Webami artist)</label>
        <input id="map-canonical" class="input" value="${esc(newVal)}">
      </div>`;
    Modal.open({
      title: 'Create Artist Mapping',
      body: bodyEl,
      buttons: [
        { label: 'Cancel', cls: 'btn-ghost', onClick: Modal.close },
        { label: 'Save Mapping', cls: 'btn-primary', onClick: async () => {
          const alias = document.getElementById('map-alias').value.trim();
          const canonical = document.getElementById('map-canonical').value.trim();
          if (!alias || !canonical) { Toast.warning('Both fields required'); return; }
          try {
            await API.post('/api/aliases', { alias_name: alias, canonical_name: canonical });
            Toast.success('Mapping saved');
            Modal.close();
          } catch (e) { Toast.error(e.message); }
        }},
      ],
    });
  }

  _updateVarBtn() {
    const n = this.selectedVariances.size;
    const btn = document.getElementById('var-push-sel-btn');
    if (btn) { btn.disabled = !n; btn.textContent = n ? `Push Selected (${n})` : 'Push Selected'; }
  }

  async _pushVariances(items) {
    const selected = items.filter(p => this.selectedVariances.has(p.product_id));
    const itemMap = {};
    selected.forEach(p => { itemMap[p.product_id] = p; });

    // Build fields per product from checked field checkboxes
    const fieldsByProduct = {};
    document.querySelectorAll('.var-field-select:checked').forEach(cb => {
      const pid = cb.dataset.product;
      if (!itemMap[pid]) return; // product not selected overall
      fieldsByProduct[pid] = fieldsByProduct[pid] || {};
      const field = cb.dataset.field;
      const input = document.querySelector(`.var-new-value[data-product="${pid}"][data-field="${field}"]`);
      const val = input ? input.value.trim() : itemMap[pid].diffs[field]?.new;
      if (val !== undefined && val !== '') fieldsByProduct[pid][field] = val;
    });

    const updates = selected
      .filter(p => fieldsByProduct[p.product_id] && Object.keys(fieldsByProduct[p.product_id]).length)
      .map(p => ({ product_id: p.product_id, variant_id: p.variant_id, fields: fieldsByProduct[p.product_id] }));

    if (!updates.length) { Toast.warning('No fields selected to push'); return; }

    try {
      const data = await API.post('/api/products/push-variance-fields', { updates });
      if (data.dry_run) Toast.warning(`Dry run — would update ${data.would_update} products`);
      else {
        const ok = data.results.filter(r => r.ok).length;
        const fail = data.results.filter(r => !r.ok).length;
        Toast.success(`Updated ${ok} products${fail ? `, ${fail} failed` : ''}`);
      }
      this.selectedVariances.clear();
      await this._fetchVariances();
    } catch (e) { Toast.error(e.message); }
  }

  // ── Review Queue ──────────────────────────────────────────────

  async _loadQueue() {
    const el = document.getElementById('matching-content');
    el.innerHTML = '<div style="color:var(--text-muted);font-size:13px">Loading…</div>';
    try {
      const data = await API.get(`/api/matching/queue?page=${this.page}&per_page=20&hide_dash_u=${this.hideDashU ? '1' : '0'}`);
      if (!data.items?.length) {
        el.innerHTML = `
          <div style="display:flex;gap:8px;align-items:center;margin-bottom:16px;flex-wrap:wrap">
            <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px;color:var(--text-secondary)">
              <input type="checkbox" id="hide-dash-u-cb" ${this.hideDashU ? 'checked' : ''}> Hide "- U" titles
            </label>
          </div>
          <div class="empty-state">
            <div class="empty-state-icon">✅</div>
            <div class="empty-state-text">Review queue is empty</div>
          </div>`;
        document.getElementById('hide-dash-u-cb').addEventListener('change', e => {
          this.hideDashU = e.target.checked;
          this.page = 1;
          this._loadQueue();
        });
        return;
      }
      this.selected.clear();
      el.innerHTML = `
        <div style="display:flex;gap:8px;align-items:center;margin-bottom:16px;flex-wrap:wrap">
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px;color:var(--text-secondary)">
            <input type="checkbox" id="select-all-cb"> All
          </label>
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px;color:var(--text-secondary)">
            <input type="checkbox" id="hide-dash-u-cb" ${this.hideDashU ? 'checked' : ''}> Hide "- U" titles
          </label>
          <span id="queue-top-summary" style="font-size:13px;color:var(--text-muted);flex:1">${data.total} items need review</span>
          <button class="btn btn-success btn-sm" id="confirm-sel-btn" disabled>✓ Confirm Selected</button>
          <button class="btn btn-danger btn-sm" id="reject-sel-btn" disabled>✕ Reject Selected</button>
          <button class="btn btn-ghost btn-sm" id="confirm-all-btn">Confirm All on Page</button>
        </div>
        <div id="queue-items"></div>
        <div id="queue-pager"></div>`;

      document.getElementById('hide-dash-u-cb').addEventListener('change', e => {
        this.hideDashU = e.target.checked;
        this.page = 1;
        this._loadQueue();
      });

      const itemsEl = document.getElementById('queue-items');
      itemsEl.innerHTML = data.items.map((item, i) => this._queueCard(item, i)).join('');

      document.querySelectorAll('.queue-confirm').forEach(btn =>
        btn.addEventListener('click', () => this._confirm(btn.dataset.product, btn.dataset.upc)));
      document.querySelectorAll('.queue-reject').forEach(btn =>
        btn.addEventListener('click', () => this._reject(btn.dataset.product)));
      document.querySelectorAll('.queue-search').forEach(btn =>
        btn.addEventListener('click', () => this._searchModal(btn.dataset.product, btn.dataset.title, btn.dataset.format)));

      document.querySelectorAll('.queue-cb').forEach(cb => {
        cb.addEventListener('change', () => {
          if (cb.checked) this.selected.add(cb.dataset.product + '|' + cb.dataset.upc);
          else            this.selected.delete(cb.dataset.product + '|' + cb.dataset.upc);
          this._updateSelBtns();
          document.getElementById('select-all-cb').checked = this.selected.size === data.items.length;
        });
      });

      document.getElementById('select-all-cb').addEventListener('change', e => {
        document.querySelectorAll('.queue-cb').forEach(cb => {
          cb.checked = e.target.checked;
          if (e.target.checked) this.selected.add(cb.dataset.product + '|' + cb.dataset.upc);
          else                  this.selected.delete(cb.dataset.product + '|' + cb.dataset.upc);
        });
        this._updateSelBtns();
      });

      document.querySelectorAll('.match-panel').forEach(panel => {
        panel.style.cursor = 'pointer';
        panel.addEventListener('click', e => {
          if (e.target.closest('button') || e.target.tagName === 'INPUT' || e.target.tagName === 'IMG') return;
          const cb = panel.querySelector('.queue-cb');
          if (cb) { cb.checked = !cb.checked; cb.dispatchEvent(new Event('change')); }
        });
      });

      document.getElementById('confirm-all-btn').addEventListener('click', () =>
        this._confirmAll(data.items));
      document.getElementById('confirm-sel-btn').addEventListener('click', () =>
        this._confirmSelected());
      document.getElementById('reject-sel-btn').addEventListener('click', () =>
        this._rejectSelected());

      buildPager(document.getElementById('queue-pager'), data, p => { this.page = p; this._load(); }, 'queue-top-summary');
    } catch (e) {
      el.innerHTML = `<div class="alert alert-error">${esc(e.message)}</div>`;
    }
  }

  _queueCard(item, i) {
    const score = (item.score * 100).toFixed(0);
    const scoreClass = item.score >= 0.88 ? 'high' : 'medium';
    const sp_img = item.sp_image || '';
    const wp_img = item.wp_image || '';
    return `
      <div class="match-panel" data-idx="${i}">
        <div class="match-side">
          <div class="match-side-label" style="display:flex;align-items:center;gap:8px">
            <input type="checkbox" class="queue-cb" data-product="${esc(item.product_id)}" data-upc="${esc(item.webami_upc)}">
            Shopify
          </div>
          <div class="row center" style="gap:10px">
            ${sp_img ? `<img class="match-img" src="${esc(sp_img)}" onerror="this.style.display='none'">` : '<div class="match-img" style="display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:22px">♫</div>'}
            <div>
              <div class="match-title">${esc(item.sp_title || '—')}</div>
              <div class="match-meta">${esc(item.vendor || '—')} · ${esc(item.category_name || '—')}</div>
              <div class="match-meta">Cost: ${Fmt.price(item.sv_cost || '—')}</div>
              <div class="match-meta mono" style="font-size:11px">UPC: ${esc(item.upc || '—')}</div>
            </div>
          </div>
        </div>
        <div class="match-side">
          <div class="match-side-label">
            Webami suggestion
            <span class="match-score ${scoreClass}" style="margin-left:8px">${score}%</span>
          </div>
          <div class="row center" style="gap:10px">
            ${wp_img ? `<img class="match-img" src="${esc(wp_img)}" onerror="this.style.display='none'">` : '<div class="match-img" style="display:flex;align-items:center;justify-content:center;color:var(--text-muted);font-size:22px">♫</div>'}
            <div>
              <div class="match-title">${esc(item.wp_title || '—')}</div>
              <div class="match-meta">${esc(item.artist || '—')} · ${esc(item.format || '—')}</div>
              <div class="match-meta">Cost: ${Fmt.price(item.wp_cost || '—')}</div>
              <div class="match-meta mono" style="font-size:11px">UPC: ${esc(item.webami_upc || '—')}</div>
            </div>
          </div>
          <div class="match-actions">
            <button class="btn btn-success btn-sm queue-confirm" data-product="${esc(item.product_id)}" data-upc="${esc(item.webami_upc)}">✓ Confirm</button>
            <button class="btn btn-danger btn-sm queue-reject" data-product="${esc(item.product_id)}">✕ Reject</button>
            <button class="btn btn-ghost btn-sm queue-search" data-product="${esc(item.product_id)}" data-title="${esc(item.sp_title)}" data-format="${esc(item.format||'')}">Search…</button>
          </div>
        </div>
      </div>`;
  }

  async _confirm(productId, webamiUpc) {
    try {
      await API.post('/api/matching/confirm', { product_id: productId, webami_upc: webamiUpc });
      Toast.success('Match confirmed');
      await this._loadQueue();
    } catch (e) { Toast.error(e.message); }
  }

  async _reject(productId) {
    try {
      await API.post('/api/matching/reject', { product_id: productId });
      Toast.info('Match rejected');
      await this._loadQueue();
    } catch (e) { Toast.error(e.message); }
  }

  async _confirmAll(items) {
    let ok = 0;
    for (const item of items) {
      try {
        await API.post('/api/matching/confirm', { product_id: item.product_id, webami_upc: item.webami_upc });
        ok++;
      } catch (_) {}
    }
    Toast.success(`Confirmed ${ok} matches`);
    await this._loadQueue();
  }

  _searchModal(productId, title, format = '') {
    const bodyEl = document.createElement('div');
    bodyEl.innerHTML = `
      <div class="input-group" style="margin-bottom:12px">
        <label class="input-label">Search Webami by UPC or title</label>
        <div class="row">
          <input id="ws-input" class="input flex-1" placeholder="UPC or title…" value="${esc(title || '')}">
          <button id="ws-btn" class="btn btn-primary btn-sm">Fetch</button>
        </div>
      </div>
      <div id="ws-result"></div>`;

    Modal.open({
      title: 'Find Webami match',
      body:  bodyEl,
      buttons: [{ label: 'Cancel', cls: 'btn-ghost', onClick: Modal.close }],
    });

    const input = document.getElementById('ws-input');
    const resultEl = document.getElementById('ws-result');

    const doFetch = async () => {
      const q = input.value.trim();
      if (!q) return;
      resultEl.innerHTML = '<div style="color:var(--text-muted);font-size:13px">Fetching…</div>';
      try {
        const wp = await API.post('/api/webami/scrape', { upc: q, title: q, format});
        resultEl.innerHTML = `
          <div class="pending-item">
            <div class="item-info">
              <div class="item-title">${esc(wp.title || wp.upc)}</div>
              <div class="item-meta">${esc(wp.artist || wp.brand || '')} · ${esc(wp.format || '')} · ${Fmt.price(wp.cost)}</div>
            </div>
            <button class="btn btn-success btn-sm" id="ws-select">Select</button>
          </div>`;
        document.getElementById('ws-select').addEventListener('click', async () => {
          try {
            await API.post('/api/matching/confirm', { product_id: productId, webami_upc: wp.upc });
            Toast.success('Mapped!');
            Modal.close();
            await this._loadQueue();
          } catch (e) { Toast.error(e.message); }
        });
      } catch (e) {
        resultEl.innerHTML = `<div class="alert alert-error">${esc(e.message)}</div>`;
      }
    };

    document.getElementById('ws-btn').addEventListener('click', doFetch);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') doFetch(); });
  }

  // ── Duplicate Groups ──────────────────────────────────────────

  async _loadDupes() {
    const el = document.getElementById('matching-content');
    el.innerHTML = '<div style="color:var(--text-muted);font-size:13px">Loading…</div>';
    try {
      const data = await API.get(`/api/matching/duplicates?page=${this.page}`);
      if (!data.items?.length) {
        el.innerHTML = `
          <div class="empty-state">
            <div class="empty-state-icon">✅</div>
            <div class="empty-state-text">No pending duplicate groups</div>
          </div>`;
        return;
      }
      this.selectedDupes.clear();
      el.innerHTML = `
        <div style="display:flex;gap:8px;align-items:center;margin-bottom:16px;flex-wrap:wrap">
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px;color:var(--text-secondary)">
            <input type="checkbox" id="dupe-select-all"> All
          </label>
          <span id="dupe-top-summary" style="font-size:13px;color:var(--text-muted);flex:1">${data.total} groups pending</span>
          <button class="btn btn-ghost btn-sm" id="dismiss-sel-btn" disabled>Dismiss Selected</button>
          <button class="btn btn-primary btn-sm" id="merge-sel-btn" disabled>Mark Merged Selected</button>
        </div>
        <div id="dupe-items"></div>
        <div id="dupe-pager"></div>`;

      document.getElementById('dupe-items').innerHTML = data.items.map(g => this._dupeCard(g)).join('');

      document.querySelectorAll('.dupe-cb').forEach(cb => {
        cb.addEventListener('change', () => {
          if (cb.checked) this.selectedDupes.add(+cb.dataset.id);
          else            this.selectedDupes.delete(+cb.dataset.id);
          this._updateDupeBtns(data.items.length);
          document.getElementById('dupe-select-all').checked = this.selectedDupes.size === data.items.length;
        });
      });
      document.getElementById('dupe-select-all').addEventListener('change', e => {
        document.querySelectorAll('.dupe-cb').forEach(cb => {
          cb.checked = e.target.checked;
          if (e.target.checked) this.selectedDupes.add(+cb.dataset.id);
          else                  this.selectedDupes.delete(+cb.dataset.id);
        });
        this._updateDupeBtns(data.items.length);
      });
      document.querySelectorAll('.dupe-dismiss').forEach(btn =>
        btn.addEventListener('click', () => this._resolveDupe(btn.dataset.id, 'dismissed')));
      document.querySelectorAll('.dupe-merged').forEach(btn =>
        btn.addEventListener('click', () => this._resolveDupe(btn.dataset.id, 'merged')));
      document.getElementById('dismiss-sel-btn').addEventListener('click', () => this._resolveSelected('dismissed'));
      document.getElementById('merge-sel-btn').addEventListener('click', ()  => this._resolveSelected('merged'));

      document.querySelectorAll('.card[data-group-id]').forEach(card => {
        card.addEventListener('click', e => {
          if (e.target.closest('button') || e.target.tagName === 'INPUT' || e.target.tagName === 'IMG') return;
          const cb = card.querySelector('.dupe-cb');
          if (cb) { cb.checked = !cb.checked; cb.dispatchEvent(new Event('change')); }
        });
      });

      buildPager(document.getElementById('dupe-pager'), data, p => { this.page = p; this._load(); }, 'dupe-top-summary');
    } catch (e) {
      el.innerHTML = `<div class="alert alert-error">${esc(e.message)}</div>`;
    }
  }

  _dupeCard(group) {
    const members = group.members || [];
    return `
      <div class="card" data-group-id="${group.id}" style="margin-bottom:12px;cursor:pointer">
        <div class="row center" style="margin-bottom:12px">
          <input type="checkbox" class="dupe-cb" data-id="${group.id}" style="margin-right:6px;flex-shrink:0">
          <div style="font-size:12px;color:var(--text-muted)">Group #${group.id} · ${members.length} products · <span class="mono">${esc(group.normalized_key)}</span></div>
          <div style="flex:1"></div>
          <button class="btn btn-ghost btn-sm dupe-dismiss" data-id="${group.id}">Dismiss</button>
          <button class="btn btn-primary btn-sm dupe-merged" data-id="${group.id}">Mark Merged</button>
        </div>
        <div style="display:flex;gap:12px;flex-wrap:wrap">
          ${members.map(m => `
            <div style="flex:1;min-width:160px;padding:12px;background:var(--bg-raised);border-radius:8px">
              ${m.image_url ? `<img src="${esc(m.image_url)}" style="width:100%;height:80px;object-fit:cover;border-radius:4px;margin-bottom:8px">` : ''}
              <div style="font-size:13px;font-weight:600">${esc(m.title)}</div>
              <div style="font-size:12px;color:var(--text-muted);margin-top:2px">${esc(m.vendor || '—')} · ${statusBadge(m.status)}</div>
              <div style="font-size:12px;color:var(--text-muted);margin-top:2px">
                ${m.format ? `<span class="badge badge-draft" style="font-size:10px">${esc(m.format)}</span> ` : ''}
                ${m.category_name ? `<span class="badge badge-active" style="font-size:10px">${esc(m.category_name)}</span>` : ''}
              </div>
              <div style="font-size:12px;margin-top:4px;display:flex;gap:12px">
                <span>Price: <b>${Fmt.price(m.price)}</b></span>
                <span>Cost: <b>${Fmt.price(m.webami_cost || m.cost)}</b></span>
                <span>Qty: <b>${Fmt.qty(m.inventory_quantity)}</b></span>
              </div>
              ${m.tags ? `<div style="font-size:11px;color:var(--text-muted);margin-top:4px;white-space:normal">${esc(m.tags)}</div>` : ''}
            </div>`).join('')}
        </div>
      </div>`;
  }

  async _resolveDupe(groupId, action) {
    try {
      await API.post(`/api/matching/duplicates/${groupId}/resolve`, { action });
      Toast.success(action === 'dismissed' ? 'Dismissed' : 'Marked as merged');
      await this._loadDupes();
    } catch (e) { Toast.error(e.message); }
  }

  _updateDupeBtns(total) {
    const n = this.selectedDupes.size;
    const db = document.getElementById('dismiss-sel-btn');
    const mb = document.getElementById('merge-sel-btn');
    if (db) { db.disabled = !n; db.textContent = n ? `Dismiss (${n})` : 'Dismiss Selected'; }
    if (mb) { mb.disabled = !n; mb.textContent = n ? `Mark Merged (${n})` : 'Mark Merged Selected'; }
  }

  async _resolveSelected(action) {
    let ok = 0;
    for (const id of [...this.selectedDupes]) {
      try { await API.post(`/api/matching/duplicates/${id}/resolve`, { action }); ok++; } catch(_) {}
    }
    Toast.success(`${action === 'dismissed' ? 'Dismissed' : 'Marked merged'} ${ok} groups`);
    this.selectedDupes.clear();
    await this._loadDupes();
  }

  _updateSelBtns() {
    const n = this.selected.size;
    const cb = document.getElementById('confirm-sel-btn');
    const rb = document.getElementById('reject-sel-btn');
    if (cb) { cb.disabled = !n; cb.textContent = n ? `✓ Confirm (${n})` : '✓ Confirm Selected'; }
    if (rb) { rb.disabled = !n; rb.textContent = n ? `✕ Reject (${n})`  : '✕ Reject Selected'; }
  }

  async _confirmSelected() {
    const btn = document.getElementById('confirm-sel-btn');
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>'; }
    let ok = 0;
    for (const entry of [...this.selected]) {
      const [product_id, webami_upc] = entry.split('|');
      try { await API.post('/api/matching/confirm', { product_id, webami_upc }); ok++; } catch(_) {}
    }
    Toast.success(`Confirmed ${ok} matches`);
    this.selected.clear();
    await this._loadQueue();
  }

  async _rejectSelected() {
    const btn = document.getElementById('reject-sel-btn');
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>'; }
    let ok = 0;
    for (const entry of [...this.selected]) {
      const product_id = entry.split('|')[0];
      try { await API.post('/api/matching/reject', { product_id }); ok++; } catch(_) {}
    }
    Toast.info(`Rejected ${ok} matches`);
    this.selected.clear();
    await this._loadQueue();
  }

  // ── Missing Fields ───────────────────────────────────────────

  async _loadMissing() {
    const el = document.getElementById('matching-content');
    el.innerHTML = `
      <div class="row" style="margin-bottom:16px;align-items:center;gap:10px">
        <span style="font-size:13px;color:var(--text-muted)">Filter by missing field:</span>
        <select id="field-filter" class="select" style="max-width:180px">
          <option value="">All</option>
          ${['title','vendor','product_type','category','images','cost','price','weight','weight_unit','upc','genre']
            .map(f => `<option value="${f}" ${this.fieldFilter===f?'selected':''}>${f.replace('_',' ')}</option>`).join('')}
        </select>
      </div>
      <div id="missing-list"></div>
      <div id="missing-pager"></div>`;
    document.getElementById('field-filter').addEventListener('change', e => {
      this.fieldFilter = e.target.value; this.page = 1; this._fetchMissing();
    });
    await this._fetchMissing();
  }

  async _fetchMissing() {
    const el = document.getElementById('missing-list');
    if (!el) return;
    el.innerHTML = '<div style="color:var(--text-muted);font-size:13px">Loading…</div>';
    try {
      const mfqs = new URLSearchParams({ page:this.page, per_page:20, field:this.fieldFilter||'',
        sort:this.mfSort, q_title:this.mfColFilters.title||'', q_vendor:this.mfColFilters.vendor||'',
        status:this.mfColFilters.pstatus||'', q_category:this.mfColFilters.category||'' });
      const data = await API.get(`/api/matching/missing-fields?${mfqs}`);      if (!data.items?.length) {
        el.innerHTML = `<div class="empty-state"><div class="empty-state-icon">✅</div><div class="empty-state-text">No products with missing fields</div></div>`;
        return;
      }
      el.innerHTML = `
        <div style="display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap">
          <span id="missing-top-summary" style="font-size:13px;color:var(--text-muted);flex:1">${data.total} products with missing fields</span>
          <button class="btn btn-primary btn-sm" id="mf-pull-sel-btn" disabled>Pull Webami Selected</button>
        </div>
        <div class="table-wrap">
          <table>
            <colgroup>${MISSING_COLS.map(c=>`<col style="width:${MISSING_COL_WIDTHS[c.id]?MISSING_COL_WIDTHS[c.id]+'px':'auto'}">`).join('')}</colgroup>
            <thead id="mf-thead"></thead>
            <tbody>${data.items.map(p => this._missingRow(p)).join('')}</tbody>
          </table>
        </div>`;

      const mfCols = MISSING_COLS.map((c,i) => i===0 ? {...c, label:'<input type="checkbox" id="mf-select-all">'} : c);
      buildSortableHead(document.getElementById('mf-thead'), mfCols, this.mfSort, this.mfColFilters,
        s => { this.mfSort = s; this.page = 1; this._fetchMissing(); },
        (col, val) => { this.mfColFilters[col] = val; this.page = 1; this._fetchMissing(); });

      this._selectedMissing = new Set();
      const _updateMfBtns = () => {
        const n = this._selectedMissing.size;
        const pb = document.getElementById('mf-pull-sel-btn');
        if (pb) { pb.disabled = !n; pb.textContent = n ? `Pull Webami (${n})` : 'Pull Webami Selected'; }
      };
      el.querySelectorAll('.mf-cb').forEach(cb => {
        cb.addEventListener('change', () => {
          if (cb.checked) this._selectedMissing.add(cb.dataset.id);
          else            this._selectedMissing.delete(cb.dataset.id);
          _updateMfBtns();
          document.getElementById('mf-select-all').checked = this._selectedMissing.size === data.items.length;
        });
      });
      document.getElementById('mf-select-all')?.addEventListener('change', e => {
        el.querySelectorAll('.mf-cb').forEach(cb => {
          cb.checked = e.target.checked;
          if (e.target.checked) this._selectedMissing.add(cb.dataset.id);
          else                  this._selectedMissing.delete(cb.dataset.id);
        });
        _updateMfBtns();
      });

      document.getElementById('mf-pull-sel-btn')?.addEventListener('click', async () => {
        const ids = [...this._selectedMissing];
        const allItems = data.items.filter(p => ids.includes(p.product_id));
        if (!allItems.length) return;
        // reuse single-item confirmation modal but apply to all selected
        const fields = ['title','vendor','upc','genre','weight','price','images'];
        const bodyEl = document.createElement('div');
        bodyEl.innerHTML = `
          <p style="font-size:13px;color:var(--text-secondary);margin-bottom:12px">Push to ${ids.length} product(s):</p>
          <div style="display:flex;flex-wrap:wrap;gap:8px">
            ${fields.map(f => `
              <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px;
                padding:6px 12px;background:var(--bg-raised);border-radius:var(--radius-sm);border:1px solid var(--border-light)">
                <input type="checkbox" id="mpw-${f}" checked> ${f}
              </label>`).join('')}
          </div>`;
        Modal.open({ title: 'Pull from Webami', body: bodyEl, buttons: [
          { label: 'Cancel', cls: 'btn-ghost', onClick: Modal.close },
          { label: `Push to ${ids.length} Products`, cls: 'btn-primary', onClick: async () => {
            const push = {};
            fields.forEach(f => { push[f] = document.getElementById(`mpw-${f}`)?.checked ?? true; });
            Modal.close();
            let ok = 0, errs = 0;
            for (const p of allItems) {
              try { await API.post('/api/products/push-webami-data', { product_id: p.product_id, push }); ok++; }
              catch(_) { errs++; }
            }
            Toast.success(`Pushed ${ok} products${errs ? `, ${errs} errors` : ''}`);
            this._selectedMissing.clear();
            await this._fetchMissing();
          }},
        ]});
      });

      el.querySelectorAll('tbody tr').forEach(row => {
        row.style.cursor = 'pointer';
        row.addEventListener('click', e => {
          if (e.target.closest('button') || e.target.tagName === 'INPUT') return;
          const cb = row.querySelector('.mf-cb');
          if (cb) { cb.checked = !cb.checked; cb.dispatchEvent(new Event('change')); }
        });
      });

      el.querySelectorAll('.pull-webami-btn').forEach(btn =>
        btn.addEventListener('click', () => this._pullWebami(btn.dataset.id)));
      el.querySelectorAll('.edit-fields-btn').forEach(btn =>
        btn.addEventListener('click', () => this._editFields(data.items.find(p => p.product_id === btn.dataset.id))));
      buildPager(document.getElementById('missing-pager'), data, p => { this.page = p; this._fetchMissing(); }, 'mf-top-summary');
    } catch(e) {
      el.innerHTML = `<div class="alert alert-error">${esc(e.message)}</div>`;
    }
  }

  async _loadUnmatched() {
    const el = document.getElementById('matching-content');
    el.innerHTML = `
      <div id="unmatched-top-summary" style="font-size:13px;color:var(--text-muted);margin-bottom:6px"></div>
      <div class="table-wrap">
        <table>
          <colgroup>${UNMATCHED_COLS.map(c=>`<col style="width:${UNMATCHED_COL_W[c.id]||100}px">`).join('')}</colgroup>
          <thead id="unmatched-thead"></thead>
          <tbody id="unmatched-body"><tr><td colspan="${UNMATCHED_COLS.length}" style="text-align:center;padding:24px;color:var(--text-muted)">Loading…</td></tr></tbody>
        </table>
      </div>
      <div id="unmatched-pager"></div>`;
    await this._fetchUnmatched();
  }

  async _fetchUnmatched() {
    const body  = document.getElementById('unmatched-body');
    const thead = document.getElementById('unmatched-thead');
    if (!body || !thead) return;
    buildSortableHead(thead, UNMATCHED_COLS, this.umSort, this.umColFilters,
      s => { this.umSort = s; this.page = 1; this._fetchUnmatched(); },
      (col, val) => { this.umColFilters[col] = val; this.page = 1; this._fetchUnmatched(); });
    body.innerHTML = `<tr><td colspan="${UNMATCHED_COLS.length}" style="text-align:center;padding:24px;color:var(--text-muted)">Loading…</td></tr>`;
    try {
      const qs = new URLSearchParams({
        page: String(this.page), per_page: '20', sort: this.umSort,
        q_title:    this.umColFilters.title    || '',
        q_vendor:   this.umColFilters.vendor   || '',
        q_category: this.umColFilters.category || '',
      });
      const data = await API.get(`/api/matching/unmatched?${qs}`);
      if (!data.items?.length) {
        body.innerHTML = `<tr><td colspan="${UNMATCHED_COLS.length}" style="text-align:center;padding:32px;color:var(--text-muted)">No unmatched products</td></tr>`;
        buildPager(document.getElementById('unmatched-pager'), data, p => { this.page = p; this._fetchUnmatched(); }, 'unmatched-top-summary');
        return;
      }
      body.innerHTML = data.items.map(p => `
        <tr>
          <td class="cell-truncate" style="text-align:left" title="${esc(p.title||'')}">${esc(p.title||'—')}</td>
          <td class="cell-truncate" style="text-align:left">${esc(p.vendor||'—')}</td>
          <td class="cell-truncate" style="text-align:left">${esc(p.category_name||'—')}</td>
          <td style="text-align:right">${Fmt.price(p.cost)}</td>
          <td>
            <div class="row center" style="gap:6px;justify-content:center">
              <input class="input" id="um-upc-${esc(p.product_id)}" placeholder="Enter UPC" style="width:160px">
            <button class="btn btn-success btn-sm um-match-btn" data-product="${esc(p.product_id)}"
              data-title="${esc(p.title||'')}" data-vendor="${esc(p.vendor||'')}" data-format="${esc(p.category_name||'')}">Match</button>
            <button class="btn btn-ghost btn-sm um-search-btn" data-product="${esc(p.product_id)}"
              data-title="${esc(p.title||'')}" data-vendor="${esc(p.vendor||'')}" data-format="${esc(p.category_name||'')}">Search Webami</button>
            <button class="btn btn-ghost btn-sm um-ignore-btn" data-product="${esc(p.product_id)}">No Match</button>
          </div>`).join('');
      document.querySelectorAll('.um-match-btn').forEach(btn =>
        btn.addEventListener('click', () => this._matchUnmatched(btn.dataset.product)));
      document.querySelectorAll('.um-search-btn').forEach(btn =>
        btn.addEventListener('click', () => this._searchUnmatched(btn.dataset.product, btn.dataset.title, btn.dataset.vendor, btn.dataset.format)));
      document.querySelectorAll('.um-ignore-btn').forEach(btn =>
        btn.addEventListener('click', async () => {
          try {
            await API.post('/api/products/ignore-unmatched', { product_id: btn.dataset.product });
            Toast.success('Marked as no match');
            await this._loadUnmatched();
          } catch (e) { Toast.error(e.message); }
        }));
      buildPager(document.getElementById('unmatched-pager'), data, p => { this.page = p; this._fetchUnmatched(); }, 'unmatched-top-summary');
    } catch (e) {
      body.innerHTML = `<tr><td colspan="${UNMATCHED_COLS.length}" style="color:var(--red);padding:16px">${esc(e.message)}</td></tr>`;
    }
  }

  async _matchUnmatched(productId) {
    const input = document.getElementById(`um-upc-${productId}`);
    const upc = input?.value.trim();
    if (!upc) { Toast.warning('Enter a UPC'); return; }
    try {
      const wp = await API.post('/api/webami/scrape', { upc });
      await API.post('/api/matching/confirm', { product_id: productId, webami_upc: wp.upc });
      Toast.success('Matched!');
      await this._fetchUnmatched();
    } catch (e) {
      const forceIt = confirm(`UPC not found on Webami. Set it anyway without verification?`);
      if (!forceIt) return;
      try {
        await API.post('/api/products/force-map', { product_id: productId, webami_upc: upc });
        Toast.success('UPC set (unverified)');
        await this._fetchUnmatched();
      } catch (e2) { Toast.error(e2.message); }
    }
  }

  _searchUnmatched(productId, title, vendor, format) {
    const bodyEl = document.createElement('div');
    bodyEl.innerHTML = `
      <div class="input-group" style="margin-bottom:12px">
        <label class="input-label">Search Webami by title</label>
        <div class="row">
          <input id="usw-input" class="input flex-1" value="${esc(title || '')}">
          <button id="usw-btn" class="btn btn-primary btn-sm">Search</button>
        </div>
      </div>
      <div id="usw-result"></div>`;

    Modal.open({
      title: 'Search Webami',
      body: bodyEl,
      buttons: [{ label: 'Cancel', cls: 'btn-ghost', onClick: Modal.close }],
    });

    const input = document.getElementById('usw-input');
    const resultEl = document.getElementById('usw-result');

    const doSearch = async () => {
      const q = input.value.trim();
      if (!q) return;
      resultEl.innerHTML = '<div style="color:var(--text-muted);font-size:13px">Searching…</div>';
      try {
        const qs = new URLSearchParams({ title: q, artist: vendor || '', format: format || '' });
        const wp = await API.get(`/api/webami/search?${qs}`);
        resultEl.innerHTML = `
          <div class="pending-item">
            <div class="item-info">
              <div class="item-title">${esc(wp.title || wp.upc)}</div>
              <div class="item-meta">${esc(wp.artist || wp.brand || '')} · ${esc(wp.format || '')} · ${Fmt.price(wp.cost)}</div>
            </div>
            <button class="btn btn-success btn-sm" id="usw-select">Select</button>
          </div>`;
        document.getElementById('usw-select').addEventListener('click', async () => {
          try {
            await API.post('/api/matching/confirm', { product_id: productId, webami_upc: wp.upc });
            Toast.success('Matched!');
            Modal.close();
            await this._fetchUnmatched();
          } catch (e) { Toast.error(e.message); }
        });
      } catch (e) {
        resultEl.innerHTML = `<div class="alert alert-error">${esc(e.message)}</div>`;
      }
    };

    document.getElementById('usw-btn').addEventListener('click', doSearch);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') doSearch(); });
  }

  _missingRow(p) {
    const flags = [
      ['missing_title','title'], ['missing_vendor','vendor'],
      ['missing_product_type','product type'], ['missing_category','category'],
      ['missing_images','images'], ['missing_cost','cost'],
      ['missing_price','price'], ['missing_weight','weight'],
      ['missing_weight_unit','weight unit'],
      ['missing_upc','upc'], ['missing_genre','genre'],
    ].filter(([k]) => p[k]).map(([,label]) =>
      `<span class="badge badge-used" style="font-size:10px;margin:1px">${label}</span>`).join('');
    const hasMatch = p.map_status === 'active' && p.webami_upc;
    return `
      <tr>
        <td style="width:32px;text-align:center"><input type="checkbox" class="mf-cb" data-id="${esc(p.product_id)}"></td>
        <td class="col-thumb">${p.image_url
          ? `<img class="product-thumb" src="${esc(p.image_url)}" onerror="this.style.display='none'">`
          : '<div class="product-thumb-placeholder">♫</div>'}</td>
        <td class="cell-truncate" title="${esc(p.title||'')}">${esc(p.title||'—')}</td>
        <td class="cell-truncate" title="${esc(p.vendor||'')}">${esc(p.vendor||'—')}</td>
        <td style="text-align:center"><span class="badge ${p.status==='ACTIVE'?'badge-active':'badge-draft'}" style="font-size:10px">${esc(p.status||'—')}</span></td>
        <td class="cell-truncate" title="${esc(p.category_name||'')}">${esc(p.category_name||'—')}</td>
        <td style="overflow:visible;white-space:normal;padding:8px 14px">${flags}</td>
        <td style="overflow:visible">
          <div style="display:flex;gap:4px;justify-content:center">
            ${hasMatch ? `<button class="btn btn-primary btn-sm pull-webami-btn" data-id="${esc(p.product_id)}">Pull Webami</button>` : ''}
            <button class="btn btn-ghost btn-sm edit-fields-btn" data-id="${esc(p.product_id)}">Edit</button>
          </div>
        </td>
      </tr>`;
  }

  _pullWebami(productId) {
    const fields = ['title','vendor','upc','genre','weight','price','images'];
    const bodyEl = document.createElement('div');
    bodyEl.innerHTML = `
      <p style="font-size:13px;color:var(--text-secondary);margin-bottom:12px">Select fields to push from Webami:</p>
      <div style="display:flex;flex-wrap:wrap;gap:8px">
        ${fields.map(f => `
          <label style="display:flex;align-items:center;gap:6px;cursor:pointer;font-size:13px;
            padding:6px 12px;background:var(--bg-raised);border-radius:var(--radius-sm);border:1px solid var(--border-light)">
            <input type="checkbox" id="pw-${f}" checked> ${f}
          </label>`).join('')}
      </div>`;
    Modal.open({
      title: 'Pull from Webami',
      body: bodyEl,
      buttons: [
        { label: 'Cancel', cls: 'btn-ghost', onClick: Modal.close },
        { label: 'Push to Shopify', cls: 'btn-primary', onClick: () => {
          const push = {};
          fields.forEach(f => { push[f] = document.getElementById(`pw-${f}`)?.checked ?? true; });
          Modal.close();
          this._doPullWebami(productId, push);
        }},
      ],
    });
  }

  async _doPullWebami(productId, push) {
    try {
      const data = await API.post('/api/products/push-webami-data', { product_id: productId, push });
      if (data.dry_run) Toast.warning('Dry run — nothing pushed');
      else if (data.errors?.length) Toast.warning('Partial: ' + data.errors.join('; '));
      else Toast.success('Webami data pushed to Shopify');
      await this._fetchMissing();
    } catch(e) { Toast.error(e.message); }
  }

  _editFields(p) {
    if (!p) return;
    const bodyEl = document.createElement('div');
    bodyEl.innerHTML = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
        <div class="input-group">
          <label class="input-label">Title</label>
          <input id="ef-title" class="input" value="${esc(p.title||'')}">
        </div>
        <div class="input-group">
          <label class="input-label">Vendor</label>
          <input id="ef-vendor" class="input" value="${esc(p.vendor||'')}">
        </div>
        <div class="input-group">
          <label class="input-label">Product Type</label>
          <input id="ef-type" class="input" value="${esc(p.product_type||'')}">
        </div>
        <div class="input-group">
          <label class="input-label">Category</label>
          <select id="ef-category" class="select">
            <option value="">—</option>
            ${ALLOWED_CATEGORIES.map(([name]) =>
              `<option value="${esc(name)}" ${p.category_name===name?'selected':''}>${esc(name)}</option>`).join('')}
          </select>
        </div>
        <div class="input-group">
          <label class="input-label">Price</label>
          <input id="ef-price" class="input" type="number" step="0.01" value="${esc(p.price||'')}">
        </div>
        <div class="input-group">
          <label class="input-label">Weight</label>
          <input id="ef-weight" class="input" type="number" step="0.01" value="${esc(p.weight||'')}">
        </div>
        <div class="input-group">
          <label class="input-label">Weight Unit</label>
          <select id="ef-weight-unit" class="select">
            <option value="">—</option>
            ${['GRAMS','KILOGRAMS','OUNCES','POUNDS'].map(u =>
              `<option value="${u}" ${(p.weight_unit||'').toUpperCase()===u?'selected':''}>${u}</option>`).join('')}
          </select>
        </div>
      </div>`;
    Modal.open({
      title: 'Edit — ' + esc(p.title || p.product_id),
      body: bodyEl,
      buttons: [
        { label: 'Cancel', cls: 'btn-ghost', onClick: Modal.close },
        { label: 'Save & Push', cls: 'btn-primary', onClick: () => this._saveFields(p) },
      ],
    });
  }

  async _saveFields(p) {
    const payload = { product_id: p.product_id, variant_id: p.variant_id };
    const title  = document.getElementById('ef-title')?.value.trim();
    const vendor = document.getElementById('ef-vendor')?.value.trim();
    const type   = document.getElementById('ef-type')?.value.trim();
    const category = document.getElementById('ef-category')?.value.trim();
    const price  = document.getElementById('ef-price')?.value.trim();
    const weight = document.getElementById('ef-weight')?.value.trim();
    const wunit  = document.getElementById('ef-weight-unit')?.value;
    if (title)  payload.title        = title;
    if (vendor) payload.vendor       = vendor;
    if (type)   payload.product_type = type;
    if (category) payload.category_name = category
    if (price)  payload.price        = parseFloat(price);
    if (weight) payload.weight       = parseFloat(weight);
    if (wunit)  payload.weight_unit  = wunit;
    try {
      const data = await API.post('/api/products/update-fields', payload);
      if (data.dry_run) Toast.warning('Dry run — nothing pushed');
      else Toast.success('Fields updated in Shopify');
      Modal.close();
      await this._fetchMissing();
    } catch(e) { Toast.error(e.message); }
  }
}
