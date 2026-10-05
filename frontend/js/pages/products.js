const PRODUCT_COLS = [
  { id:'thumb',    label:'',               always:true, default:true,  sortKey:null,
    tdFn: p => thumb(p.image_url, p.title) },
  { id:'title',    label:'Title',          always:true, default:true,  sortKey:'title',
    filterable:true, filterKey:'title',
    tdFn: p => truncCell(p.title) },
  { id:'vendor',   label:'Vendor / Artist',             default:true,  sortKey:'vendor',
    filterable:true, filterKey:'vendor',
    tdFn: p => p.vendor ? truncCell(p.vendor) : `<span title="From Webami">${truncCell(p.artist)} <span class="badge badge-active" style="font-size:9px">W</span></span>` },
  { id:'upc',      label:'UPC',               default:false, sortKey:'upc',
    thStyle:'text-align:center', tdStyle:'text-align:center',
    filterable:true, filterKey:'upc',
    tdFn: p => `<span class="mono" style="font-size:11px">${esc(p.upc||'—')}</span>` },
  { id:'format',   label:'Format',                      default:false, sortKey:'format',
    filterable:true, filterType:'select', filterKey:'format',
    options:['LP','CD','Cassette','7" Single','12" Single','Vinyl Accessories'],
    tdFn: p => esc(p.format||'—') },
  { id:'category', label:'Category',                    default:false, sortKey:'category',
    filterable:true, filterKey:'category', filterType:'select', options:[],
    tdFn: p => truncCell(p.category_name) },
  { id:'ptype',    label:'Product Type',                 default:false, sortKey:null,
    filterable:true, filterKey:'ptype', filterType:'select', options:[],
    tdFn: p => truncCell(p.product_type) },
  { id:'tags',     label:'Tags',                         default:false, sortKey:null,
    filterable:true, filterKey:'tags',
    tdFn: p => truncCell(p.tags) },
  { id:'genres',   label:'Genres',                       default:false, sortKey:null,
    filterable:true, filterKey:'genres',
    tdFn: p => truncCell(p.genres) },
  { id:'cost',     label:'Cost',                        default:true, sortKey:'cost',
    thStyle:'text-align:right', tdStyle:'text-align:right',
    filterable:true, filterKey:'q_cost',
    tdFn: p => p.cost ? Fmt.price(p.cost) : (p.webami_cost ? `${Fmt.price(p.webami_cost)} <span class="badge badge-active" style="font-size:9px">W</span>` : '—') },
  { id:'price',    label:'Price / Target',              default:true,  sortKey:'price',
    thStyle:'text-align:right', tdStyle:'text-align:right',
    filterable:true, filterKey:'q_price',
    tdFn: p => {
      const price = parseFloat(p.price||0);
      const sugg  = p.suggested_price;
      return `${price ? Fmt.price(price) : '—'}${sugg ? `<br><span style="font-size:11px;color:var(--text-muted)">→ ${Fmt.price(sugg)}</span>` : ''}`;
    }},
  { id:'qty',      label:'Qty',                         default:true,  sortKey:'qty',
    thStyle:'text-align:center', tdStyle:'text-align:center',
    filterable:true, filterKey:'q_qty',
    tdFn: p => Fmt.qty(p.inventory_quantity) },
  { id:'pstatus',  label:'Status',                      default:false, sortKey:null,
    filterable:true, filterType:'select', filterKey:'status',
    options:['ACTIVE','DRAFT','ARCHIVED'],
    tdFn: p => statusBadge(p.status) },
  { id:'mapped',   label:'Mapped',         always:true, default:true,  sortKey:'mapped',
    filterable:true, filterType:'select', filterKey:'mapped',
    options:['mapped','pending','unmatched'],
    tdFn: p => mapStatusBadge(p.map_status, p.confidence) },
  { id:'actions',  label:'',               always:true, default:true,  sortKey:null,
    tdFn: p => `<button class="btn btn-ghost btn-sm view-btn" data-id="${esc(p.product_id)}">View</button>` },
];

