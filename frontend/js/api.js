/* Centralized fetch wrapper. All API calls go through here. */
const API = (() => {
  async function request(method, path, body) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const resp = await fetch(path, opts);
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
    return data;
  }

  return {
    get:    (path)        => request('GET',    path),
    post:   (path, body)  => request('POST',   path, body),
    put:    (path, body)  => request('PUT',    path, body),
    delete: (path)        => request('DELETE', path),
  };
})();

/* Format helpers */
const Fmt = {
  price:  v => v != null ? `$${parseFloat(v).toFixed(2)}` : '—',
  margin: v => v != null ? `${(v * 100).toFixed(1)}%` : '—',
  date:   v => {
    if (!v) return '—';
    let s = String(v).replace(' ', 'T');
    if (!/[zZ]|[+-]\d\d:\d\d$/.test(s)) s += 'Z';
    return new Date(s).toLocaleDateString();
  },
  datetime: v => {
    if (!v) return '—';
    let s = String(v).replace(' ', 'T');
    if (!/[zZ]|[+-]\d\d:\d\d$/.test(s)) s += 'Z';
    return new Date(s).toLocaleString();
  },
  qty:    v => v != null ? v : '—',
  upc:    v => v || '—',
};

function pageRange(data) {
  const { page, per_page, total } = data;
  if (!total) return 'No results';
  const from = (page - 1) * per_page + 1;
  const to   = Math.min(page * per_page, total);
  return `Showing ${from}–${to} of ${total.toLocaleString()}`;
}

function buildPager(container, data, onPage, topContainerId) {
  const { page, pages } = data;
  const summary = `<span style="font-size:12px;color:var(--text-muted)">${pageRange(data)}</span>`;
  if (topContainerId) {
    const top = document.getElementById(topContainerId);
    if (top) top.innerHTML = summary;
  }
  if (pages <= 1) { container.innerHTML = summary; return; }
  container.innerHTML = `
    <div class="row center" style="gap:6px;justify-content:center;padding:16px 0;flex-wrap:wrap">
      <button class="btn btn-ghost btn-sm" ${page <= 1 ? 'disabled' : ''} data-p="${page - 1}">‹ Prev</button>
      <span style="font-size:12px;color:var(--text-muted)">Page</span>
      <input id="pager-goto" type="number" min="1" max="${pages}" value="${page}"
        style="width:52px;height:28px;padding:0 6px;text-align:center;background:var(--bg-base);
               border:1px solid var(--border-light);border-radius:var(--radius-sm);
               color:var(--text-primary);font-size:12px;font-family:'DM Mono',monospace">
      <span style="font-size:12px;color:var(--text-muted)">of ${pages}</span>
      <button class="btn btn-ghost btn-sm" ${page >= pages ? 'disabled' : ''} data-p="${page + 1}">Next ›</button>
      <span style="font-size:12px;color:var(--text-muted);margin-left:8px">${pageRange(data)}</span>
    </div>`;
  container.querySelectorAll('[data-p]').forEach(btn =>
    btn.addEventListener('click', () => onPage(+btn.dataset.p)));
  const gi = container.querySelector('#pager-goto');
  const go = () => { const p = Math.max(1, Math.min(pages, parseInt(gi.value)||1)); if (p !== page) onPage(p); };
  gi.addEventListener('change', go);
  gi.addEventListener('keydown', e => { if (e.key === 'Enter') go(); });
}

function buildSortableHead(thead, cols, sort, colFilters, onSort, onFilter) {
  const [base, dir] = (sort || '').split(/_(?=[^_]+$)/);
  const showFilters = !!onFilter && cols.some(c => c.filterable);
  const is = 'height:24px;font-size:11px;width:100%;background:var(--bg-base);border:1px solid var(--border-light);border-radius:var(--radius-sm);color:var(--text-primary)';
  const fp = 'padding:2px 6px;border-bottom:1px solid var(--border)';
  thead.innerHTML =
    '<tr>' + cols.map(c => {
      const active = c.sortKey && c.sortKey === base;
      const s = [c.thStyle||'', c.sortKey ? 'cursor:pointer;user-select:none' : ''].filter(Boolean).join(';');
      return `<th${s?` style="${s}"`:''}${c.sortKey?` data-sort="${c.sortKey}"`:''}${c.id?` data-col="${c.id}"`:''}>`+
        c.label+(c.sortKey?`<span style="opacity:${active?1:0.25};font-size:10px;margin-left:3px">${active?(dir==='asc'?'↑':'↓'):'↕'}</span>`:'')+'</th>';
    }).join('') + '</tr>' +
    (showFilters ? '<tr>' + cols.map(c => {
      if (!c.filterable) return `<th style="${fp}"${c.id?` data-col="${c.id}"`:''}></th>`;
      const val = (colFilters||{})[c.id] || '';
      if (c.filterType === 'select') return `<th style="${fp}"${c.id?` data-col="${c.id}"`:''}><select class="col-filter" data-col-id="${c.id}" style="${is};padding:0 4px">
        <option value="">All</option>${(c.options||[]).map(o=>`<option value="${o}"${val===o?' selected':''}>${o}</option>`).join('')}</select></th>`;
      return `<th style="${fp}"${c.id?` data-col="${c.id}"`:''}><input class="col-filter" data-col-id="${c.id}" value="${esc(val)}" placeholder="…" style="${is};padding:0 6px"></th>`;
    }).join('') + '</tr>' : '');
  thead.querySelectorAll('th[data-sort]').forEach(th =>
    th.addEventListener('click', e => {
      if (e.target.closest('.col-filter')) return;
      const key = th.dataset.sort;
      onSort(base === key && dir === 'asc' ? `${key}_desc` : `${key}_asc`);
    }));
  if (onFilter) {
    thead.querySelectorAll('.col-filter').forEach(el => {
      el.addEventListener(el.tagName==='SELECT'?'change':'input', debounce(()=>onFilter(el.dataset.colId, el.value), 300));
      el.addEventListener('click', e=>e.stopPropagation());
      el.addEventListener('keydown', e=>e.stopPropagation());
    });
  }
}

/* Badge helpers */
function mapStatusBadge(status, confidence) {
  if (!status) return '<span class="badge badge-draft">Unmatched</span>';
  if (status === 'pending')  return '<span class="badge badge-used">Review</span>';
  if (status === 'rejected') return '<span class="badge badge-draft">Rejected</span>';
  if (confidence === 'manual') return '<span class="badge badge-new">Manual</span>';
  return '<span class="badge badge-new">Mapped</span>';
}

function statusBadge(status) {
  const map = {
    ACTIVE:   'badge-active',
    DRAFT:    'badge-draft',
    ARCHIVED: 'badge-draft',
  };
  return `<span class="badge ${map[status] || 'badge-draft'}">${status || '?'}</span>`;
}

/* Debounce */
function debounce(fn, ms = 300) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

/* Escape HTML */
function esc(str) {
  return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function truncCell(text) {
  const t = String(text ?? '');
  return `<span class="cell-truncate" title="${esc(t)}">${esc(t || '—')}</span>`;
}

/* Thumbnail */
function thumb(url, title) {
  if (url) return `<img class="product-thumb" src="${esc(url)}" alt="${esc(title)}" onerror="this.style.display='none'">`;
  return `<div class="product-thumb-placeholder">♫</div>`;
}
