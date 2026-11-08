import { API } from '../api.js';
import { Modal } from '../components/modal.js';
import { Toast } from '../components/toast.js';
import { Fmt, buildPager, debounce, esc, truncCell } from '../util.js';

export class OrdersPage {
  constructor() {
    this.page = 1;
    this.q = '';
    this._request = 0;
    this.status = '';
    this.item = { q: '', sort: 'position', dir: 'asc', only: '' };
    this.draft = {};
  }

  destroy() {}

  async render(container) {
    this.c = container;
    await this._showList();
  }

  async _showList() {
    this.item = { q: '', sort: 'position', dir: 'asc', only: '' };
    this.c.innerHTML = `
      <div class="page">
        <div class="page-title">Orders</div>
        <div class="search-row" style="align-items:center">
          <input class="input" id="o-search" placeholder="Search order #, name, UPC, title, artist…">
          <select class="input" id="o-status" style="max-width:160px">
            <option value="">All orders</option><option value="outstanding">Outstanding</option>
            <option value="open">Open</option><option value="partial">Partial</option>
            <option value="complete">Complete</option>
          </select>
          <button class="btn btn-ghost btn-sm" id="o-out">Outstanding items</button>
          <button class="btn btn-primary btn-sm" id="o-queue">Review queue (<span id="o-qcount">0</span>)</button>
        </div>
        <div id="o-pager-top"></div>
        <div class="table-wrap">
          <table>
            <thead><tr>
              <th>Order #</th><th>Name</th><th>Date</th>
              <th class="num">SKUs</th><th class="num">Total qty</th>
              <th style="width:160px">Progress</th><th>Status</th><th></th>
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
    const st = this.c.querySelector('#o-status');
    st.value = this.status;
    st.addEventListener('change', () => { this.status = st.value; this.page = 1; this._load(); });
    this.c.querySelector('#o-out').addEventListener('click', () => this._outstanding());
    this.c.querySelector('#o-queue').addEventListener('click', () => this._queue());
    this._qcount();
    await this._load();
  }

  async _qcount() {
    try {
      const { count } = await API.get('/api/orders/queue/count');
      const el = this.c.querySelector('#o-qcount');
      if (el) el.textContent = count;
    } catch (_) { /* non-critical */ }
  }

  async _load() {
    const body = this.c.querySelector('#o-body');
    const request = ++this._request;
    try {
      const params = new URLSearchParams({ page: String(this.page) });
      if (this.q) params.set('q', this.q);
      if (this.status) params.set('status', this.status);
      const data = await API.get(`/api/orders?${params}`);
      if (request !== this._request || !body.isConnected) return;
      body.innerHTML = data.items.length ? data.items.map(o => `
        <tr>
          <td class="mono">${esc(o.number)}</td>
          <td>${truncCell(o.name)}</td>
          <td>${Fmt.datetime(o.submitted_at)}</td>
          <td class="num">${o.sku_count}</td>
          <td class="num">${o.total_qty}</td>
          <td><div class="progress-bar-wrap" style="margin:0 0 4px"><div class="progress-bar"
            style="width:${o.total_qty ? Math.min(100, Math.round(o.received / o.total_qty * 100)) : 0}%"></div></div>
            <span class="muted">${o.received}/${o.total_qty}</span></td>
          <td><span class="badge ${{ open: 'badge-draft', partial: 'badge-used', complete: 'badge-new' }[o.status]}">${esc(o.status)}</span></td>
          <td><button class="btn btn-ghost btn-sm" data-id="${esc(o.guid)}">View</button></td>
        </tr>`).join('')
        : '<tr><td colspan="8" class="empty-cell">No orders found</td></tr>';
      body.querySelectorAll('button[data-id]').forEach(b =>
        b.addEventListener('click', () => this._openOrder(b.dataset.id)));
      for (const id of ['#o-pager-top', '#o-pager-bottom']) {
        buildPager(this.c.querySelector(id), data, p => { this.page = p; this._load(); });
      }
    } catch (e) {
      if (request === this._request && body.isConnected) {
        body.innerHTML = `<tr><td colspan="8" class="empty-cell">${esc(e.message)}</td></tr>`;
      }
    }
  }

  async _openOrder(guid) {
    let o;
    try {
      const p = new URLSearchParams({ q: this.item.q, sort: this.item.sort, dir: this.item.dir, only: this.item.only });
      o = await API.get(`/api/orders/${encodeURIComponent(guid)}?${p}`);
    } catch (e) {
      Toast.error(e.message);
      return;
    }
    const d = (this.draft[guid] ||= {});
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
        <div class="search-row" style="align-items:center">
        <input class="input" id="i-q" placeholder="Filter items…" style="max-width:220px" value="${esc(this.item.q)}">
        <select class="input" id="i-only" style="max-width:150px">
          ${[['', 'All items'], ['outstanding', 'Outstanding'], ['new', 'New products'], ['received', 'Fully received']]
            .map(([v, l]) => `<option value="${v}" ${this.item.only === v ? 'selected' : ''}>${l}</option>`).join('')}
        </select>
        <button class="btn btn-ghost btn-sm" id="o-all">Fill remaining</button>
        <button class="btn btn-ghost btn-sm" id="o-clear">Clear inputs</button>
        <button class="btn btn-primary btn-sm" id="o-addall">Add all entered</button>
          <button class="btn btn-ghost btn-sm" id="o-queue2">Review queue</button>
          <button class="btn btn-ghost btn-sm" id="o-hist">Receipts</button>
        </div>
        <div class="table-wrap">
          <table class="variants-table">
            <thead><tr>
            ${[['title', 'Title'], ['artist', 'Artist'], ['format', 'Format'], ['upc', 'UPC'], ['', 'SKU'],
              ['qty', 'Qty', 1], ['received', 'Recvd', 1], ['left', 'Receive', 1], ['price', 'Price', 1], ['', 'Total', 1]]
             .map(([k, l, n]) => `<th class="${n ? 'num ' : ''}${k ? 'sortable' : ''}" data-sort="${k}">${l}${this.item.sort === k ? (this.item.dir === 'asc' ? ' ▲' : ' ▼') : ''}</th>`).join('')}<th></th>
            </tr></thead>
            <tbody>
            ${o.items.map(i => {
              const left = Math.max(0, i.quantity - i.received - i.queued);
              return `
              <tr>
                <td>${truncCell(i.title)}${i.variant_id ? '' : ' <span class="badge badge-used">No UPC match</span>'}</td>
                <td>${truncCell(i.artist)}</td>
                <td>${esc(i.format || '—')}</td>
                <td class="mono">${esc(Fmt.upc(i.upc))}</td>
                <td class="mono">${esc(i.sku || '—')}</td>
                <td class="num">${i.quantity}</td>
                <td class="num">${i.received}${i.queued ? ` <span class="muted">(+${i.queued} queued)</span>` : ''}</td>
                <td class="num"><div style="display:flex;gap:6px;justify-content:flex-end">
                  <input class="input" type="number" min="0" max="${left}" style="width:70px;height:28px;text-align:right" data-recv="${esc(i.upc)}" data-left="${left}" value="${esc(d[i.upc] ?? '')}">
                  <button class="btn btn-primary btn-sm" data-add="${esc(i.upc)}" ${left ? '' : 'disabled'}>Add</button></div></td>
                <td class="num"><input class="input" type="number" min="0" max="${left}" style="width:70px;height:28px;text-align:right" data-recv="${esc(i.upc)}" data-left="${left}" value="${esc(d[i.upc] ?? (i.queued || ''))}"></td>
                <td class="num">${Fmt.price(i.price)}</td>
                <td class="num">${Fmt.price((i.quantity || 0) * (i.price || 0))}</td>
                <td>${i.product_id ? `<button class="btn btn-ghost btn-sm" data-pid="${i.product_id}">Product</button>` : ''}</td>
              </tr>`;
            }).join('')}
            </tbody>
          </table>
        </div>
      </div>`;
    this.c.querySelector('#o-back').addEventListener('click', () => this._showList());
    this.c.querySelectorAll('button[data-pid]').forEach(b =>
      b.addEventListener('click', () => this._openProduct(b.dataset.pid)));
    this.c.querySelectorAll('[data-recv]').forEach(i => i.addEventListener('input', () => {
      if (+i.value > +i.dataset.left) i.value = i.dataset.left;
      d[i.dataset.recv] = i.value;
    }));
    this.c.querySelector('#o-all').addEventListener('click', () =>
      this.c.querySelectorAll('[data-recv]').forEach(i => {
        i.value = i.dataset.left;
        i.dispatchEvent(new Event('input'));
      }));
    this.c.querySelectorAll('th[data-sort]').forEach(th => th.addEventListener('click', () => {
      const k = th.dataset.sort;
      if (!k) return;
      this.item.dir = this.item.sort === k && this.item.dir === 'asc' ? 'desc' : 'asc';
      this.item.sort = k;
      this._openOrder(guid);
    }));
    this.c.querySelector('#i-only').addEventListener('change', e => { this.item.only = e.target.value; this._openOrder(guid); });
    this.c.querySelector('#i-q').addEventListener('input', debounce(e => {
      this.item.q = e.target.value.trim();
      this._openOrder(guid);
    }));
    this.c.querySelector('#o-queue2').addEventListener('click', () => this._queue());
    this.c.querySelector('#o-hist').addEventListener('click', () => this._receipts(guid));
    const add = async upcs => {
      const lines = upcs.map(u => ({ upc: u, qty: parseInt(d[u], 10) || 0 })).filter(l => l.qty > 0);
      if (!lines.length) return Toast.info('Nothing entered');
      try {
        await API.post(`/api/orders/${encodeURIComponent(guid)}/stage`, { lines });
        lines.forEach(l => delete d[l.upc]);
        Toast.success(`Added ${lines.length} to review queue`);
        await this._openOrder(guid);
      } catch (e) { Toast.error(e.message); }
    };
    this.c.querySelectorAll('[data-add]').forEach(b =>
      b.addEventListener('click', () => add([b.dataset.add])));
    this.c.querySelectorAll('[data-recv]').forEach(i => i.addEventListener('keydown', e => {
      if (e.key === 'Enter') add([i.dataset.recv]);
    }));
    this.c.querySelector('#o-addall').addEventListener('click', () => add(Object.keys(d)));
    this.c.querySelector('#o-clear').addEventListener('click', () => {
      Object.keys(d).forEach(x => delete d[x]);
      this.c.querySelectorAll('[data-recv]').forEach(i => { i.value = ''; });
    });
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

  async _queue() {
    let items;
    try { ({ items } = await API.get('/api/orders/queue')); } catch (e) { return Toast.error(e.message); }
    const k = r => `${r.order_guid}|${r.upc}`;
    const keep = this._qsel;
    this._qsel = null;
    const sel = new Set(keep ? items.map(k).filter(x => keep.has(x)) : items.map(k));
    const off = this._qoff || new Set();
    this._qoff = null;
    const L = { update: 'Update quantity', map: 'Update quantity + set UPC', variant: 'New variant', new: 'New product + variant' };
    const B = { upc: 'UPC match', closest: 'Closest match', manual: 'Manual', none: 'No match' };
    const cls = { update: 'badge-new', map: 'badge-active', variant: 'badge-used', new: 'badge-used' };
    const diff = r => ['update', 'map'].includes(r.plan.action) && r.wm_cost != null
      && Math.abs((r.plan.cost || 0) - r.wm_cost) >= 0.005;
    const tgt = r => {
      const p = r.plan;
      if (p.action === 'new') return `<span class="muted">New:</span> ${esc(p.new_title || '—')}<div class="muted">${esc(p.new_vtitle || '')}</div>`;
      if (p.action === 'variant') return `${esc(p.product_title || '—')}<div class="muted">New variant: ${esc(p.new_vtitle || '—')}</div>`;
      return `${esc(p.product_title || '—')}<div class="muted">${esc(p.variant_title || '—')} · stock ${p.stock ?? 0} → ${(p.stock || 0) + r.qty}${p.action === 'map' ? ' · UPC will be set' : ''}</div>`;
    };
    const qs = s => `/api/orders/queue/${encodeURIComponent(s.order_guid)}/${encodeURIComponent(s.upc)}`;
    const body = document.createElement('div');
    const upd = () => {
      const b = document.querySelector('.modal-footer .btn-primary');
      if (b && !b.disabled) b.textContent = `Push selected (${sel.size})`;
    };
    const drop = keys => { items = items.filter(r => !keys.includes(k(r))); keys.forEach(x => sel.delete(x)); };
    const retarget = async (r, t) => {
      try { await API.put(`${qs(r)}/target`, t); await this._queue(); }
      catch (e) { Toast.error(e.message); }
    };
    const draw = () => {
      body.innerHTML = items.length ? `
        <div class="search-row" style="align-items:center;flex-wrap:wrap">
          <button class="btn btn-ghost btn-sm" id="q-all">Select all</button>
          <button class="btn btn-ghost btn-sm" id="q-none">Deselect all</button>
          <button class="btn btn-ghost btn-sm" id="q-rmsel">Remove selected</button>
          <button class="btn btn-danger btn-sm" id="q-rmall">Remove all</button>
        </div>
        <div class="table-wrap modal-fit"><table class="variants-table">
          <thead><tr><th></th><th>Order</th><th>WebAMI item</th><th>Action</th><th>Shopify target</th>
            <th class="num">Cost (Shopify → WebAMI)</th><th class="num">Receive</th><th></th></tr></thead>
          <tbody>${items.map((r, i) => `<tr>
            <td><input type="checkbox" data-s="${i}" ${sel.has(k(r)) ? 'checked' : ''}></td>
            <td class="mono">${esc(r.number)}</td>
            <td>${truncCell(r.title)}<div class="muted">${esc(r.artist || '')} · <span class="mono">${esc(r.upc)}</span></div></td>
            <td><span class="badge ${cls[r.plan.action]}">${L[r.plan.action]}</span>
              <div class="muted">${B[r.plan.basis]}</div></td>
            <td style="white-space:normal">${tgt(r)}</td>
            <td class="num">${diff(r) ? `<label class="check-row" style="margin:0;justify-content:flex-end"><input type="checkbox" data-c="${i}" ${off.has(k(r)) ? '' : 'checked'}><span>${Fmt.price(r.plan.cost)} → ${Fmt.price(r.wm_cost)} (update price)</span></label>` : '—'}</td>
            <td class="num"><input class="input" type="number" min="1" max="${r.ordered ?? ''}" style="width:70px;height:28px;text-align:right" data-q="${i}" value="${r.qty}"></td>
            <td style="white-space:normal"><div style="display:flex;gap:4px;flex-wrap:wrap">
              <button class="btn btn-ghost btn-sm" data-opt="${i}">Change…</button>
              ${r.plan.basis === 'closest' && r.plan.action === 'map' ? `<button class="btn btn-ghost btn-sm" data-nv="${i}">New variant instead</button>` : ''}
              ${r.plan.basis === 'closest' ? `<button class="btn btn-ghost btn-sm" data-np="${i}">New product instead</button>` : ''}
              ${r.plan.basis === 'manual' ? `<button class="btn btn-ghost btn-sm" data-auto="${i}">Reset</button>` : ''}
              <button class="btn btn-ghost btn-sm" data-rm="${i}">Remove</button></div></td></tr>`).join('')}
          </tbody></table></div>`
        : '<div class="muted">Queue is empty</div>';
      upd();
      if (!items.length) return;
      const $ = s => body.querySelector(s);
      const each = (s, fn) => body.querySelectorAll(s).forEach(fn);
      $('#q-all').addEventListener('click', () => { items.forEach(r => sel.add(k(r))); draw(); });
      $('#q-none').addEventListener('click', () => { sel.clear(); draw(); });
      $('#q-rmsel').addEventListener('click', async () => {
        const keys = [...sel];
        if (!keys.length) return Toast.info('Nothing selected');
        if (!confirm(`Remove ${keys.length} selected from queue?`)) return;
        try { await API.post('/api/orders/queue/remove', { keys }); drop(keys); draw(); this._qcount(); }
        catch (e) { Toast.error(e.message); }
      });
      $('#q-rmall').addEventListener('click', async () => {
        if (!confirm('Remove everything from the queue?')) return;
        try { await API.delete('/api/orders/queue'); items = []; sel.clear(); draw(); this._qcount(); }
        catch (e) { Toast.error(e.message); }
      });
      each('[data-s]', c => c.addEventListener('change', () => {
        const key = k(items[+c.dataset.s]);
        c.checked ? sel.add(key) : sel.delete(key);
        upd();
      }));
      each('[data-c]', c => c.addEventListener('change', () => {
        const key = k(items[+c.dataset.c]);
        c.checked ? off.delete(key) : off.add(key);
      }));
      each('[data-q]', inp => inp.addEventListener('change', async () => {
        const i = +inp.dataset.q, v = parseInt(inp.value, 10);
        if (!(v > 0)) { inp.value = items[i].qty; return Toast.error('Invalid qty'); }
        try {
          const r = await API.put(qs(items[i]), { qty: v });
          items[i].qty = r.qty;
          inp.value = r.qty;
        } catch (e) { Toast.error(e.message); }
      }));
      each('[data-opt]', b => b.addEventListener('click', () => {
        this._qsel = new Set(sel);
        this._qoff = off;
        this._options(items[+b.dataset.opt]);
      }));
      each('[data-nv]', b => b.addEventListener('click', () => {
        const r = items[+b.dataset.nv];
        this._qsel = new Set(sel); this._qoff = off;
        retarget(r, { action: 'variant', product_id: r.plan.product_id });
      }));
      each('[data-np]', b => b.addEventListener('click', () => {
        this._qsel = new Set(sel); this._qoff = off;
        retarget(items[+b.dataset.np], { action: 'new' });
      }));
      each('[data-auto]', b => b.addEventListener('click', () => {
        this._qsel = new Set(sel); this._qoff = off;
        retarget(items[+b.dataset.auto], { action: 'auto' });
      }));
      each('[data-rm]', b => b.addEventListener('click', async () => {
        const i = +b.dataset.rm;
        try { await API.delete(qs(items[i])); drop([k(items[i])]); draw(); this._qcount(); }
        catch (e) { Toast.error(e.message); }
      }));
    };
    draw();
    Modal.open({
      title: 'Review receipts', body, width: '96vw',
      buttons: [
        { label: 'Push selected', cls: 'btn-primary', onClick: async btn => {
          const chosen = items.filter(r => sel.has(k(r)));
          if (!chosen.length) return Toast.info('Nothing selected');
          const n = chosen.filter(r => ['variant', 'new'].includes(r.plan.action)).length;
          if (n && !confirm(`${n} line(s) will create new products/variants. Continue?`)) return;
          btn.disabled = true;
          btn.innerHTML = '<span class="spinner"></span>Pushing…';
          try {
            const r = await API.post('/api/orders/queue/push', {
              keys: chosen.map(k),
              cost_keys: chosen.filter(x => diff(x) && !off.has(k(x))).map(k),
            });
            if (r.dry_run) { Toast.warning('Test mode: nothing written'); btn.disabled = false; upd(); return; }
            const msg = `Updated ${r.updated}, new variants ${r.variants}, new products ${r.created}`;
            r.errors.length ? Toast.warning(`${msg}; ${r.errors[0]}`) : Toast.success(msg);
            Modal.close();
            this._showList();
          } catch (e) {
            Toast.error(e.message);
            btn.disabled = false;
            upd();
          }
        } },
        { label: 'Close', onClick: () => { Modal.close(); this._qcount(); } },
      ],
    });
    upd();
  }

  async _options(r) {
    const base = `/api/orders/queue/${encodeURIComponent(r.order_guid)}/${encodeURIComponent(r.upc)}`;
    const body = document.createElement('div');
    body.innerHTML = `
      <div>${esc(r.title)} — ${esc(r.artist || '')}</div>
      <div class="muted mono">UPC ${esc(r.upc)}</div>
      <div class="search-row" style="margin-top:12px">
        <input class="input" id="op-q" placeholder="Search Shopify title, vendor or UPC…">
        <button class="btn btn-ghost" id="op-go">Search</button></div>
      <div id="op-list"></div>`;
    const list = body.querySelector('#op-list');
    const set = async t => {
      try { await API.put(`${base}/target`, t); this._queue(); } catch (e) { Toast.error(e.message); }
    };
    let found = [];
    const draw = () => {
      list.innerHTML = found.length ? `<div class="table-wrap modal-fit"><table class="variants-table">
        <thead><tr><th>Product</th><th>Vendor</th><th>Variants</th><th></th></tr></thead>
        <tbody>${found.map(p => `<tr>
          <td>${truncCell(p.title)}</td><td>${truncCell(p.vendor)}</td>
          <td>${p.variants.map(v => `<div style="display:flex;gap:8px;align-items:center;margin:2px 0">
            <span>${esc(v.title || '—')}</span><span class="muted mono">${esc(v.upc || 'no UPC')}</span>
            <span class="muted">qty ${v.inventory_quantity ?? 0}</span>
            <button class="btn btn-ghost btn-sm" data-use="${esc(v.variant_id)}" data-diff="${v.upc && v.upc !== r.upc ? 1 : ''}">Use this variant</button></div>`).join('')}</td>
          <td><button class="btn btn-ghost btn-sm" data-nv="${esc(p.product_id)}">New variant here</button></td></tr>`).join('')}
        </tbody></table></div>` : '<div class="muted" style="margin-top:12px">No results</div>';
      list.querySelectorAll('[data-use]').forEach(b => b.addEventListener('click', () => {
        if (b.dataset.diff && !confirm('This variant has a different UPC. Overwrite it?')) return;
        set({ action: 'use', variant_id: b.dataset.use });
      }));
      list.querySelectorAll('[data-nv]').forEach(b => b.addEventListener('click', () =>
        set({ action: 'variant', product_id: b.dataset.nv })));
    };
    const load = async q => {
      try { ({ items: found } = await API.get(`${base}/options?q=${encodeURIComponent(q)}`)); draw(); }
      catch (e) { Toast.error(e.message); }
    };
    const qi = body.querySelector('#op-q');
    body.querySelector('#op-go').addEventListener('click', () => load(qi.value.trim()));
    qi.addEventListener('keydown', e => { if (e.key === 'Enter') load(qi.value.trim()); });
    await load('');
    Modal.open({
      title: 'Choose Shopify match', body, width: '96vw',
      buttons: [
        { label: 'New product + variant', cls: 'btn-primary', onClick: () => set({ action: 'new' }) },
        { label: 'Reset to suggested', onClick: () => set({ action: 'auto' }) },
        { label: 'Back', onClick: () => this._queue() },
      ],
    });
  }

  async _outstanding() {
    let items;
    try { ({ items } = await API.get('/api/orders/outstanding')); } catch (e) { return Toast.error(e.message); }
    const body = document.createElement('div');
    body.innerHTML = items.length ? `<div class="table-wrap modal-fit"><table class="variants-table">
      <thead><tr><th>Artist</th><th>Title</th><th>UPC</th><th class="num">Ordered</th>
        <th class="num">Received</th><th class="num">Outstanding</th><th class="num">Orders</th></tr></thead>
      <tbody>${items.map(r => `<tr>
        <td>${truncCell(r.artist)}</td><td>${truncCell(r.title)}</td><td class="mono">${esc(r.upc)}</td>
        <td class="num">${r.ordered}</td><td class="num">${r.received}</td>
        <td class="num">${r.ordered - r.received}</td><td class="num">${r.orders}</td></tr>`).join('')}
      </tbody></table></div>` : '<div class="muted">Nothing outstanding</div>';
      Modal.open({ title: `Outstanding items (${items.length})`, body, width: '96vw',
        buttons: [
          { label: 'Download CSV', cls: 'btn-primary', onClick: () => {
            const q = v => `"${String(v ?? '').replace(/"/g, '""')}"`;
            const csv = ['Artist,Title,UPC,Ordered,Received,Outstanding,Orders',
              ...items.map(r => [r.artist, r.title, r.upc, r.ordered, r.received, r.ordered - r.received, r.orders].map(q).join(','))].join('\n');
            const a = document.createElement('a');
            a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
            a.download = 'outstanding.csv';
            a.click();
          } },
          { label: 'Close', onClick: Modal.close },
        ] });
  }

  async _receipts(guid) {
    let items;
    try { ({ items } = await API.get(`/api/orders/${encodeURIComponent(guid)}/receipts`)); }
    catch (e) { return Toast.error(e.message); }
    const body = document.createElement('div');
    body.innerHTML = items.length ? `<div class="table-wrap modal-fit"><table class="variants-table">
      <thead><tr><th>Date</th><th>Title</th><th>UPC</th><th class="num">Qty</th><th></th></tr></thead>
      <tbody>${items.map(r => `<tr>
        <td>${Fmt.datetime(r.created_at)}</td><td>${truncCell(r.title)}</td>
        <td class="mono">${esc(r.upc)}</td><td class="num">${r.qty}</td>
        <td>${r.reversed_at ? '<span class="badge badge-draft">Undone</span>'
          : `<button class="btn btn-ghost btn-sm" data-undo="${r.id}">Undo</button>`}</td></tr>`).join('')}
      </tbody></table></div>` : '<div class="muted">No receipts</div>';
    body.querySelectorAll('[data-undo]').forEach(b => b.addEventListener('click', async () => {
      if (!confirm('Undo this receipt? Inventory will be reduced.')) return;
      try {
        const r = await API.post(`/api/orders/receipts/${b.dataset.undo}/undo`);
        if (r.dry_run) return Toast.warning('Test mode: nothing written');
        Toast.success('Receipt undone');
        Modal.close();
        this._openOrder(guid);
      } catch (e) { Toast.error(e.message); }
    }));
    Modal.open({ title: 'Receipts', body, width: '800px',
      buttons: [{ label: 'Close', onClick: Modal.close }] });
  }
}