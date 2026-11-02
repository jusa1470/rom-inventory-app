import { API } from '../api.js';
import { Modal } from '../components/modal.js';
import { Toast } from '../components/toast.js';
import { Fmt, buildPager, debounce, esc, truncCell } from '../util.js';

const margin = (price, cost) =>
  price > 0 ? `${(((price - cost) / price) * 100).toFixed(1)}%` : '—';
const move = (a, b) => `${Fmt.price(a)} → ${Fmt.price(b)}`;
const tone = (a, b) => (b > a ? 'var(--red)' : b < a ? 'var(--green)' : 'inherit');

export class PricesPage {
  constructor() {
    this.page = 1;
    this.f = { title: '', vendor: '', type: '', increase: false, decrease: false, review: false };
    this._request = 0;
  }

  destroy() {}

  _params(extra = {}) {
    const p = new URLSearchParams(extra);
    for (const [k, v] of Object.entries(this.f)) if (v) p.set(k, v === true ? 'true' : v);
    return p;
  }

  async render(c) {
    this.c = c;
    c.innerHTML = `
      <div class="page">
        <div class="page-title">Price Updates</div>
        <div class="search-row" style="flex-wrap:wrap;align-items:center">
          <input class="input" data-f="title" placeholder="Title…">
          <input class="input" data-f="vendor" placeholder="Artist / vendor…">
          <select class="input" data-f="type" style="max-width:140px">
            <option value="">All types</option><option>Vinyl</option><option>CD</option><option>Cassette</option>
          </select>
          <label class="check-row" style="margin:0"><input type="checkbox" data-f="increase"><span>Increased</span></label>
          <label class="check-row" style="margin:0"><input type="checkbox" data-f="decrease"><span>Decreased</span></label>
          <label class="check-row" style="margin:0"><input type="checkbox" data-f="review"><span>Needs review</span></label>
        </div>
        <div class="search-row">
          <button class="btn btn-ghost btn-sm" id="p-all">Select all</button>
          <button class="btn btn-ghost btn-sm" id="p-none">Deselect all</button>
          <button class="btn btn-primary btn-sm" id="p-review">Review list (<span id="p-count">0</span>)</button>
        </div>
        <div id="p-pager-top"></div>
        <div class="table-wrap"><table class="variants-table">
          <thead id="p-head"></thead><tbody id="p-body"></tbody>
        </table></div>
        <div id="p-pager-bottom"></div>
      </div>`;
    const reload = () => { this.page = 1; this._load(); };
    c.querySelectorAll('[data-f]').forEach(el => {
      const k = el.dataset.f;
      const set = () => { this.f[k] = el.type === 'checkbox' ? el.checked : el.value.trim(); reload(); };
      el.addEventListener(el.tagName === 'INPUT' && el.type === 'text' ? 'input' : 'change',
        el.type === 'text' ? debounce(set) : set);
    });
    c.querySelector('#p-all').addEventListener('click', () => this._bulk('add'));
    c.querySelector('#p-none').addEventListener('click', () => this._bulk('remove'));
    c.querySelector('#p-review').addEventListener('click', () => this._openQueue());
    this._count();
    await this._load();
  }

  async _count() {
    try {
      const { items } = await API.get('/api/prices/queue');
      const el = this.c.querySelector('#p-count');
      if (el) el.textContent = items.length;
    } catch (_) { /* non-critical */ }
  }

  async _bulk(action) {
    if (this.f.review) return Toast.info('Switch off "Needs review" first');
    try {
      await API.post(`/api/prices/queue/filtered?${this._params({ action })}`);
      await this._load();
      this._count();
    } catch (e) { Toast.error(e.message); }
  }

