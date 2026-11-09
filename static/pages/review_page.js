import { API } from '../api.js';
import { Modal } from '../components/modal.js';
import { Toast } from '../components/toast.js';
import { Fmt, debounce, esc, truncCell } from '../util.js';

const L = { update: 'Update quantity', map: 'Update quantity + set UPC', variant: 'New variant', new: 'New product + variant' };
const B = { upc: 'UPC match', closest: 'Closest match', manual: 'Manual', none: 'No match' };
const CLS = { update: 'badge-new', map: 'badge-active', variant: 'badge-used', new: 'badge-used' };
const nz = s => (s || '').trim().toLowerCase();
const k = r => `${r.order_guid}|${r.upc}`;
const isNew = r => ['new', 'variant'].includes(r.plan.action);
const diff = r => !isNew(r) && r.wm_cost != null && Math.abs((r.plan.cost || 0) - r.wm_cost) >= 0.005;
const tdiff = r => !isNew(r)
  && (nz(r.plan.product_title) !== nz(r.plan.new_title) || nz(r.plan.variant_title) !== nz(r.plan.new_vtitle));
const SORTS = {
  order: r => r.number, title: r => nz(r.plan.new_title || r.title), artist: r => nz(r.artist),
  action: r => r.plan.action, qty: r => r.qty, cost: r => (diff(r) ? r.wm_cost - (r.plan.cost || 0) : 0),
};

export class ReviewPage {
  constructor(onBack) {
    this.onBack = onBack;
    this.items = [];
    this.sel = new Set();
    this.on = new Set();   // price update ON
    this.toff = new Set(); // title update OFF
    this.q = '';
    this.flt = '';
    this.sort = 'order';
    this.dir = 'asc';
    this._first = true;
  }

  destroy() {}

  async render(c) {
    this.c = c;
    c.innerHTML = `
      <div class="page" id="rv-page">
        <div class="page-title">Review Receipts</div>
        <div class="search-row" style="align-items:center;flex-wrap:wrap">
          <input class="input" id="rv-q" placeholder="Filter title, artist, UPC, order…">
          <select class="input" id="rv-flt" style="max-width:210px">
            <option value="">All actions</option>
            ${Object.entries(L).map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}
            <option value="price">Has price change</option>
            <option value="titles">Has title difference</option>
            <option value="closest">Closest match (verify)</option>
          </select>
          <select class="input" id="rv-sort" style="max-width:170px">
            <option value="order">Sort: Order</option><option value="title">Sort: Title</option>
            <option value="artist">Sort: Artist</option><option value="action">Sort: Action</option>
            <option value="qty">Sort: Qty</option><option value="cost">Sort: Cost change</option>
          </select>
          <button class="btn btn-ghost btn-sm" id="rv-dir">▲</button>
          <button class="btn btn-ghost btn-sm" id="rv-back">‹ Back</button>
        </div>
        <div class="search-row" style="align-items:center;flex-wrap:wrap">
          <button class="btn btn-ghost btn-sm" id="rv-all">Select all (shown)</button>
          <button class="btn btn-ghost btn-sm" id="rv-none">Deselect all</button>
          <button class="btn btn-ghost btn-sm" id="rv-selp">Select price changes</button>
          <button class="btn btn-ghost btn-sm" id="rv-selt">Select title diffs</button>
          <button class="btn btn-ghost btn-sm" id="rv-selc">Select closest matches</button>
          <button class="btn btn-ghost btn-sm" id="rv-selnew">Select new items</button>
          <span class="muted">|</span>
          <button class="btn btn-ghost btn-sm" id="rv-pon">Prices: update all</button>
          <button class="btn btn-ghost btn-sm" id="rv-poff">Prices: none</button>
          <button class="btn btn-ghost btn-sm" id="rv-ton">Titles: update all</button>
          <button class="btn btn-ghost btn-sm" id="rv-toff">Titles: none</button>
          <span class="muted">|</span>
          <button class="btn btn-ghost btn-sm" id="rv-rmsel">Remove selected</button>
          <button class="btn btn-danger btn-sm" id="rv-rmall">Remove all</button>
        </div>
        <div class="muted" id="rv-sum" style="margin-bottom:10px"></div>
        <div class="table-wrap"><table class="variants-table" id="rv-body"></table></div>
        <div class="rv-bar">
          <span id="rv-selinfo" class="muted"></span>
          <div style="flex:1"></div>
          <button class="btn btn-primary" id="rv-push">Push selected</button>
        </div>
      </div>`;
    const $ = s => c.querySelector(s);
    $('#rv-q').addEventListener('input', debounce(e => { this.q = e.target.value.trim().toLowerCase(); this._draw(); }));
    $('#rv-flt').addEventListener('change', e => { this.flt = e.target.value; this._draw(); });
    $('#rv-sort').addEventListener('change', e => { this.sort = e.target.value; this._draw(); });
    $('#rv-dir').addEventListener('click', e => {
      this.dir = this.dir === 'asc' ? 'desc' : 'asc';
      e.target.textContent = this.dir === 'asc' ? '▲' : '▼';
      this._draw();
    });
    $('#rv-back').addEventListener('click', () => this.onBack());
    const pick = (fn, add = true) => () => {
      this._shown().forEach(r => { if (fn(r)) add ? this.sel.add(k(r)) : this.sel.delete(k(r)); });
      this._draw();
    };
    $('#rv-all').addEventListener('click', pick(() => true));
    $('#rv-none').addEventListener('click', () => { this.sel.clear(); this._draw(); });
    $('#rv-selp').addEventListener('click', () => { this.sel = new Set(this.items.filter(diff).map(k)); this._draw(); });
    $('#rv-selt').addEventListener('click', () => { this.sel = new Set(this.items.filter(tdiff).map(k)); this._draw(); });
    $('#rv-selc').addEventListener('click', () => { this.sel = new Set(this.items.filter(r => r.plan.basis === 'closest').map(k)); this._draw(); });
    $('#rv-selnew').addEventListener('click', () => { this.sel = new Set(this.items.filter(isNew).map(k)); this._draw(); });
    $('#rv-pon').addEventListener('click', () => { this.items.filter(diff).forEach(r => this.on.add(k(r))); this._draw(); });
    $('#rv-poff').addEventListener('click', () => { this.on.clear(); this._draw(); });
    $('#rv-ton').addEventListener('click', () => { this.toff.clear(); this._draw(); });
    $('#rv-toff').addEventListener('click', () => { this.items.filter(tdiff).forEach(r => this.toff.add(k(r))); this._draw(); });
    $('#rv-rmsel').addEventListener('click', () => this._remove([...this.sel]));
    $('#rv-rmall').addEventListener('click', async () => {
      if (!confirm('Remove everything from the queue?')) return;
      try { await API.delete('/api/orders/queue'); await this._load(); } catch (e) { Toast.error(e.message); }
    });
    $('#rv-push').addEventListener('click', () => this._push());
    await this._load();
  }

