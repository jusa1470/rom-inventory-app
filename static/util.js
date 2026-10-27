export function el(html) {
    const t = document.createElement('template');
    t.innerHTML = html.trim();
    return t.content.firstChild;
  }
  
  export function esc(str) {
    return String(str ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  
  function toDate(v) {
    let s = String(v).replace(' ', 'T');
    if (!/[zZ]|[+-]\d\d:\d\d$/.test(s)) s += 'Z';
    return new Date(s);
  }
  
  export const Fmt = {
    price: v => {
      const n = parseFloat(v);
      return Number.isNaN(n) ? '—' : `$${n.toFixed(2)}`;
    },
    date: v => (v ? toDate(v).toLocaleDateString() : '—'),
    datetime: v => (v ? toDate(v).toLocaleString() : '—'),
    qty: v => (v != null ? v : '—'),
    upc: v => v || '—',
  };
  
  export function truncCell(text) {
    const t = String(text ?? '');
    return `<span class="cell-truncate" title="${esc(t)}">${esc(t || '—')}</span>`;
  }
  
  export function thumb(url, title) {
    if (url) {
      return `<img class="product-thumb" src="${esc(url)}" alt="${esc(title)}" onerror="this.style.display='none'">`;
    }
    return '<div class="product-thumb-placeholder">♫</div>';
  }
  
  export function statusBadge(status) {
    const map = { ACTIVE: 'badge-active', DRAFT: 'badge-draft', ARCHIVED: 'badge-draft' };
    return `<span class="badge ${map[status] || 'badge-draft'}">${esc(status || '?')}</span>`;
  }
  
  export function debounce(fn, ms = 300) {
    let t;
    return (...args) => {
      clearTimeout(t);
      t = setTimeout(() => fn(...args), ms);
    };
  }
  
  export function buildPager(container, { page, per_page, total }, onPage) {
    const pages = Math.max(1, Math.ceil(total / per_page));
    const from = total ? (page - 1) * per_page + 1 : 0;
    const to = Math.min(page * per_page, total);
    const summary = total
      ? `Showing ${from}–${to} of ${total.toLocaleString()}`
      : 'No results';
    container.innerHTML = `
      <div class="pager">
        <button class="btn btn-ghost btn-sm" data-p="${page - 1}" ${page <= 1 ? 'disabled' : ''}>‹ Prev</button>
        <span class="muted">Page ${page} of ${pages}</span>
        <button class="btn btn-ghost btn-sm" data-p="${page + 1}" ${page >= pages ? 'disabled' : ''}>Next ›</button>
        <span class="muted pager-summary">${summary}</span>
      </div>`;
    container.querySelectorAll('[data-p]').forEach(btn =>
      btn.addEventListener('click', () => onPage(+btn.dataset.p)));
  }