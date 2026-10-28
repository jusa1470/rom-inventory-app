import { API } from '../api.js';
import { Modal } from '../components/modal.js';
import { createMultiSelect } from '../components/multiselect.js';
import { Toast } from '../components/toast.js';
import { Fmt, buildPager, debounce, esc, statusBadge, thumb, truncCell } from '../util.js';

// key = filter name (and filter-options key); sort = backend sort key
const COLUMNS = [
  { label: '', width: 58 },
  { label: 'Title', width: 320, key: 'title', sort: 'title', filter: 'text' },
  { label: 'Vendor', width: 160, key: 'vendor', sort: 'vendor', filter: 'text' },
  { label: 'Status', width: 120, key: 'status', sort: 'status', filter: 'select' },
  { label: 'Category', width: 200, key: 'category', sort: 'category', filter: 'select' },
  { label: 'Type', width: 140, key: 'type', sort: 'type', filter: 'select' },
  { label: 'Genres', width: 180, key: 'genres', sort: 'genres', filter: 'select' },
  { label: 'Tags', width: 180, key: 'tags', sort: 'tags', filter: 'select' },
  { label: 'Variants', width: 90, sort: 'variants', num: true },
  { label: 'Price', width: 140, sort: 'price', num: true },
  { label: 'Qty', width: 80, sort: 'qty', num: true },
  { label: '', width: 100, clear: true },
];

const TABLE_MIN_WIDTH = COLUMNS.reduce((n, c) => n + (c.width || 0), 0);

const listText = v => (v ? String(v).split(',').join(', ') : '');

function priceRange(variants) {
  const prices = variants.map(v => parseFloat(v.price)).filter(n => !Number.isNaN(n));
  if (!prices.length) return '—';
  const lo = Math.min(...prices);
  const hi = Math.max(...prices);
  return lo === hi ? Fmt.price(lo) : `${Fmt.price(lo)} – ${Fmt.price(hi)}`;
}

const totalQty = variants => variants.reduce((n, v) => n + (v.inventory_quantity || 0), 0);

export class ProductsPage {
  constructor() {
    this.page = 1;
    this.q = '';
    this.sort = 'title';
    this.dir = 'asc';
    this.filters = {};
    this._request = 0;
    this._selects = [];
    this._textInputs = [];
  }

  destroy() {
    this._selects.forEach(s => s.destroy());
    this._selects = [];
  }

  async render(container) {
    this.c = container;
    container.innerHTML = `
      <div class="page">
        <div class="page-title">Products</div>
        <div class="search-row">
          <input class="input" id="p-search" placeholder="Search all columns — title, vendor, UPC, SKU, barcode…">
        </div>
        <div id="pager-top"></div>
        <div class="table-wrap">
          <table style="min-width:${TABLE_MIN_WIDTH}px">
            <colgroup>${COLUMNS.map(c => `<col${c.width ? ` style="width:${c.width}px"` : ''}>`).join('')}</colgroup>
            <thead id="products-head"></thead>
            <tbody id="products-body"></tbody>
          </table>
        </div>
        <div id="pager-bottom"></div>
      </div>`;

    let options = {};
    try {
      options = await API.get('/api/products/filter-options');
    } catch (e) {
      Toast.error('Failed to load filter options: ' + e.message);
    }
    this._buildHead(options);

    this.c.querySelector('#p-search').addEventListener('input', debounce(e => {
      this.q = e.target.value.trim();
      this.page = 1;
      this._load();
    }));
    await this._load();
  }

  _buildHead(options) {
    const labels = document.createElement('tr');
    const filters = document.createElement('tr');
    filters.className = 'filter-row';

    COLUMNS.forEach(col => {
      const th = document.createElement('th');
      th.className = [col.num ? 'num' : '', col.sort ? 'sortable' : ''].join(' ').trim();
      th.innerHTML = `${col.label}<span class="sort-ind" data-sort="${col.sort || ''}"></span>`;
      if (col.sort) th.addEventListener('click', () => this._setSort(col.sort));
      labels.appendChild(th);

      const fth = document.createElement('th');
      if (col.filter === 'text') {
        const input = document.createElement('input');
        input.className = 'input filter-input';
        input.placeholder = 'Filter…';
        input.addEventListener('input', debounce(() => {
          this.filters[col.key] = input.value.trim();
          this.page = 1;
          this._load();
        }));
        this._textInputs.push(input);
        fth.appendChild(input);
      } else if (col.filter === 'select') {
        const select = createMultiSelect({
          placeholder: 'All',
          options: options[col.key] || [],
          onChange: values => {
            this.filters[col.key] = values;
            this.page = 1;
            this._load();
          },
        });
        this._selects.push(select);
        fth.appendChild(select.el);
      } else if (col.clear) {
        const btn = document.createElement('button');
        btn.className = 'btn btn-ghost btn-sm';
        btn.textContent = 'Clear all';
        btn.addEventListener('click', () => this._clearFilters());
        fth.appendChild(btn);
      }
      filters.appendChild(fth);
    });

    this.c.querySelector('#products-head').replaceChildren(labels, filters);
    this._updateSortIndicators();
  }

  _clearFilters() {
    this.q = '';
    this.filters = {};
    this.page = 1;
    this.c.querySelector('#p-search').value = '';
    this._textInputs.forEach(i => { i.value = ''; });
    this._selects.forEach(s => s.clear());
    this._load();
  }