  async _load() {
    try {
      const { items } = await API.get('/api/orders/queue');
      this.items = items;
    } catch (e) { return Toast.error(e.message); }
    const keys = new Set(this.items.map(k));
    if (this._first) { this.sel = new Set(keys); this._first = false; }
    for (const s of [this.sel, this.on, this.toff]) [...s].forEach(x => { if (!keys.has(x)) s.delete(x); });
    this._draw();
  }

  _shown() {
    const f = this.flt;
    let l = this.items.filter(r => {
      if (this.q && !`${r.title} ${r.artist} ${r.upc} ${r.number} ${r.plan.new_title || ''} ${r.plan.product_title || ''}`
        .toLowerCase().includes(this.q)) return false;
      if (!f) return true;
      if (f === 'price') return diff(r);
      if (f === 'titles') return tdiff(r);
      if (f === 'closest') return r.plan.basis === 'closest';
      return r.plan.action === f;
    });
    const fn = SORTS[this.sort];
    l.sort((a, b) => (fn(a) > fn(b) ? 1 : fn(a) < fn(b) ? -1 : 0) * (this.dir === 'asc' ? 1 : -1));
    return l;
  }

  _cmp(r) {
    const p = r.plan, nw = isNew(r);
    const same = !nw && nz(p.variant_title) === nz(p.new_vtitle);
    const tsame = !nw && nz(p.product_title) === nz(p.new_title);
    const vcls = nw ? '' : same ? 'ok' : 'bad';
    const tag = { new: 'Create new product', variant: 'Create new variant', map: 'Existing · UPC will be set', update: 'Existing' }[p.action];
    const title = p.action === 'new' ? p.new_title : p.product_title;
    const vt = nw ? p.new_vtitle : p.variant_title;
    const stock = nw ? '' : `<div class="muted" style="margin-top:4px">stock ${p.stock ?? 0} → ${(p.stock || 0) + r.qty}</div>`;
    return `<div class="cmp2">
      <div class="box"><div class="tag">WebAMI</div><div class="tt">${esc(p.new_title || r.title || '—')}</div>
        <span class="vt ${vcls}">${esc(p.new_vtitle || '—')}</span>
        <div class="muted" style="margin-top:4px">${esc(r.artist || '')} · <span class="mono">${esc(r.upc)}</span></div></div>
      <div class="arrow">→</div>
      <div class="box ${nw ? 'new' : 'shop'}"><div class="tag">Shopify · ${tag}</div>
        <div class="tt" style="${nw || tsame ? '' : 'color:var(--orange)'}">${esc(title || '—')}</div>
        <span class="vt ${vcls}">${esc(vt || '—')}</span>${stock}</div></div>`;
  }

