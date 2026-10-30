import { API } from '../api.js';
import { Modal } from '../components/modal.js';
import { Toast } from '../components/toast.js';
import { Fmt, buildPager, debounce, esc, truncCell } from '../util.js';

export class OrdersPage {
  constructor() {
    this.page = 1;
    this.q = '';
    this._request = 0;
  }

  destroy() {}

  async render(container) {
    this.c = container;
    await this._showList();
  }

  async _showList() {
    this.c.innerHTML = `
      <div class="page">
        <div class="page-title">Orders</div>
        <div class="search-row">
          <input class="input" id="o-search" placeholder="Search order #, name, UPC, title, artist…">
        </div>
        <div id="o-pager-top"></div>
        <div class="table-wrap">
          <table>
            <thead><tr>
              <th>Order #</th><th>Name</th><th>Date</th>
              <th class="num">SKUs</th><th class="num">Total qty</th><th></th>
            </tr></thead>
            <tbody id="o-body"></tbody>
          </table>
        </div>
        <div id="o-pager-bottom"></div>
      </div>`;
    const search = this.c.querySelector('#o-search');
    search.value = this.q;
    search.addEventListener('input', debounce(e => {
      this.q = e.target.value.trim();
      this.page = 1;
      this._load();
    }));
    await this._load();
  }

  async _load() {
    const body = this.c.querySelector('#o-body');
    const request = ++this._request;
    try {
      const params = new URLSearchParams({ page: String(this.page) });
      if (this.q) params.set('q', this.q);
      const data = await API.get(`/api/orders?${params}`);
      if (request !== this._request || !body.isConnected) return;
      body.innerHTML = data.items.length ? data.items.map(o => `
        <tr>
          <td class="mono">${esc(o.number)}</td>
          <td>${truncCell(o.name)}</td>
          <td>${Fmt.datetime(o.submitted_at)}</td>
          <td class="num">${o.sku_count}</td>
          <td class="num">${o.total_qty}</td>
          <td><button class="btn btn-ghost btn-sm" data-id="${esc(o.guid)}">View</button></td>
        </tr>`).join('')
        : '<tr><td colspan="6" class="empty-cell">No orders found</td></tr>';
      body.querySelectorAll('button[data-id]').forEach(b =>
        b.addEventListener('click', () => this._openOrder(b.dataset.id)));
      for (const id of ['#o-pager-top', '#o-pager-bottom']) {
        buildPager(this.c.querySelector(id), data, p => { this.page = p; this._load(); });
      }
    } catch (e) {
      if (request === this._request && body.isConnected) {
        body.innerHTML = `<tr><td colspan="6" class="empty-cell">${esc(e.message)}</td></tr>`;
      }
    }
  }

  async _openOrder(guid) {
    let o;
    try {
      o = await API.get(`/api/orders/${encodeURIComponent(guid)}`);
    } catch (e) {
      Toast.error(e.message);
      return;
    }
    const total = o.items.reduce((n, i) => n + (i.quantity || 0) * (i.price || 0), 0);
    this.c.innerHTML = `
      <div class="page">
        <div class="page-title">Order ${esc(o.number)}</div>
        <button class="btn btn-ghost btn-sm" id="o-back" style="margin-bottom:16px">‹ Back to orders</button>
        <div class="card">
          <div class="detail-grid">
            <div><div class="input-label">Order #</div><div class="mono">${esc(o.number)}</div></div>
            <div><div class="input-label">Name</div><div>${esc(o.name || '—')}</div></div>
            <div><div class="input-label">Submitted</div><div>${Fmt.datetime(o.submitted_at)}</div></div>
            <div><div class="input-label">SKUs</div><div>${o.sku_count}</div></div>
            <div><div class="input-label">Total</div><div>${Fmt.price(total)}</div></div>
          </div>
        </div>
        <div class="section-label">Items (${o.items.length})</div>
        <div class="table-wrap">
          <table class="variants-table">
            <thead><tr>
              <th>Title</th><th>Artist</th><th>Format</th><th>UPC</th><th>SKU</th>
              <th class="num">Qty</th><th class="num">Price</th><th class="num">Total</th><th></th>
            </tr></thead>
            <tbody>
              ${o.items.map(i => `
                <tr>
                  <td>${truncCell(i.title)}</td>
                  <td>${truncCell(i.artist)}</td>
                  <td>${esc(i.format || '—')}</td>
                  <td class="mono">${esc(Fmt.upc(i.upc))}</td>
                  <td class="mono">${esc(i.sku || '—')}</td>
                  <td class="num">${i.quantity}</td>
                  <td class="num">${Fmt.price(i.price)}</td>
                  <td class="num">${Fmt.price((i.quantity || 0) * (i.price || 0))}</td>
                  <td>${i.product_id
                    ? `<button class="btn btn-ghost btn-sm" data-pid="${i.product_id}">Product</button>` : ''}</td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>
      </div>`;
    this.c.querySelector('#o-back').addEventListener('click', () => this._showList());
    this.c.querySelectorAll('button[data-pid]').forEach(b =>
      b.addEventListener('click', () => this._openProduct(b.dataset.pid)));
  }

  async _openProduct(id) {
    let p;
    try {
      p = await API.get(`/api/orders/products/${encodeURIComponent(id)}`);
    } catch (e) {
      Toast.error(e.message);
      return;
    }
    const item = (label, value, cls = '') => `
      <div><div class="input-label">${label}</div>
      <div class="detail-value ${cls}">${esc(value || '—')}</div></div>`;
    const config_base = 'https://webami.aent.com';
    const body = document.createElement('div');
    body.innerHTML = `
      <div class="detail-grid">
        ${item('Title', p.title)}
        ${item('Artist', p.artist)}
        ${item('Vendor', p.vendor)}
        ${item('Type', p.product_type)}
        ${item('SKU', p.sku, 'mono')}
        ${item('UPC', p.upc, 'mono')}
        ${item('List price', p.price != null ? Fmt.price(p.price) : '')}
        ${item('Your price', p.your_price != null ? Fmt.price(p.your_price) : '')}
        ${item('WebAMI ID', p.wmsid, 'mono')}
        ${item('Last synced', Fmt.datetime(p.last_synced))}
        ${p.href ? `<div><div class="input-label">WebAMI</div>
          <a href="${esc(config_base + p.href)}" target="_blank" rel="noopener">Open product page ↗</a></div>` : ''}
      </div>
      <div class="section-label">Known IDs (${p.ids.length})</div>
      <div class="table-wrap">
        <table class="variants-table">
          <thead><tr><th>Kind</th><th>Value</th><th>First seen</th><th>Last seen</th></tr></thead>
          <tbody>
            ${p.ids.map(i => `
              <tr>
                <td>${esc(i.kind)}</td>
                <td class="mono">${esc(i.value)}</td>
                <td>${Fmt.datetime(i.first_seen)}</td>
                <td>${Fmt.datetime(i.last_seen)}</td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>`;
    Modal.open({
      title: p.title || 'Product',
      body,
      width: '800px',
      buttons: [{ label: 'Close', onClick: Modal.close }],
    });
  }
}