const COL_WIDTHS = {
  thumb:48, title:210, vendor:140, upc:130, format:80, category:120,
  cost:70, price:120, qty:55, pstatus:80, mapped:90, actions:60,
  ptype:130, tags:160, genres:120,
};

const ALLOWED_CATEGORIES = [
  ["Apparel & Accessories", "gid://shopify/TaxonomyCategory/aa"],
  ["Home & Garden > Kitchen & Dining > Barware > Coasters", "gid://shopify/TaxonomyCategory/hg-11-1-8"],
  ["Arts & Entertainment > Hobbies & Creative Arts > Arts & Crafts > Art & Crafting Materials > Embellishments & Trims > Decorative Stickers", "gid://shopify/TaxonomyCategory/ae-2-1-2-8-4"],
  ["Gift Cards", "gid://shopify/TaxonomyCategory/gc"],
  ["Home & Garden > Decor > Seasonal & Holiday Decorations > Holiday Ornaments", "gid://shopify/TaxonomyCategory/hg-3-58-7"],
  ["Furniture > Cabinets & Storage > Media Storage Cabinets & Racks", "gid://shopify/TaxonomyCategory/fr-4-10"],
  ["Media > Music & Sound Recordings > Music CDs", "gid://shopify/TaxonomyCategory/me-3-3"],
  ["Media > Music & Sound Recordings > Music Cassette Tapes", "gid://shopify/TaxonomyCategory/me-3-2"],
  ["Office Supplies > General Office Supplies > Paper Products > Notebooks & Notepads", "gid://shopify/TaxonomyCategory/os-4-9-9"],
  ["Home & Garden > Smoking Accessories", "gid://shopify/TaxonomyCategory/hg-19"],
  ["Electronics > Audio > Audio Components > Speakers", "gid://shopify/TaxonomyCategory/el-2-2-10"],
  ["Electronics > Audio > Audio Accessories > Turntable Accessories", "gid://shopify/TaxonomyCategory/el-2-1-9"],
  ["Electronics > Audio > Audio Players & Recorders > Turntables & Record Players", "gid://shopify/TaxonomyCategory/el-2-3-10"],
  ["Media > Music & Sound Recordings > Vinyl", "gid://shopify/TaxonomyCategory/me-3-6"]
];

const LS_COLS = 'products_hidden_cols_v2';
const LS_SORT = 'products_sort';

function getHiddenCols() {
  try {
    const stored = localStorage.getItem(LS_COLS);
    if (stored !== null) return new Set(JSON.parse(stored));
  } catch {}
  // First visit — default hidden = cols where default:false
  return new Set(PRODUCT_COLS.filter(c => !c.default && !c.always).map(c => c.id));
}
function saveHiddenCols(s) { localStorage.setItem(LS_COLS, JSON.stringify([...s])); }
function getSavedSort()    { return localStorage.getItem(LS_SORT) || 'title_asc'; }
function saveSort(s)       { localStorage.setItem(LS_SORT, s); }

class ProductsPage {
  constructor() {
    this.page    = 1;
    this.filters = { q:'', status:'', mapped:'', format:'', title:'', vendor:'', upc:'', category:'', ptype:'', tags:'', genres:'' };
    this.sort    = getSavedSort();
    this.hidden  = getHiddenCols();
    this.filterOptions = { categories: [], product_types: [] };
  }