  _setSort(key) {
    if (this.sort === key) {
      this.dir = this.dir === 'asc' ? 'desc' : 'asc';
    } else {
      this.sort = key;
      this.dir = 'asc';
    }
    this.page = 1;
    this._updateSortIndicators();
    this._load();
  }

  _updateSortIndicators() {
    this.c.querySelectorAll('.sort-ind').forEach(span => {
      span.textContent = span.dataset.sort === this.sort
        ? (this.dir === 'asc' ? '▲' : '▼') : '';
    });
  }

  _params() {
    const params = new URLSearchParams({
      page: String(this.page), sort: this.sort, dir: this.dir,
    });
    if (this.q) params.set('q', this.q);
    for (const [key, value] of Object.entries(this.filters)) {
      if (Array.isArray(value)) value.forEach(v => params.append(key, v));
      else if (value) params.set(key, value);
    }
    return params;
  }

  async _load() {
    const body = this.c.querySelector('#products-body');
    const request = ++this._request;
    try {
      const data = await API.get(`/api/products?${this._params()}`);
      if (request !== this._request || !body.isConnected) return;
      this._renderRows(body, data.items);
      for (const id of ['#pager-top', '#pager-bottom']) {
        buildPager(this.c.querySelector(id), data, p => {
          this.page = p;
          this._load();
        });
      }
    } catch (e) {
      if (request !== this._request || !body.isConnected) return;
      body.innerHTML = `<tr><td colspan="${COLUMNS.length}" class="empty-cell">${esc(e.message)}</td></tr>`;
    }
  }

  _renderRows(body, items) {
    if (!items.length) {
      body.innerHTML = `<tr><td colspan="${COLUMNS.length}" class="empty-cell">No products found</td></tr>`;
      return;
    }
    body.innerHTML = items.map(p => `
      <tr>
        <td>${thumb(p.image_url, p.title)}</td>
        <td>${truncCell(p.title)}</td>
        <td>${truncCell(p.vendor)}</td>
        <td>${statusBadge(p.status)}</td>
        <td>${truncCell(p.category_name)}</td>
        <td>${truncCell(p.type)}</td>
        <td>${truncCell(listText(p.genres))}</td>
        <td>${truncCell(listText(p.tags))}</td>
        <td class="num">${p.variants.length}</td>
        <td class="num">${priceRange(p.variants)}</td>
        <td class="num">${totalQty(p.variants)}</td>
        <td><button class="btn btn-ghost btn-sm" data-id="${esc(p.product_id)}">View</button></td>
      </tr>`).join('');
    body.querySelectorAll('button[data-id]').forEach(btn =>
      btn.addEventListener('click', () => this._openDetail(btn.dataset.id)));
  }

  async _openDetail(productId) {
    let p;
    try {
      p = await API.get(`/api/products/${encodeURIComponent(productId)}`);
    } catch (e) {
      Toast.error(e.message);
      return;
    }

    const item = (label, value) => `
      <div>
        <div class="input-label">${label}</div>
        <div class="detail-value">${esc(value || '—')}</div>
      </div>`;

    const body = document.createElement('div');
    body.innerHTML = `
      <div class="detail-grid">
        ${item('Vendor', p.vendor)}
        ${item('Handle', p.handle)}
        ${item('Status', p.status)}
        ${item('Category', p.category_name)}
        ${item('Product type', p.product_type)}
        ${item('Genres', listText(p.genres))}
        ${item('Type', p.type)}
        ${item('Tags', listText(p.tags))}
        ${item('Last synced', Fmt.datetime(p.last_synced))}
      </div>
      ${p.images.length ? `
        <div class="section-label">Product images (${p.images.length})</div>
        <div class="image-strip">
          ${p.images.map(img => `<img src="${esc(img.url)}" alt="${esc(p.title)}">`).join('')}
        </div>` : ''}
      <div class="section-label">Variants (${p.variants.length})</div>
      <div class="table-wrap">
        <table class="variants-table">
          <thead><tr>
            <th></th><th>Title</th><th>SKU</th><th>Barcode</th><th>UPC</th>
            <th class="num">Price</th><th class="num">Cost</th><th class="num">Qty</th>
            <th>Weight</th><th>Release date</th><th>Variant tags</th><th>Description</th>
          </tr></thead>
          <tbody>
            ${p.variants.map(v => `
              <tr>
                <td>${thumb(v.image_url, v.title)}</td>
                <td>${truncCell(v.title)}</td>
                <td class="mono">${esc(v.sku || '—')}</td>
                <td class="mono">${esc(v.barcode || '—')}</td>
                <td class="mono">${esc(Fmt.upc(v.upc))}</td>
                <td class="num">${Fmt.price(v.price)}</td>
                <td class="num">${Fmt.price(v.cost)}</td>
                <td class="num">${Fmt.qty(v.inventory_quantity)}</td>
                <td>${v.weight != null ? esc(`${v.weight} ${v.weight_unit || ''}`) : '—'}</td>
                <td>${esc(v.release_date || '—')}</td>
                <td>${truncCell(listText(v.variant_tags))}</td>
                <td>${truncCell(v.description)}</td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>`;

    Modal.open({
      title: p.title,
      body,
      width: '96vw',
      buttons: [{ label: 'Close', onClick: Modal.close }],
    });
  }
}
