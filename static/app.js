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
const PAGES = { products: renderProducts, plan: renderPlan, rules: renderRules, sync: renderSync };
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


// ── Plan: classify existing products into product / variants ────────
const post = (path, body) => api(path, { method: 'POST', body });

function renderPlan() {
  const page = el(`<div>
    <div class="row"><button id="build">Rebuild plan</button><span id="sum" class="muted"></span></div>
    <div id="terms"></div>
    <div class="row"><select id="flt"><option value="review">Needs review</option><option value="ready">Ready</option>
      <option value="approved">Approved</option><option value="all">All</option></select>
      <input id="q" placeholder="Search…"/></div>
    <div id="groups"></div>
    <div class="pager"><span id="info"></span><button id="prev">←</button><button id="next">→</button></div></div>`);
  const LIMIT = 25; let offset = 0, debounce;
  const $ = (sel) => page.querySelector(sel);

  async function loadTerms() {
    const terms = await api('/plan/unknown-terms');
    const box = $('#terms');
    if (!terms.length) { box.innerHTML = ''; return; }
    box.innerHTML = `<h3>Needs a rule (${terms.length})</h3>` + terms.map((t, i) => `
      <div class="term" data-i="${i}">
        <div><strong>${esc(t.label)}</strong> <span class="muted">· ${t.count} product${t.count > 1 ? 's' : ''}</span>
          <div class="muted">${t.examples.map(esc).join(' | ')}</div></div>
        <div class="row">
          ${t.suggestion ? `<button data-act="accept">Accept: ${t.suggestion.map((r) => `${esc(r.term)}→${esc(r.kind)}${r.value ? ':' + esc(r.value) : ''}`).join(', ')}</button>` : ''}
          <select>${t.kinds.map((k) => `<option>${k}</option>`).join('')}</select>
          <input placeholder="value"/><button data-act="save">Save rule</button>
        </div></div>`).join('');
    box.querySelectorAll('.term').forEach((row) => {
      const t = terms[row.dataset.i];
      row.querySelector('[data-act=accept]')?.addEventListener('click', async () => {
        await post('/plan/rules', t.suggestion); refresh();
      });
      row.querySelector('[data-act=save]').onclick = async () => {
        const kind = row.querySelector('select').value;
        const value = row.querySelector('input').value;
        try { await post('/plan/rules', [{ term: t.term, kind, value }]); refresh(); }
        catch (e) { alert(e.message); }
      };
    });
  }

  async function loadGroups() {
    const f = $('#flt').value, q = $('#q').value;
    const d = await api(`/plan/groups?filter=${f}&q=${encodeURIComponent(q)}&limit=${LIMIT}&offset=${offset}`);
    const m = d.summary;
    $('#sum').textContent = `${m.total || 0} products · ${m.ready || 0} ready · ${m.review || 0} need review · ${m.approved || 0} approved`;
    $('#groups').innerHTML = d.groups.map((g) => `
      <div class="grp" data-id="${g.id}"><div class="gh"><div><strong>${esc(g.title)}</strong>
        <span class="muted">${esc(g.vendor)} · <span class="mono">${esc(g.handle)}</span></span></div>
        ${g.status === 'draft' ? `<button data-act="approve" ${g.nr ? 'disabled' : ''}>Approve</button>`
          : `<span class="muted">${g.status}</span> ${g.status === 'approved' ? '<button data-act="unapprove" class="ghost">Undo</button>' : ''}`}</div>
        <table><thead><tr><th>Edition</th><th>Color</th><th>Attributes</th><th>From</th><th>Price</th><th>Qty</th><th></th></tr></thead><tbody>
        ${g.variants.map((v) => `<tr data-v="${v.id}" class="${v.status === 'needs_review' ? 'warn' : ''}">
          ${['edition', 'color', 'attributes'].map((k) => `<td><input data-k="${k}" value="${esc(v[k])}" ${g.status === 'applied' ? 'disabled' : ''}/></td>`).join('')}
          <td>${esc(v.source_title)}</td><td>${v.price != null ? '$' + v.price.toFixed(2) : ''}</td><td>${v.qty ?? ''}</td>
          <td class="muted">${esc(v.reason || '')}</td></tr>`).join('')}</tbody></table></div>`).join('')
      || '<p class="muted">Nothing here.</p>';
    $('#info').textContent = d.total ? `${offset + 1}–${Math.min(offset + LIMIT, d.total)} of ${d.total}` : '';
    $('#prev').disabled = offset === 0; $('#next').disabled = offset + LIMIT >= d.total;
    page.querySelectorAll('.grp').forEach((gEl) => {
      const id = gEl.dataset.id;
      gEl.querySelector('[data-act=approve]')?.addEventListener('click', async () => {
        try { await post(`/plan/groups/${id}/approve`); loadGroups(); } catch (e) { alert(e.message); }
      });
      gEl.querySelector('[data-act=unapprove]')?.addEventListener('click', async () => {
        await post(`/plan/groups/${id}/unapprove`); loadGroups();
      });
      gEl.querySelectorAll('tr[data-v] input').forEach((inp) => {
        inp.onchange = async () => {
          const body = {}; body[inp.dataset.k] = inp.value;
          try { await api(`/plan/variants/${inp.closest('tr').dataset.v}`, { method: 'PATCH', body }); loadGroups(); }
          catch (e) { alert(e.message); }
        };
      });
    });
  }

  const refresh = () => { loadTerms(); loadGroups(); };
  $('#build').onclick = async () => { $('#build').disabled = true; await post('/plan/build'); $('#build').disabled = false; refresh(); };
  $('#flt').onchange = () => { offset = 0; loadGroups(); };
  $('#q').oninput = () => { clearTimeout(debounce); debounce = setTimeout(() => { offset = 0; loadGroups(); }, 300); };
  $('#prev').onclick = () => { offset = Math.max(0, offset - LIMIT); loadGroups(); };
  $('#next').onclick = () => { offset += LIMIT; loadGroups(); };
  refresh();
  return page;
}

function renderRules() {
  const page = el(`<div><p class="muted">Rules you've taught the app. Deleting one re-opens those products for review.</p>
    <table><thead><tr><th>Term</th><th>Kind</th><th>Value</th><th></th></tr></thead><tbody></tbody></table></div>`);
  async function load() {
    const rules = await api('/plan/rules');
    page.querySelector('tbody').innerHTML = rules.map((r) => `<tr><td class="mono">${esc(r.term)}</td>
      <td>${esc(r.kind)}</td><td>${esc(r.value)}</td><td><button class="ghost" data-t="${esc(r.term)}">Delete</button></td></tr>`).join('');
    page.querySelectorAll('button[data-t]').forEach((b) => (b.onclick = async () => {
      await api(`/plan/rules?term=${encodeURIComponent(b.dataset.t)}`, { method: 'DELETE' }); load();
    }));
  }
  load();
  return page;
}