  async render(container) {
    container.innerHTML = `
      <div class="page">
        <div class="page-title">Shopify Products</div>

        <div id="products-top-summary" style="min-height:18px;margin-bottom:6px"></div>
        <div style="font-size:11px;color:var(--text-muted);margin-bottom:8px">
          <span class="badge badge-active" style="font-size:9px">W</span> = value from Webami (no Shopify value set)
        </div>
        <div class="search-row" style="flex-wrap:wrap;gap:8px;margin-bottom:16px">
          <input id="p-search" class="input" placeholder="Search title, vendor, UPC…" style="max-width:240px">
          <div style="position:relative;margin-left:auto">
            <button class="btn btn-ghost btn-sm" id="cols-btn">Columns ▾</button>
            <div id="cols-panel" style="display:none;position:absolute;right:0;top:36px;
              background:var(--bg-card);border:1px solid var(--border-light);border-radius:8px;
              padding:12px 16px;min-width:190px;z-index:100;box-shadow:var(--shadow-lg)">
              <div style="font-size:10px;color:var(--text-muted);margin-bottom:8px;font-weight:700;letter-spacing:.06em">COLUMNS</div>
              ${PRODUCT_COLS.filter(c => !c.always).map(c => `
                <label style="display:flex;align-items:center;gap:8px;cursor:pointer;padding:4px 0;font-size:13px">
                  <input type="checkbox" data-col="${c.id}" ${this.hidden.has(c.id)?'':'checked'}>
                  ${c.label}
                </label>`).join('')}
              <div style="border-top:1px solid var(--border);margin-top:8px;padding-top:8px">
                <button class="btn btn-ghost btn-sm" id="cols-reset" style="width:100%;font-size:11px">Reset to default</button>
              </div>
            </div>
          </div>
        </div>

        <div class="table-wrap">
          <table id="products-table">
            <colgroup id="products-colgroup"></colgroup>
            <thead id="products-thead"></thead>
            <tbody id="products-body">
              <tr><td colspan="${PRODUCT_COLS.length}" style="text-align:center;padding:32px;color:var(--text-muted)">Loading…</td></tr>
            </tbody>
          </table>
        </div>
        <div id="products-pager"></div>
      </div>`;

    this._renderColgroup();
    await this._loadFilterOptions();
    this._renderThead();
    this._bindFilters(container);
    this._bindCols(container);
    await this._load();
  }

  _renderColgroup() {
    const cg = document.getElementById('products-colgroup');
    if (!cg) return;
    cg.innerHTML = PRODUCT_COLS.map(c =>
      `<col style="width:${COL_WIDTHS[c.id]||80}px" data-col="${c.id}">`
    ).join('');
    this._applyColVisibility();
  }

  async _loadFilterOptions() {
    try {
      const data = await API.get('/api/products/filter-options');
      this.filterOptions = data;
      const catCol = PRODUCT_COLS.find(c => c.id === 'category');
      const typeCol = PRODUCT_COLS.find(c => c.id === 'ptype');
      if (catCol) catCol.options = data.categories || [];
      if (typeCol) typeCol.options = data.product_types || [];
    } catch (_) {}
  }

  _renderThead() {
    const thead = document.getElementById('products-thead');
    if (!thead) return;
    const colFilters = {};
    PRODUCT_COLS.forEach(c => { if (c.filterKey) colFilters[c.id] = this.filters[c.filterKey] || ''; });
    buildSortableHead(thead, PRODUCT_COLS, this.sort, colFilters,
      newSort => {
        this.sort = newSort;
        saveSort(this.sort); this.page = 1; this._renderThead(); this._load();
      },
      (colId, val) => {
        const c = PRODUCT_COLS.find(x => x.id === colId);
        if (c?.filterKey) { this.filters[c.filterKey] = val; this.page = 1; this._load(); }
      }
    );
    this._applyColVisibility();
  }

  _applyColVisibility() {
    document.querySelectorAll('[data-col]').forEach(el => {
      const col = PRODUCT_COLS.find(c => c.id === el.dataset.col);
      if (col && !col.always) el.style.display = this.hidden.has(col.id) ? 'none' : '';
    });
  }

  _bindCols(container) {
    const btn   = container.querySelector('#cols-btn');
    const panel = container.querySelector('#cols-panel');

    btn.addEventListener('click', e => {
      e.stopPropagation();
      panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
    });
    document.addEventListener('click', () => { if (panel) panel.style.display = 'none'; });
    panel.addEventListener('click', e => e.stopPropagation());

    panel.querySelectorAll('input[type=checkbox]').forEach(cb => {
      cb.addEventListener('change', () => {
        if (cb.checked) this.hidden.delete(cb.dataset.col);
        else            this.hidden.add(cb.dataset.col);
        saveHiddenCols(this.hidden);
        this._applyColVisibility();
      });
    });

    container.querySelector('#cols-reset').addEventListener('click', () => {
      localStorage.removeItem(LS_COLS);
      this.hidden = getHiddenCols();
      panel.querySelectorAll('input[type=checkbox]').forEach(cb => {
        cb.checked = !this.hidden.has(cb.dataset.col);
      });
      saveHiddenCols(this.hidden);
      this._applyColVisibility();
    });
  }

