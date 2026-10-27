import { API } from '../api.js';
import { Modal } from '../components/modal.js';
import { Toast } from '../components/toast.js';
import { Fmt, buildPager, debounce, esc, statusBadge, thumb, truncCell } from '../util.js';

const COLUMNS = [
  { label: '', width: 58 },
  { label: 'Title' },
  { label: 'Vendor', width: 160 },
  { label: 'Status', width: 100 },
  { label: 'Category', width: 200 },
  { label: 'Genres', width: 160 },
  { label: 'Variants', width: 80, num: true },
  { label: 'Price', width: 140, num: true },
  { label: 'Qty', width: 70, num: true },
  { label: '', width: 80 },
];

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
    this._request = 0;
  }

  async render(container) {
    this.c = container;
    container.innerHTML = `
      <div class="page">
        <div class="page-title">Products</div>
        <div class="search-row">
          <input class="input" id="p-search" placeholder="Title, vendor, UPC, SKU, barcode…">
        </div>
        <div class="table-wrap">
          <table>
            <colgroup>${COLUMNS.map(c => `<col${c.width ? ` style="width:${c.width}px"` : ''}>`).join('')}</colgroup>
            <thead><tr>${COLUMNS.map(c => `<th class="${c.num ? 'num' : ''}">${c.label}</th>`).join('')}</tr></thead>
            <tbody id="products-body"></tbody>
          </table>
        </div>
        <div id="products-pager"></div>
      </div>`;

    this.c.querySelector('#p-search').addEventListener('input', debounce(e => {
      this.q = e.target.value.trim();
      this.page = 1;
      this._load();
    }));
    await this._load();
  }

  async _load() {
    const body = this.c.querySelector('#products-body');
    const request = ++this._request;
    const params = new URLSearchParams({ page: String(this.page) });
    if (this.q) params.set('q', this.q);
    try {
      const data = await API.get(`/api/products?${params}`);
      if (request !== this._request || !body.isConnected) return;
      this._renderRows(body, data.items);
      buildPager(this.c.querySelector('#products-pager'), data, p => {
        this.page = p;
        this._load();
      });
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
        <td>${truncCell(p.genres)}</td>
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
        ${item('Genres', p.genres)}
        ${item('Type', p.type)}
        ${item('Tags', p.tags)}
        ${item('Last synced', Fmt.datetime(p.last_synced))}
      </div>
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
                <td>${thumb(v.images && v.images[0] && v.images[0].url, v.title)}</td>
                <td>${truncCell(v.title)}</td>
                <td class="mono">${esc(v.sku || '—')}</td>
                <td class="mono">${esc(v.barcode || '—')}</td>
                <td class="mono">${esc(Fmt.upc(v.upc))}</td>
                <td class="num">${Fmt.price(v.price)}</td>
                <td class="num">${Fmt.price(v.cost)}</td>
                <td class="num">${Fmt.qty(v.inventory_quantity)}</td>
                <td>${v.weight != null ? esc(`${v.weight} ${v.weight_unit || ''}`) : '—'}</td>
                <td>${esc(v.release_date || '—')}</td>
                <td>${truncCell(v.variant_tags)}</td>
                <td>${truncCell(v.description)}</td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>`;

    Modal.open({
      title: p.title,
      body,
      width: '1000px',
      buttons: [{ label: 'Close', onClick: Modal.close }],
    });
  }
}