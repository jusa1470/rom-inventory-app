import { App } from "./core.js";

// ── DOM builder ───────────────────────────────────────────────────────────────
export function h(tag, attrs={}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'class') el.className = v;
    else if (k === 'html') el.innerHTML = v;
    else el.setAttribute(k, v);
  }
  for (const c of children.flat()) {
    if (c == null || c === false) continue;
    el.appendChild(typeof c === 'string' ? document.createTextNode(c) : c);
  }
  return el;
}

// ── Formatting ────────────────────────────────────────────────────────────────
export function fmt(isoStr) {
  if (!isoStr) return '—';
  const d = new Date(isoStr);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    + ' ' + d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
}

export function fmtPrice(n) {
  if (n == null) return '—';
  return '$' + Number(n).toFixed(2);
}

export function parseJSON(str) {
  try { return JSON.parse(str); } catch { return null; }
}

// ── Badges ────────────────────────────────────────────────────────────────────
export function badge(text, cls) {
  return h('span', { class: `badge ${cls}` }, text);
}

export function statusBadge(status) {
  const map = { ACTIVE: 'badge-active', DRAFT: 'badge-draft', ARCHIVED: 'badge-used' };
  return badge(status || '—', map[status] || 'badge-draft');
}

// ── Common UI elements ────────────────────────────────────────────────────────
export function spinner() {
  return h('span', { class: 'spinner' });
}

export function emptyState(icon, text) {
  return h('div', { class: 'empty-state' },
    h('div', { class: 'empty-state-icon' }, icon),
    h('div', { class: 'empty-state-text' }, text)
  );
}

function loadingState() {
  return h('div', { class: 'empty-state' }, spinner(), h('span', {}, 'Loading…'));
}

// ── Toast ─────────────────────────────────────────────────────────────────────
export function showToast(msg, type='info') {
  if (App._toastTimer) clearTimeout(App._toastTimer);
  App.toast = { msg, type };
  renderToast();
  App._toastTimer = setTimeout(() => { App.toast = null; renderToast(); }, 4000);
}

function renderToast() {
  let el = document.getElementById('toast');
  if (!el) {
    el = document.createElement('div');
    el.id = 'toast';
    el.style.cssText = 'position:fixed;bottom:24px;right:24px;z-index:9999;min-width:260px;max-width:400px;';
    document.body.appendChild(el);
  }
  if (!App.toast) { el.innerHTML = ''; return; }
  const typeMap = { info: 'alert-info', success: 'alert-success', error: 'alert-error', warning: 'alert-warning' };
  el.innerHTML = `<div class="alert ${typeMap[App.toast.type] || 'alert-info'}" style="box-shadow:var(--shadow-lg)">${App.toast.msg}</div>`;
}

// ── Button loading state ──────────────────────────────────────────────────────
export async function withLoading(btn, fn) {
  const orig = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>';
  try { return await fn(); }
  finally { btn.disabled = false; btn.innerHTML = orig; }
}

// ── Pagination ────────────────────────────────────────────────────────────────
export function makePaginator(rows, renderFn, defaultSize = 50) {
  let page = 1;
  let pageSize = defaultSize;

  function totalPages() { return Math.max(1, Math.ceil(rows.length / pageSize)); }

  function doRender() {
    const start = (page - 1) * pageSize;
    renderFn(rows.slice(start, start + pageSize));
    updateControls();
  }

  const info    = h('span', { style: 'font-size:12px;color:var(--text-muted);' }, '');
  const prevBtn = h('button', { class: 'btn btn-ghost btn-sm', onClick: () => { if (page > 1) { page--; doRender(); } } }, '←');
  const nextBtn = h('button', { class: 'btn btn-ghost btn-sm', onClick: () => { if (page < totalPages()) { page++; doRender(); } } }, '→');

  const sizeSel = h('select', { class: 'select', style: 'height:28px;font-size:12px;width:auto;' });
  sizeSel.addEventListener('change', e => { pageSize = +e.target.value; page = 1; doRender(); });
  for (const n of [10, 25, 50, 100, 250]) {
    const opt = document.createElement('option');
    // @ts-ignore
    opt.value = n; opt.textContent = n;
    if (n === defaultSize) opt.selected = true;
    sizeSel.appendChild(opt);
  }

  function updateControls() {
    prevBtn.disabled = page === 1;
    nextBtn.disabled = page === totalPages();
    info.textContent = rows.length
      ? `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, rows.length)} of ${rows.length}`
      : '0 results';
  }

  const bar = h('div', { style: 'display:flex;align-items:center;gap:8px;margin-top:12px;justify-content:flex-end;' },
    info, sizeSel, prevBtn, nextBtn,
  );

  function reset(newRows) {
    rows = newRows;
    page = 1;
    doRender();
    updateControls();
  }

  return { bar, render: doRender, reset };
}

// ── Modal ─────────────────────────────────────────────────────────────────────
export function renderModal(title, ...bodyChildren) {
  const overlay = h('div', {
    style: 'position:fixed;inset:0;background:rgba(0,0,0,0.6);z-index:1000;display:flex;align-items:center;justify-content:center;animation:fadeIn 0.15s ease;',
    onClick: e => { if (e.target === overlay) closeModal(); },
  });

  const modal = h('div', {
    style: 'background:var(--bg-card);border:1px solid var(--border-light);border-radius:var(--radius-xl);padding:32px;width:480px;max-width:95vw;max-height:85vh;overflow-y:auto;box-shadow:var(--shadow-lg);',
  },
    h('h3', { style: 'margin-bottom:20px;font-size:20px;' }, title),
    ...bodyChildren,
  );

  overlay.appendChild(modal);
  overlay.id = 'modal-overlay';
  return overlay;
}

export function closeModal() {
  const m = document.getElementById('modal-overlay');
  if (m) m.remove();
}