  _bindFilters(container) {
    const search = container.querySelector('#p-search');
    search.addEventListener('input', debounce(() => {
      this.filters.q = search.value; this.page = 1; this._load();
    }, 350));
  }

  async _load() {
    const body = document.getElementById('products-body');
    if (!body) return;
    body.innerHTML = `<tr><td colspan="${PRODUCT_COLS.length}" style="text-align:center;padding:24px;color:var(--text-muted)">Loading…</td></tr>`;

    const f  = this.filters;
    const qs = new URLSearchParams({
      page: String(this.page), per_page: '50', sort: this.sort,
      q: f.q, status: f.status, mapped: f.mapped, format: f.format,
      title: f.title, vendor: f.vendor, upc: f.upc,
      category: f.category, ptype: f.ptype, tags: f.tags, genres: f.genres,
    });
    try {
      const data = await API.get(`/api/products?${qs}`);
      this._renderRows(data.items);
      buildPager(document.getElementById('products-pager'), data,
        p => { this.page = p; this._load(); }, 'products-top-summary');
    } catch (e) {
      body.innerHTML = `<tr><td colspan="${PRODUCT_COLS.length}" style="text-align:center;padding:24px;color:var(--red)">${esc(e.message)}</td></tr>`;
    }
  }

  _renderRows(items) {
    const body = document.getElementById('products-body');
    if (!body) return;
    if (!items?.length) {
      body.innerHTML = `<tr><td colspan="${PRODUCT_COLS.length}" style="text-align:center;padding:32px;color:var(--text-muted)">No products found</td></tr>`;
      return;
    }
    body.innerHTML = items.map(p => `
      <tr data-id="${esc(p.product_id)}">
        ${PRODUCT_COLS.map(c => `
          <td data-col="${c.id}" style="${c.tdStyle||''}${this.hidden.has(c.id)&&!c.always?';display:none':''}">
            ${c.tdFn(p)}
          </td>`).join('')}
      </tr>`).join('');

    body.querySelectorAll('.view-btn').forEach(btn => {
      btn.addEventListener('click', e => { e.stopPropagation(); this._openDetail(btn.dataset.id); });
    });
  }

  // ── Detail modal ───────────────────────────────────────────────────────────

