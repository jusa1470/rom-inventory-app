const ORDER_COLS = [
  { id:'order_number',    label:'Order #',    sortKey:'order_number',   filterable:true,  thStyle:'text-align:left' },
  { id:'order_name',      label:'Order Name', sortKey:'order_name',     filterable:true,  thStyle:'text-align:left' },
  { id:'order_date',      label:'Date',       sortKey:'order_date',     filterable:false },
  { id:'item_count',      label:'Items',      sortKey:'item_count',     filterable:false, thStyle:'text-align:center' },
  { id:'total_qty',       label:'Ordered',    sortKey:'total_qty',      filterable:false, thStyle:'text-align:center' },
  { id:'total_received',  label:'Received',   sortKey:'total_received', filterable:false, thStyle:'text-align:center' },
  { id:'status',          label:'Status',     sortKey:'status',         filterable:true,
    filterType:'select', options:['pending','partial','complete'], thStyle:'text-align:center' },
];
const ORDER_COL_WIDTHS = { order_number:150, order_name:160, order_date:100, item_count:60, total_qty:80, total_received:80, status:90 };

class OrdersPage {
  constructor() {
    this.page       = 1;
    this.sort       = 'order_date_desc';
    this.colFilters = {};
    this._cancelId  = null;
  }

  async render(container) {
    container.innerHTML = `
      <div class="page">
        <div class="page-title">Orders</div>
        <div id="orders-top-summary" style="min-height:18px;margin-bottom:6px"></div>
        <div class="row" style="margin-bottom:16px;gap:10px;align-items:center">
          <button class="btn btn-primary" id="sync-webami-btn">Sync from Webami</button>
          <button class="btn btn-ghost btn-sm" id="cancel-sync-btn" style="display:none">Cancel</button>
          <div id="sync-msg" style="font-size:12px;color:var(--text-muted)"></div>
        </div>
        <div class="table-wrap">
          <table>
            <colgroup>${ORDER_COLS.map(c=>`<col style="width:${ORDER_COL_WIDTHS[c.id]||100}px">`).join('')}</colgroup>
            <thead id="orders-thead"></thead>
            <tbody id="orders-body"><tr><td colspan="${ORDER_COLS.length}" style="text-align:center;padding:32px;color:var(--text-muted)">Loading…</td></tr></tbody>
          </table>
        </div>
        <div id="orders-pager"></div>
      </div>`;

    document.getElementById('sync-webami-btn').addEventListener('click', () => this._sync());
    document.getElementById('cancel-sync-btn').addEventListener('click', () => this._cancelSync());
    await this._load();
  }

  async _load() {
    const body  = document.getElementById('orders-body');
    const thead = document.getElementById('orders-thead');
    if (!body || !thead) return;
    buildSortableHead(thead, ORDER_COLS, this.sort, this.colFilters,
      s => { this.sort = s; this.page = 1; this._load(); },
      (col, val) => { this.colFilters[col] = val; this.page = 1; this._load(); });
    body.innerHTML = `<tr><td colspan="${ORDER_COLS.length}" style="text-align:center;padding:24px;color:var(--text-muted)">Loading…</td></tr>`;
    try {
      const qs = new URLSearchParams({
        page: this.page, per_page: 30, sort: this.sort,
        q_number: this.colFilters.order_number || '',
        q_name:   this.colFilters.order_name   || '',
        status:   this.colFilters.status       || '',
      });
      const data = await API.get(`/api/orders?${qs}`);
      const items = data.items || [];
      if (!items.length) {
        body.innerHTML = `<tr><td colspan="${ORDER_COLS.length}" style="text-align:center;padding:32px;color:var(--text-muted)">
          ${data.total===0 ? 'No orders yet — click "Sync from Webami" to import' : 'No orders match the filter'}
        </td></tr>`;
        buildPager(document.getElementById('orders-pager'), data, p=>{this.page=p;this._load();}, 'orders-top-summary');
        return;
      }
      const cls = { complete:'badge-new', partial:'badge-used', pending:'badge-draft' };
      body.innerHTML = items.map(o => `
        <tr style="cursor:pointer" onclick="location.hash='#receiving?order=${o.id}'">
          <td class="mono" style="font-size:12px;text-align:left">${esc(o.order_number||o.webami_order_id||'—')}</td>
          <td class="cell-truncate" style="font-size:12px;color:var(--text-secondary);text-align:left" title="${esc(o.order_name||'')}">${esc(o.order_name||'—')}</td>
          <td style="font-size:12px">${Fmt.date(o.order_date)}</td>
          <td style="text-align:center">${o.item_count??'—'}</td>
          <td style="text-align:center">${o.total_qty??0}</td>
          <td style="text-align:center">${o.total_received??0}</td>
          <td style="text-align:center"><span class="badge ${cls[o.status]||'badge-draft'}">${esc(o.status)}</span></td>
        </tr>`).join('');
      buildPager(document.getElementById('orders-pager'), data, p=>{this.page=p;this._load();}, 'orders-top-summary');
    } catch (e) {
      body.innerHTML = `<tr><td colspan="${ORDER_COLS.length}" style="color:var(--red);padding:16px">${esc(e.message)}</td></tr>`;
    }
  }

  async _cancelSync() {
    if (!this._cancelId) return;
    try { await API.post(`/api/sync/cancel/${this._cancelId}`); Toast.info('Cancelling…'); } catch (_) {}
  }

  async _sync() {
    const btn    = document.getElementById('sync-webami-btn');
    const cancel = document.getElementById('cancel-sync-btn');
    const msg    = document.getElementById('sync-msg');
    btn.disabled = true; btn.innerHTML = '<span class="spinner"></span> Syncing…';
    cancel.style.display = 'inline-flex'; msg.textContent = '';
    try {
      const { job_id } = await API.post('/api/orders/sync-webami');
      this._cancelId = job_id;
      await this._poll(job_id, s => { msg.textContent = s.message || '…'; });
      Toast.success('Orders synced from Webami');
      this.page = 1; await this._load();
    } catch (e) {
      if (!e.message?.includes('cancel')) Toast.error(e.message);
    } finally {
      btn.disabled = false; btn.textContent = 'Sync from Webami';
      cancel.style.display = 'none'; msg.textContent = '';
      this._cancelId = null;
    }
  }

  _poll(jobId, onProgress) {
    return new Promise((resolve, reject) => {
      const t = setInterval(async () => {
        try {
          const s = await API.get(`/api/sync/status/${jobId}`);
          onProgress(s);
          if (s.status==='done')      { clearInterval(t); resolve(s); }
          if (s.status==='error')     { clearInterval(t); reject(new Error(s.error||'Sync failed')); }
          if (s.status==='cancelled') { clearInterval(t); resolve(s); }
        } catch (e) { clearInterval(t); reject(e); }
      }, 1500);
    });
  }
}