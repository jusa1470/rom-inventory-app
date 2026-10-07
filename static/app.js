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
const PAGES = { products: renderProducts, plan: renderPlan, apply: renderApply, rules: renderRules, sync: renderSync };
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
      <option value="approved">Approved</option><option value="unclassified">Unclassified</option><option value="all">All</option></select>
      <input id="q" placeholder="Search…"/></div>
    <div id="groups"></div>
    <div class="pager"><span id="info"></span><button id="prev">←</button><button id="next">→</button></div></div>`);
  const LIMIT = 25; let offset = 0, debounce;
  const $ = (sel) => page.querySelector(sel);

  async function loadTerms() {
    const terms = await api('/plan/unknown-terms');
    const box = $('#terms');
    if (!terms.length) { box.innerHTML = ''; return; }
    box.innerHTML = `<h3>Needs a rule (${terms.length})</h3>` + terms.slice(0, 20).map((t, i) => {
      const seg = t.kinds.includes('segment'), pf = t.prefill || {};
      return `<div class="term" data-i="${i}">
        <div><strong>${esc(t.label)}</strong> <span class="muted">· ${t.count} product${t.count > 1 ? 's' : ''}</span>
          <div class="muted">${t.examples.map(esc).join(' | ')}</div></div>
        <div class="row">
          ${seg ? `<input data-f="edition" placeholder="Edition" value="${esc(pf.edition)}"/>
            <input data-f="color" placeholder="Color" value="${esc(pf.color)}"/>
            <input data-f="attributes" placeholder="Attributes (comma)" value="${esc(pf.attributes)}"/>
            <button data-act="segment">Save</button><button class="ghost" data-act="title">Part of title</button>
            <button class="ghost" data-act="ignore">Ignore</button>`
          : `<input data-f="value" placeholder="value"/><button data-act="default">Save</button>`}
          ${t.suggestion ? `<button class="ghost" data-act="accept" title="${esc(JSON.stringify(t.suggestion))}">Accept suggestion</button>` : ''}
        </div></div>`;
    }).join('') + (terms.length > 20 ? `<p class="muted">+ ${terms.length - 20} more after these</p>` : '');
    box.querySelectorAll('.term').forEach((row) => {
      const t = terms[row.dataset.i];
      const val = (f) => row.querySelector(`[data-f=${f}]`)?.value || '';
      const send = async (rules) => { try { await post('/plan/rules', rules); refresh(); } catch (e) { alert(e.message); } };
      row.querySelector('[data-act=accept]')?.addEventListener('click', () => send(t.suggestion));
      row.querySelector('[data-act=segment]')?.addEventListener('click', () => send([{ term: t.term, kind: 'segment',
        value: JSON.stringify({ edition: val('edition'), color: val('color'), attributes: val('attributes') }) }]));
      row.querySelector('[data-act=title]')?.addEventListener('click', () => send([{ term: t.term, kind: 'title' }]));
      row.querySelector('[data-act=ignore]')?.addEventListener('click', () => send([{ term: t.term, kind: 'ignore' }]));
      row.querySelector('[data-act=default]')?.addEventListener('click', () => send([{ term: t.term, kind: 'default', value: val('value') }]));
    });
  }

  async function loadGroups() {
    const f = $('#flt').value, q = $('#q').value;
    const d = await api(`/plan/groups?filter=${f}&q=${encodeURIComponent(q)}&limit=${LIMIT}&offset=${offset}`);
    const m = d.summary;
    $('#sum').textContent = `${m.total || 0} products · ${m.ready || 0} ready · ${m.review || 0} need review · ${m.approved || 0} approved · ${m.unclassified || 0} unclassified`;
    $('#groups').innerHTML = d.groups.map((g) => {
      const locked = !!g.new_product_id;
      return `<div class="grp" data-id="${g.id}"><div class="gh"><div><strong>${esc(g.title)}</strong>
        <span class="tag ${g.format ? '' : 'bad'}">${esc(g.format || 'unclassified')}</span>
        <span class="muted">${esc(g.vendor)} · <span class="mono">${esc(g.handle)}</span></span></div>
        <div class="row">${locked ? '<span class="muted">created</span>' : `<button class="ghost" data-act="add">+ Add variant</button>
        ${g.status === 'draft' ? `<button data-act="approve" ${g.nr || !g.category_id ? 'disabled' : ''}>Approve</button>`
          : `<span class="muted">${g.status}</span> <button data-act="unapprove" class="ghost">Undo</button>`}`}</div></div>
        <div class="addbox"></div>
        <table><thead><tr><th>Edition</th><th>Color</th><th>Attributes</th><th>From</th><th>Price</th><th>Qty</th><th></th><th></th></tr></thead><tbody>
        ${g.variants.map((v) => `<tr data-v="${v.id}" class="${v.status === 'needs_review' ? 'warn' : ''}">
          ${['edition', 'color', 'attributes'].map((k) => `<td><input data-k="${k}" value="${esc(v[k])}" ${locked ? 'disabled' : ''}/></td>`).join('')}
          <td>${esc(v.source_title)}</td><td>${v.price != null ? '$' + v.price.toFixed(2) : ''}</td><td>${v.qty ?? ''}</td>
          <td class="muted">${esc(v.reason || '')}</td>
          <td>${locked ? '' : `<button class="ghost" data-act="remove" title="Move to its own product">✕</button>`}</td></tr>`).join('')}</tbody></table></div>`;
    }).join('') || '<p class="muted">Nothing here.</p>';
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
      gEl.querySelector('[data-act=add]')?.addEventListener('click', () => {
        const box = gEl.querySelector('.addbox');
        box.innerHTML = '<input placeholder="Search products in this category…"/><div class="res"></div>';
        const inp = box.querySelector('input'), res = box.querySelector('.res');
        const run = async () => {
          const rows = await api(`/plan/groups/${id}/addable?q=${encodeURIComponent(inp.value)}`);
          res.innerHTML = rows.map((r) => `<div class="hit" data-v="${r.id}">${esc(r.title)} <span class="muted">· ${esc(r.group_handle)}</span></div>`).join('') || '<span class="muted">No matches</span>';
          res.querySelectorAll('.hit').forEach((h) => (h.onclick = async () => {
            try { await post(`/plan/variants/${h.dataset.v}/move`, { group_id: Number(id) }); loadGroups(); } catch (e) { alert(e.message); }
          }));
        };
        inp.oninput = () => { clearTimeout(debounce); debounce = setTimeout(run, 250); };
        inp.focus(); run();
      });
      gEl.querySelectorAll('[data-act=remove]').forEach((btn) => (btn.onclick = async () => {
        const vid = btn.closest('tr').dataset.v;
        const title = prompt('Title for the new product:', gEl.querySelector('strong').textContent);
        if (!title) return;
        try { await post(`/plan/variants/${vid}/move`, { new_title: title }); refresh(); } catch (e) { alert(e.message); }
      }));
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

// ── Apply: step 1 create, step 2 archive (tracked separately) ───────
function renderApply() {
  const page = el(`<div>
    <div id="chips" class="row"></div>
    <div class="row"><label>Chunk <input id="n" type="number" value="25" min="1" max="100" style="width:70px"/></label>
      <label><input id="pub" type="checkbox"/> create as Active (default Draft)</label>
      <button id="create">1 · Create next chunk</button><button id="archive">2 · Archive old for next chunk</button>
      <button id="publish">Publish to Online Store</button>
      <button id="cancel" class="ghost">Cancel</button><a href="/api/plan/mapping.csv" class="muted">Export mapping</a></div>
    <p id="msg"></p><div class="row"><select id="stage"><option value="to_create">To create</option>
      <option value="to_archive">Created · old not archived</option><option value="to_publish">Created · not published</option><option value="partial">Partial / failed</option>
      <option value="done">Done</option><option value="all">All</option></select><input id="q" placeholder="Search…"/></div>
    <div id="groups"></div><div class="pager"><span id="info"></span><button id="prev">←</button><button id="next">→</button></div></div>`);
  const LIMIT = 25; let offset = 0, debounce, wasRunning = false;
  const $ = (sel) => page.querySelector(sel);
  const body = (ids) => ({ group_ids: ids || [], limit: Number($('#n').value) || 25, publish: $('#pub').checked });
  const run = (step, ids) => async () => {
    if (!confirm({ create: 'Create products in Shopify?', archive: 'Archive the old products for these groups?', publish: 'Publish these products to the Online Store?' }[step])) return;
    try { await post(`/apply/${step}`, body(ids)); } catch (e) { alert(e.message); }
    poll();
  };
  async function loadSummary() {
    const m = await api('/apply/summary');
    $('#chips').innerHTML = `<span class="tag">${m.to_create} to create</span><span class="tag">${m.to_archive} created, old not archived</span><span class="tag">${m.to_publish} not on Online Store</span>
      <span class="tag ${m.partial ? 'bad' : ''}">${m.partial} partial</span><span class="tag">${m.done} done</span>`;
  }
  async function loadGroups() {
    const d = await api(`/apply/groups?stage=${$('#stage').value}&q=${encodeURIComponent($('#q').value)}&limit=${LIMIT}&offset=${offset}`);
    $('#groups').innerHTML = d.groups.map((g) => `<div class="grp" data-id="${g.id}"><div class="gh"><div><strong>${esc(g.title)}</strong>
      <span class="tag">${esc(g.format || '')}</span> <span class="mono">${esc(g.handle)}</span></div>
      <div class="row"><span class="tag ${g.created === g.n ? 'ok' : ''}">created ${g.created}/${g.n}</span>
      <span class="tag ${g.archived === g.n ? 'ok' : ''}">old archived ${g.archived}/${g.n}</span>
      <span class="tag ${g.published_at ? 'ok' : ''}">${g.published_at ? 'on Online Store' : 'not published'}</span>
      ${g.created === g.n && !g.published_at ? '<button class="ghost" data-act="publish">Publish</button>' : ''}
      ${!g.new_product_id ? '<button data-act="create">Create</button>' : g.created === g.n && g.archived < g.n ? '<button data-act="archive">Archive old</button>' : g.created < g.n ? '<button data-act="create">Resume</button>' : ''}</div></div>
      ${g.error ? `<div class="err">${esc(g.error)}</div>` : ''}
      <table><thead><tr><th>Variant</th><th>Old product</th><th>Old qty</th><th>Copied</th><th>New</th><th>Old</th></tr></thead><tbody>
      ${g.variants.map((v) => `<tr><td>${esc(v.edition)} | ${esc(v.color)} | ${esc(v.attributes)}</td><td>${esc(v.source_title)}</td>
        <td>${v.cached_qty ?? ''}</td><td>${v.qty_copied ?? ''}</td><td>${v.new_variant_id ? '✓' : ''}</td><td>${v.archived_at ? 'archived' : 'active'}</td></tr>`).join('')}
      </tbody></table></div>`).join('') || '<p class="muted">Nothing here.</p>';
    $('#info').textContent = d.total ? `${offset + 1}–${Math.min(offset + LIMIT, d.total)} of ${d.total}` : '';
    $('#prev').disabled = offset === 0; $('#next').disabled = offset + LIMIT >= d.total;
    page.querySelectorAll('.grp').forEach((gEl) => {
      const id = Number(gEl.dataset.id);
      gEl.querySelector('[data-act=create]')?.addEventListener('click', run('create', [id]));
      gEl.querySelector('[data-act=archive]')?.addEventListener('click', run('archive', [id]));
      gEl.querySelector('[data-act=publish]')?.addEventListener('click', run('publish', [id]));
    });
  }
  async function poll() {
    const s = await api('/apply/status');
    $('#msg').innerHTML = s.running ? `Running ${s.step}: ${s.done}/${s.total} — ${esc(s.current)}`
      : (s.step ? `Last ${s.step}: ${s.done}/${s.total}` : '') + (s.errors.length ? ` · ${s.errors.length} failed:<br>` + s.errors.map((e) => `${esc(e.title)} — ${esc(e.message)}`).join('<br>') : '');
    page.querySelectorAll('#create,#archive,#publish').forEach((b) => (b.disabled = s.running));
    $('#cancel').disabled = !s.running;
    if (wasRunning && !s.running) { loadSummary(); loadGroups(); }
    wasRunning = s.running;
  }
  $('#create').onclick = run('create'); $('#archive').onclick = run('archive'); $('#publish').onclick = run('publish');
  $('#cancel').onclick = () => post('/apply/cancel');
  $('#stage').onchange = () => { offset = 0; loadGroups(); };
  $('#q').oninput = () => { clearTimeout(debounce); debounce = setTimeout(() => { offset = 0; loadGroups(); }, 300); };
  $('#prev').onclick = () => { offset = Math.max(0, offset - LIMIT); loadGroups(); };
  $('#next').onclick = () => { offset += LIMIT; loadGroups(); };
  loadSummary(); loadGroups(); poll(); pollTimer = setInterval(poll, 1500);
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