  async _openDetail(productId) {
    let product;
    try {
      product = await API.get(`/api/products/detail?id=${encodeURIComponent(productId)}`);
    } catch (e) { Toast.error(e.message); return; }

    const variant = product.variants?.[0] || {};
    const mapping = product.mapping;
    const upc     = product.upc || '';

    const bodyEl = document.createElement('div');
    const alignedRow = (label, field, sp, wp, type = 'text') => `
      <div style="display:grid;grid-template-columns:110px 1fr 1fr;gap:10px;align-items:center;margin-bottom:8px">
        <label class="input-label" style="margin:0">${label}</label>
        <input class="input edit-field" data-field="${field}" type="${type}" ${type==='number'?'step="0.01"':''} value="${esc(sp ?? '')}">
        <div style="font-size:12px;color:var(--text-secondary);padding:0 4px">${esc(wp ?? '—')}</div>
      </div>`;

    bodyEl.innerHTML = `
      <div style="display:flex;gap:16px;margin-bottom:16px">
        ${product.images?.[0] ? `<img src="${esc(product.images[0].url)}" style="width:110px;height:110px;object-fit:cover;border-radius:8px;flex-shrink:0">` : ''}
        <div style="flex:1">
          <div class="section-label">Shopify ↔ Webami</div>
          <div style="display:grid;grid-template-columns:110px 1fr 1fr;gap:10px;margin-bottom:6px">
            <div></div>
            <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.06em">Shopify (editable)</div>
            <div style="font-size:10px;color:var(--text-muted);text-transform:uppercase;letter-spacing:.06em">Webami</div>
          </div>
          ${alignedRow('Title','title', product.title, mapping?.wt)}
          ${alignedRow('Vendor','vendor', product.vendor, mapping?.artist || mapping?.brand)}
          ${alignedRow('UPC','upc', upc, mapping?.webami_upc)}
          ${alignedRow('Price','price', variant.price, variant.suggested_price, 'number')}
          ${alignedRow('Cost','cost', variant.cost, mapping?.wcost, 'number')}
          ${alignedRow('Weight','weight', variant.weight, mapping?.weight, 'number')}
        </div>
      </div>

      <div class="divider"></div>
      <div class="section-label">Other Fields</div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:12px">
        <div class="input-group" style="margin:0">
          <label class="input-label">Category</label>
          <select class="select edit-field" data-field="category_name">
            <option value="">—</option>
            ${ALLOWED_CATEGORIES.map(([name]) =>
              `<option value="${esc(name)}" ${product.category_name===name?'selected':''}>${esc(name)}</option>`).join('')}
          </select>
        </div>
        <div class="input-group" style="margin:0">
          <label class="input-label">Product Type</label>
          <input class="input edit-field" data-field="product_type" value="${esc(product.product_type||'')}">
        </div>
        <div class="input-group" style="margin:0">
          <label class="input-label">Status</label>
          <input class="input edit-field" data-field="status" value="${esc(product.status||'')}">
        </div>
        <div class="input-group" style="margin:0">
          <label class="input-label">Tags</label>
          <input class="input edit-field" data-field="tags" value="${esc(product.tags||'')}">
        </div>
        <div class="input-group" style="margin:0">
          <label class="input-label">Genres</label>
          <input class="input edit-field" data-field="genres" value="${esc(product.genres||'')}">
        </div>
        <div class="input-group" style="margin:0">
          <label class="input-label">Weight Unit</label>
          <select class="select edit-field" data-field="weight_unit">
            <option value="">—</option>
            ${['GRAMS','KILOGRAMS','OUNCES','POUNDS'].map(u =>
              `<option value="${u}" ${(variant.weight_unit||'').toUpperCase()===u?'selected':''}>${u}</option>`).join('')}
          </select>
        </div>
        <div style="font-size:12px;color:var(--text-muted);align-self:center">Qty: ${Fmt.qty(variant.inventory_quantity)}</div>
      </div>

      <div class="row" style="gap:6px;margin-bottom:16px">
        <button class="btn btn-ghost btn-sm" id="clear-edits-btn">Clear Edits</button>
        <button class="btn btn-primary btn-sm" id="review-edits-btn">Review & Push</button>
      </div>

      <div class="divider"></div>
      <div class="section-label">Webami Match</div>
      <div id="webami-side">
        ${mapping ? `
          <div class="row" style="gap:6px">
            <button class="btn btn-danger btn-sm" id="modal-unmap-btn">Remove</button>
            <button class="btn btn-ghost btn-sm" id="modal-search-webami">Change Match</button>
          </div>` : this._noMatchPanel(product)}
      </div>

      <div id="push-panel" style="${mapping ? '' : 'display:none'}">
        <div class="divider"></div>
        <div class="section-label">Push to Shopify</div>
        <div style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:12px;font-size:13px">
          ${['title','vendor','upc','genres','weight','price','images'].map(f => `
            <label style="display:flex;align-items:center;gap:5px;cursor:pointer">
              <input type="checkbox" id="push-${f}" checked> ${f}
            </label>`).join('')}
        </div>
        <div id="push-result"></div>
        <button class="btn btn-primary btn-sm" id="push-btn">Push to Shopify</button>
      </div>`;

    Modal.open({ title: product.title, body: bodyEl, width: '820px',
      buttons: [{ label:'Close', cls:'btn-ghost', onClick:Modal.close }] });

    document.getElementById('modal-unmap-btn')?.addEventListener('click', async () => {
      try {
        await API.post('/api/products/unmap', { product_id: productId });
        Toast.success('Mapping removed'); Modal.close(); this._load();
      } catch (e) { Toast.error(e.message); }
    });

    document.getElementById('modal-search-webami')?.addEventListener('click', () =>
      this._webamiFetch(productId, product.title, upc, product.category_name));

    document.getElementById('push-btn')?.addEventListener('click', () =>
      this._pushToShopify(productId));

    this._origValues = {};
    bodyEl.querySelectorAll('.edit-field').forEach(el => {
      this._origValues[el.dataset.field] = el.value;
    });

    document.getElementById('clear-edits-btn')?.addEventListener('click', () => {
      bodyEl.querySelectorAll('.edit-field').forEach(el => {
        el.value = this._origValues[el.dataset.field] || '';
      });
    });

    document.getElementById('review-edits-btn')?.addEventListener('click', () =>
      this._openEditReview(productId, variant));
  }