  _draw() {
    const $ = s => this.c.querySelector(s);
    const list = this._shown();
    const sh = (key, label, cls = '') =>
      `<th class="${cls}">${label}</th>`;
    $('#rv-body').innerHTML = `
      <thead><tr><th><input type="checkbox" id="rv-hd" ${list.length && list.every(r => this.sel.has(k(r))) ? 'checked' : ''}></th>
        <th>Order</th><th>Action</th><th>WebAMI vs Shopify</th>
        <th class="num">Cost (Shopify → WebAMI)</th><th class="num">Receive</th><th></th></tr></thead>
      <tbody>${list.length ? list.map(r => `<tr>
        <td><input type="checkbox" data-s="${esc(k(r))}" ${this.sel.has(k(r)) ? 'checked' : ''}></td>
        <td class="mono">${esc(r.number)}</td>
        <td><span class="badge ${CLS[r.plan.action]}">${L[r.plan.action]}</span><div class="muted">${B[r.plan.basis]}</div></td>
        <td class="cmp-cell" style="white-space:normal">${this._cmp(r)}${tdiff(r)
          ? `<label class="check-row" style="margin:6px 0 0"><input type="checkbox" data-t="${esc(k(r))}" ${this.toff.has(k(r)) ? '' : 'checked'}><span>Update Shopify titles to match WebAMI</span></label>` : ''}</td>
        <td class="num" style="min-width:150px;white-space:normal">${diff(r)
          ? `<label class="check-row" style="margin:0;justify-content:flex-end"><input type="checkbox" data-c="${esc(k(r))}" ${this.on.has(k(r)) ? 'checked' : ''}><span>${Fmt.price(r.plan.cost)} → ${Fmt.price(r.wm_cost)} (update price)</span></label>` : '—'}</td>
        <td class="num"><input class="input" type="number" min="1" max="${r.ordered ?? ''}" style="width:70px;height:28px;text-align:right" data-q="${esc(k(r))}" value="${r.qty}"></td>
        <td style="white-space:normal"><div style="display:flex;gap:4px;flex-wrap:wrap">
          <button class="btn btn-ghost btn-sm" data-opt="${esc(k(r))}">Change…</button>
          ${r.plan.basis === 'closest' && r.plan.action === 'map' ? `<button class="btn btn-ghost btn-sm" data-nv="${esc(k(r))}">New variant instead</button>` : ''}
          ${r.plan.basis === 'closest' ? `<button class="btn btn-ghost btn-sm" data-np="${esc(k(r))}">New product instead</button>` : ''}
          ${r.plan.basis === 'manual' ? `<button class="btn btn-ghost btn-sm" data-auto="${esc(k(r))}">Reset</button>` : ''}
          <button class="btn btn-ghost btn-sm" data-rm="${esc(k(r))}">Remove</button></div></td></tr>`).join('')
        : '<tr><td colspan="7" class="empty-cell">Queue is empty</td></tr>'}</tbody>`;

    const cnt = a => this.items.filter(r => r.plan.action === a).length;
    $('#rv-sum').textContent = `${this.items.length} lines · ${this.items.reduce((n, r) => n + r.qty, 0)} units · `
      + `${cnt('update') + cnt('map')} update · ${cnt('variant')} new variant · ${cnt('new')} new product · `
      + `${this.items.filter(diff).length} price changes · ${this.items.filter(tdiff).length} title diffs`;
    const chosen = this.items.filter(r => this.sel.has(k(r)));
    $('#rv-selinfo').textContent = `${chosen.length} selected · ${chosen.reduce((n, r) => n + r.qty, 0)} units · `
      + `${chosen.filter(r => diff(r) && this.on.has(k(r))).length} price updates · `
      + `${chosen.filter(r => tdiff(r) && !this.toff.has(k(r))).length} title updates · ${chosen.filter(isNew).length} creates`;
    $('#rv-push').textContent = `Push selected (${chosen.length})`;

    const by = key => this.items.find(r => k(r) === key);
    const each = (s, fn) => this.c.querySelectorAll(s).forEach(fn);
    const base = r => `/api/orders/queue/${encodeURIComponent(r.order_guid)}/${encodeURIComponent(r.upc)}`;
    const toggle = (set, key, on) => (on ? set.add(key) : set.delete(key));
    $('#rv-hd').addEventListener('change', e => { list.forEach(r => toggle(this.sel, k(r), e.target.checked)); this._draw(); });
    each('[data-s]', c => c.addEventListener('change', () => { toggle(this.sel, c.dataset.s, c.checked); this._draw(); }));
    each('[data-c]', c => c.addEventListener('change', () => { toggle(this.on, c.dataset.c, c.checked); this._draw(); }));
    each('[data-t]', c => c.addEventListener('change', () => { toggle(this.toff, c.dataset.t, !c.checked); this._draw(); }));
    each('[data-q]', inp => inp.addEventListener('change', async () => {
      const r = by(inp.dataset.q), v = parseInt(inp.value, 10);
      if (!(v > 0)) { inp.value = r.qty; return Toast.error('Invalid qty'); }
      try { const res = await API.put(base(r), { qty: v }); r.qty = res.qty; this._draw(); }
      catch (e) { Toast.error(e.message); }
    }));
    each('[data-rm]', b => b.addEventListener('click', () => this._remove([b.dataset.rm], true)));
    each('[data-opt]', b => b.addEventListener('click', () => this._options(by(b.dataset.opt))));
    const retarget = (key, t) => async () => {
      try { await API.put(`${base(by(key))}/target`, t(by(key))); await this._load(); }
      catch (e) { Toast.error(e.message); }
    };
    each('[data-nv]', b => b.addEventListener('click',
      retarget(b.dataset.nv, r => ({ action: 'variant', product_id: r.plan.product_id }))));
    each('[data-np]', b => b.addEventListener('click', retarget(b.dataset.np, () => ({ action: 'new' }))));
    each('[data-auto]', b => b.addEventListener('click', retarget(b.dataset.auto, () => ({ action: 'auto' }))));
  }

