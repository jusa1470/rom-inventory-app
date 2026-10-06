const root = document.getElementById('root');

async function api(path, opts = {}) {
  const res = await fetch('/api' + path, {
    method: opts.method || 'GET',
    headers: { 'Content-Type': 'application/json' },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw Object.assign(new Error(e.detail || res.statusText), { status: res.status });
  }
  return res.json();
}

function el(html) {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstChild;
}

function renderLogin() {
  const box = el(`<div class="center"><form class="box">
    <h1>Record<span>Sync</span></h1>
    <input type="password" name="pw" placeholder="Password" autofocus/>
    <div class="err"></div>
    <button>Unlock</button></form></div>`);
  box.querySelector('form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await api('/login', { method: 'POST', body: { password: e.target.pw.value } });
      renderApp();
    } catch (err) {
      box.querySelector('.err').textContent = err.message;
      e.target.pw.value = '';
    }
  });
  root.replaceChildren(box);
}

const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const PAGES = { products: renderProducts, sync: renderSync };
let pollTimer = null;

function renderApp(page = 'products') {
  clearInterval(pollTimer);
  const shell = el(`<div><nav><strong>RecordSync</strong>
    ${Object.keys(PAGES).map((k) => `<button data-p="${k}" class="${k === page ? 'on' : ''}">${k}</button>`).join('')}
    <span class="sp"></span><button id="lock">Lock</button></nav><main></main></div>`);
  shell.querySelectorAll('[data-p]').forEach((b) => (b.onclick = () => renderApp(b.dataset.p)));
  shell.querySelector('#lock').onclick = async () => { await api('/logout', { method: 'POST' }); renderLogin(); };
  shell.querySelector('main').appendChild(PAGES[page]());
  root.replaceChildren(shell);
}

function renderProducts() {
  const page = el(`<div><input id="q" placeholder="Search title, artist, handle, UPC, SKU…"/>
    <table><thead><tr><th></th><th>Title</th><th>Artist</th><th>Handle</th><th>Barcode</th>
    <th>Variants</th><th>Price</th><th>Qty</th><th>Status</th></tr></thead><tbody></tbody></table>
    <div class="pager"><span id="info"></span><button id="prev">←</button><button id="next">→</button></div></div>`);
  const LIMIT = 50;
  let offset = 0, debounce;
  async function load() {
    const q = page.querySelector('#q').value;
    const { total, rows } = await api(`/shopify/products?q=${encodeURIComponent(q)}&limit=${LIMIT}&offset=${offset}`);
    page.querySelector('tbody').innerHTML = rows.map((r) => {
      let img = ''; try { img = JSON.parse(r.image_urls || '[]')[0] || ''; } catch {}
      return `<tr><td>${img ? `<img src="${esc(img)}" width="40" height="40"/>` : ''}</td>
        <td>${esc(r.title)}</td><td>${esc(r.vendor)}</td><td class="mono">${esc(r.handle)}</td>
        <td class="mono">${esc(r.barcode || r.upc_metafield)}</td><td>${r.variant_count}</td>
        <td>${r.price != null ? '$' + r.price.toFixed(2) : ''}</td><td>${r.inventory ?? ''}</td>
        <td>${esc(r.status)}</td></tr>`;
    }).join('');
    page.querySelector('#info').textContent = total ? `${offset + 1}–${Math.min(offset + LIMIT, total)} of ${total}` : '0 results';
    page.querySelector('#prev').disabled = offset === 0;
    page.querySelector('#next').disabled = offset + LIMIT >= total;
  }
  page.querySelector('#q').oninput = () => { clearTimeout(debounce); debounce = setTimeout(() => { offset = 0; load(); }, 300); };
  page.querySelector('#prev').onclick = () => { offset = Math.max(0, offset - LIMIT); load(); };
  page.querySelector('#next').onclick = () => { offset += LIMIT; load(); };
  load();
  return page;
}

function renderSync() {
  const page = el(`<div><h2>Shopify</h2><div class="row">
    <button id="recent">Sync recent</button><button id="full">Full sync</button>
    <button id="cancel" class="ghost">Cancel</button></div><p id="msg"></p><p id="last" class="muted"></p></div>`);
  const msg = page.querySelector('#msg');
  async function refresh() {
    const s = await api('/sync/status');
    const prog = s.running ? ` (${s.processed}${s.total != null ? '/' + s.total : ''})` : '';
    msg.textContent = (s.error ? `Error: ${s.error}` : s.message) + prog;
    page.querySelector('#last').textContent = s.last_sync ? `Last sync: ${s.last_sync}` : 'Never synced';
    page.querySelectorAll('#recent,#full').forEach((b) => (b.disabled = s.running));
    page.querySelector('#cancel').disabled = !s.running;
  }
  const start = (mode) => async () => {
    try { await api(`/sync/shopify?mode=${mode}`, { method: 'POST' }); } catch (e) { msg.textContent = e.message; }
    refresh();
  };
  page.querySelector('#recent').onclick = start('recent');
  page.querySelector('#full').onclick = start('full');
  page.querySelector('#cancel').onclick = () => api('/sync/cancel', { method: 'POST' });
  refresh();
  pollTimer = setInterval(refresh, 1500);
  return page;
}

api('/me').then(() => renderApp()).catch(renderLogin);