  _openEditReview(productId, variant) {
    const changed = {};
    document.querySelectorAll('.edit-field').forEach(el => {
      const val = el.value.trim();
      if (val !== (this._origValues[el.dataset.field] || '')) {
        changed[el.dataset.field] = val;
      }
    });

    if (!Object.keys(changed).length) { Toast.warning('No changes to review'); return; }

    const bodyEl = document.createElement('div');
    bodyEl.innerHTML = `
      <div class="table-wrap">
        <table>
          <thead><tr><th style="text-align:left">Field</th><th style="text-align:left">Old</th><th style="text-align:left">New</th></tr></thead>
          <tbody>
            ${Object.entries(changed).map(([field, val]) => `
              <tr>
                <td style="text-align:left">${esc(field)}</td>
                <td style="text-align:left;color:var(--text-muted)">${esc(this._origValues[field] || '—')}</td>
                <td style="text-align:left;color:var(--green)">${esc(val || '—')}</td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>`;

    Modal.open({
      title: 'Review Changes',
      body: bodyEl,
      buttons: [
        { label: 'Back', cls: 'btn-ghost', onClick: Modal.close },
        { label: 'Confirm & Push', cls: 'btn-primary', onClick: () => this._confirmEditPush(productId, variant, changed) },
      ],
    });
  }

  async _confirmEditPush(productId, variant, changed) {
    const payload = { product_id: productId, variant_id: variant.variant_id };
    if ('title' in changed)         payload.title = changed.title;
    if ('upc' in changed)           payload.upc = changed.upc;
    if ('vendor' in changed)        payload.vendor = changed.vendor;
    if ('category_name' in changed) payload.category_name = changed.category_name;
    if ('product_type' in changed)  payload.product_type = changed.product_type;
    if ('price' in changed)         payload.price = parseFloat(changed.price);
    if ('cost' in changed)          payload.cost = parseFloat(changed.cost);
    if ('weight' in changed)        payload.weight = parseFloat(changed.weight);
    if ('weight_unit' in changed)   payload.weight_unit = changed.weight_unit;

    try {
      const data = await API.post('/api/products/update-fields', payload);
      if (data.dry_run) Toast.warning('Dry run — nothing pushed');
      else Toast.success('Fields updated in Shopify');
      Modal.close();
      Modal.close();
      this._load();
    } catch (e) { Toast.error(e.message); }
  }

  _webamiPanel(mapping, variant) {
    const imgs = (() => { try { return JSON.parse(mapping.image_urls||'[]'); } catch { return []; } })();
    return `
      ${imgs[0] ? `<img src="${esc(imgs[0])}" style="width:100%;max-height:160px;object-fit:cover;border-radius:8px;margin-bottom:10px" onerror="this.style.display='none'">` : ''}
      <div style="font-size:13px;line-height:1.9">
        <div><b>Title:</b> ${esc(mapping.wt||'—')}</div>
        <div><b>Vendor:</b> ${esc(mapping.artist||mapping.brand||'—')}</div>
        <div><b>Format:</b> ${esc(mapping.format||'—')}</div>
        <div><b>UPC:</b> <span class="mono" style="font-size:11px">${esc(mapping.webami_upc||'—')}</span></div>
        <div><b>Target Price:</b> <span style="color:var(--green)">${Fmt.price(variant.suggested_price)}</span></div>
        <div><b>Cost:</b> ${Fmt.price(mapping.wcost)}</div>
        <div><b>Weight:</b> ${mapping.weight ? `${mapping.weight} ${esc(mapping.weight_unit||'g')}` : '—'}</div>
        <div><b>Confidence:</b> <span class="badge badge-new" style="font-size:11px">${esc(mapping.confidence||'—')}</span></div>
      </div>
      <div class="row" style="margin-top:10px;gap:6px">
        <button class="btn btn-danger btn-sm" id="modal-unmap-btn">Remove</button>
        <button class="btn btn-ghost btn-sm" id="modal-search-webami">Change Match</button>
      </div>`;
  }

  _noMatchPanel(product) {
    return `
      <div class="empty-state" style="padding:12px 0">
        <div class="empty-state-icon">🔍</div>
        <div class="empty-state-text">No Webami match</div>
      </div>
      <div class="input-group">
        <label class="input-label">Fetch from Webami by UPC</label>
        <div class="row" style="gap:6px">
          <input id="modal-upc-input" class="input flex-1" value="${esc(product.upc)}" placeholder="Enter UPC">
          <button id="modal-search-webami" class="btn btn-primary btn-sm">Fetch</button>
        </div>
      </div>`;
  }

  async _webamiFetch(productId, title, existingUpc, category) {
    const upcInput = document.getElementById('modal-upc-input');
    const upc = (upcInput?.value?.trim()) || existingUpc || '';
    if (!upc) { Toast.warning('Enter a UPC first'); return; }
    const btn = document.getElementById('modal-search-webami');
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span>'; }
    try {
      const wp = await API.post('/api/webami/scrape', { upc, title, format: category || '' });
      const resultArea = document.getElementById('webami-side');
      if (resultArea) {
        resultArea.innerHTML = `
          <div class="pending-item">
            <div class="item-info">
              <div class="item-title">${esc(wp.title || wp.upc)}</div>
              <div class="item-meta">${esc(wp.artist || wp.brand || '')} · ${esc(wp.format || '')} · ${Fmt.price(wp.cost)}</div>
              <div class="item-meta mono" style="font-size:11px">UPC: ${esc(wp.upc)}</div>
            </div>
            <button class="btn btn-success btn-sm" id="webami-select-btn">Select</button>
          </div>`;
        document.getElementById('webami-select-btn').addEventListener('click', async () => {
          try {
            await API.post('/api/products/map', { product_id: productId, webami_upc: wp.upc });
            Toast.success(`Matched to "${wp.title||wp.upc}"`);
            const row = document.querySelector(`tr[data-id="${productId}"]`);
            if (row) {
              const cell = row.querySelector('[data-col="mapped"]');
              if (cell) cell.innerHTML = mapStatusBadge('active', 'manual');
            }
            Modal.close(); this._load();
          } catch (e) { Toast.error(e.message); }
        });
      }
    } catch (e) {
      Toast.error(e.message);
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Fetch'; }
    }
  }

  async _pushToShopify(productId) {
    const btn    = document.getElementById('push-btn');
    const result = document.getElementById('push-result');
    const flags  = {};
    ['title','vendor','upc','genres','weight','price','images'].forEach(f => {
      flags[f] = document.getElementById(`push-${f}`)?.checked ?? true;
    });
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Pushing…';
    result.innerHTML = '';
    try {
      const data = await API.post('/api/products/push-webami-data',
        { product_id: productId, push: flags });
      result.innerHTML = data.errors?.length
        ? `<div class="alert alert-warning" style="font-size:12px">Partial: ${data.errors.join('; ')}</div>`
        : `<div class="alert alert-success" style="font-size:12px">Pushed: ${Object.entries(data.results||{}).map(([k,v])=>`${k}: ${v}`).join(', ')}</div>`;
      this._load();
    } catch (e) {
      result.innerHTML = `<div class="alert alert-error">${esc(e.message)}</div>`;
    } finally {
      btn.disabled = false; btn.textContent = 'Push to Shopify';
    }
  }
}