  async _remove(keys, quiet = false) {
    if (!keys.length) return Toast.info('Nothing selected');
    if (!quiet && !confirm(`Remove ${keys.length} from queue?`)) return;
    try { await API.post('/api/orders/queue/remove', { keys }); await this._load(); }
    catch (e) { Toast.error(e.message); }
  }

  async _push() {
    const chosen = this.items.filter(r => this.sel.has(k(r)));
    if (!chosen.length) return Toast.info('Nothing selected');
    const n = chosen.filter(isNew).length;
    if (n && !confirm(`${n} line(s) will create new products/variants. Continue?`)) return;
    const btn = this.c.querySelector('#rv-push');
    const label = btn.textContent;
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span>Pushing…';
    try {
      const r = await API.post('/api/orders/queue/push', {
        keys: chosen.map(k),
        cost_keys: chosen.filter(x => diff(x) && this.on.has(k(x))).map(k),
        title_keys: chosen.filter(x => tdiff(x) && !this.toff.has(k(x))).map(k),
      });
      if (r.dry_run) Toast.warning('Test mode: nothing written');
      else {
        const msg = `Updated ${r.updated}, new variants ${r.variants}, new products ${r.created}`;
        r.errors.length ? Toast.warning(`${msg}; ${r.errors[0]}`) : Toast.success(msg);
      }
      await this._load();
    } catch (e) { Toast.error(e.message); }
    btn.disabled = false;
    btn.textContent = label;
    this._draw();
  }

  async _options(r) {
    const base = `/api/orders/queue/${encodeURIComponent(r.order_guid)}/${encodeURIComponent(r.upc)}`;
    const body = document.createElement('div');
    body.innerHTML = `
      <div>${esc(r.plan.new_title || r.title)} — ${esc(r.artist || '')}</div>
      <div class="muted">${esc(r.plan.new_vtitle || '')} · <span class="mono">UPC ${esc(r.upc)}</span></div>
      <div class="search-row" style="margin-top:12px">
        <input class="input" id="op-q" placeholder="Search Shopify title, vendor or UPC…">
        <button class="btn btn-ghost" id="op-go">Search</button></div>
      <div id="op-list"></div>`;
    const list = body.querySelector('#op-list');
    const set = async t => {
      try { await API.put(`${base}/target`, t); Modal.close(); await this._load(); }
      catch (e) { Toast.error(e.message); }
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
        { label: 'Close', onClick: Modal.close },
      ],
    });
  }
}