  async _load() {
    const body = this.c.querySelector('#p-body');
    const head = this.c.querySelector('#p-head');
    const req = ++this._request;
    const review = this.f.review;
    head.innerHTML = review
      ? '<tr><th>Title</th><th>Vendor</th><th>Type</th><th>UPC</th><th>Suggestion</th><th>Manual UPC</th></tr>'
      : '<tr><th></th><th>Title</th><th>Vendor</th><th>Type</th><th>UPC</th>' +
        '<th class="num">Cost (old → new)</th><th class="num">Price (old → 34% margin)</th></tr>';
    body.innerHTML = `<tr><td colspan="7" class="empty-cell"><span class="spinner"></span> Loading…</td></tr>`;
    try {
      const data = await API.get(`/api/prices?${this._params({ page: this.page })}`);
      if (req !== this._request || !body.isConnected) return;
      const title = r => `<div class="pair"><span>${esc(r.title)}</span><span class="sub">${esc(r.variant_title || '')}</span></div>`;
      body.innerHTML = data.items.length ? data.items.map(r => review ? `
        <tr>
          <td>${title(r)}</td><td>${truncCell(r.vendor)}</td><td>${esc(r.type || '—')}</td>
          <td class="mono">${esc(r.upc || '—')}</td>
          <td>${r.suggest_upc
            ? `${truncCell(r.suggest_title)} <span class="mono">${esc(r.suggest_upc)}</span>
               <button class="btn btn-primary btn-sm" data-use="${esc(r.variant_id)}" data-upc="${esc(r.suggest_upc)}">Use</button>`
            : '<span class="muted">none</span>'}</td>
          <td><div style="display:flex;gap:6px">
            <input class="input" style="height:28px" placeholder="UPC" data-man="${esc(r.variant_id)}">
            <button class="btn btn-ghost btn-sm" data-look="${esc(r.variant_id)}">Look up</button></div></td>
        </tr>` : `
        <tr>
          <td><input type="checkbox" data-q="${esc(r.variant_id)}" ${r.queued ? 'checked' : ''}></td>
          <td>${title(r)}</td><td>${truncCell(r.vendor)}</td><td>${esc(r.type || '—')}</td>
          <td class="mono">${esc(r.upc || '—')}</td>
          <td class="num" style="color:${tone(r.old_cost, r.new_cost)}">${move(r.old_cost, r.new_cost)}</td>
          <td class="num">${move(r.old_price, r.calc_price)}</td>
        </tr>`).join('')
        : `<tr><td colspan="7" class="empty-cell">Nothing to show</td></tr>`;
      body.querySelectorAll('[data-q]').forEach(cb => cb.addEventListener('change', async () => {
        try {
          await API.post(`/api/prices/queue/${cb.checked ? 'add' : 'remove'}`, { variant_ids: [cb.dataset.q] });
          this._count();
        } catch (e) { cb.checked = !cb.checked; Toast.error(e.message); }
      }));
      body.querySelectorAll('[data-use]').forEach(b =>
        b.addEventListener('click', () => this._resolve(b.dataset.use, b.dataset.upc)));
      body.querySelectorAll('[data-look]').forEach(b => b.addEventListener('click', () => {
        const upc = body.querySelector(`[data-man="${b.dataset.look}"]`).value.trim();
        if (!upc) return Toast.error('Enter a UPC');
        this._resolve(b.dataset.look, upc);
      }));
      for (const id of ['#p-pager-top', '#p-pager-bottom']) {
        buildPager(this.c.querySelector(id), data, p => { this.page = p; this._load(); });
      }
    } catch (e) {
      if (req === this._request && body.isConnected)
        body.innerHTML = `<tr><td colspan="7" class="empty-cell">${esc(e.message)}</td></tr>`;
    }
  }

  async _resolve(variant_id, upc) {
    try {
      await API.post('/api/prices/resolve', { variant_id, upc });
      Toast.success('Price found');
      this._load();
    } catch (e) { Toast.error(e.message); }
  }

  async _openQueue() {
    let items;
    try {
      ({ items } = await API.get('/api/prices/queue'));
    } catch (e) { return Toast.error(e.message); }
    const body = document.createElement('div');
    const draw = () => {
      body.innerHTML = items.length ? `
        <div class="table-wrap"><table class="variants-table">
          <thead><tr><th>Title</th><th>Vendor</th><th>UPC</th><th class="num">Cost (old → new)</th>
            <th class="num">Old price</th><th class="num">New price</th><th class="num">New margin</th><th></th></tr></thead>
          <tbody>${items.map((r, i) => `
            <tr>
              <td><div class="pair"><span>${esc(r.title)}</span><span class="sub">${esc(r.variant_title || '')}</span></div></td>
              <td>${truncCell(r.vendor)}</td><td class="mono">${esc(r.upc || '—')}</td>
              <td class="num">${move(r.old_cost, r.new_cost)}</td>
              <td class="num">${Fmt.price(r.old_price)}</td>
              <td class="num"><input class="input" style="width:90px;height:28px;text-align:right"
                data-p="${i}" value="${r.new_price.toFixed(2)}"></td>
              <td class="num" data-m="${i}">${margin(r.new_price, r.new_cost)}</td>
              <td><button class="btn btn-ghost btn-sm" data-rm="${i}">Remove</button></td>
            </tr>`).join('')}</tbody></table></div>`
        : '<div class="muted">List is empty</div>';
      body.querySelectorAll('[data-p]').forEach(inp => inp.addEventListener('change', async () => {
        const i = +inp.dataset.p, v = parseFloat(inp.value);
        if (!(v > 0)) { inp.value = items[i].new_price.toFixed(2); return Toast.error('Invalid price'); }
        try {
          await API.put(`/api/prices/queue/${encodeURIComponent(items[i].variant_id)}`, { price: v });
          items[i].new_price = Math.round(v * 100) / 100;
          inp.value = items[i].new_price.toFixed(2);
          body.querySelector(`[data-m="${i}"]`).textContent = margin(items[i].new_price, items[i].new_cost);
        } catch (e) { Toast.error(e.message); }
      }));
      body.querySelectorAll('[data-rm]').forEach(b => b.addEventListener('click', async () => {
        const i = +b.dataset.rm;
        try {
          await API.post('/api/prices/queue/remove', { variant_ids: [items[i].variant_id] });
          items.splice(i, 1);
          draw();
          this._count();
        } catch (e) { Toast.error(e.message); }
      }));
    };
    draw();
    Modal.open({
      title: 'Review price updates', body, width: '96vw',
      buttons: [
        { label: 'Push to Shopify', cls: 'btn-primary', onClick: async () => {
          if (!items.length) return;
          try {
            const res = await API.post('/api/prices/queue/push');
            if (res.dry_run) Toast.warning('Test mode: nothing written');
            else if (res.errors.length) Toast.warning(`Pushed ${res.pushed}; ${res.errors.length} failed: ${res.errors[0]}`);
            else Toast.success(`Updated ${res.pushed} variants`);
            Modal.close();
            this._load();
            this._count();
          } catch (e) { Toast.error(e.message); }
        } },
        { label: 'Cancel', onClick: Modal.close },
      ],
    });
  }
}