import { api } from '../api.js';
import { h, fmt, fmtPrice, renderModal, withLoading, showToast, spinner, parseJSON, statusBadge, emptyState, closeModal, makePaginator } from '../utils.js';

export function renderShopify() {
  const wrap = h('div', {});
  wrap.appendChild(h('div', { class: 'page-title' }, 'Shopify Products'));

  const selectedIds = new Set();

  const searchInput   = h('input', { class: 'input', placeholder: 'Search title, vendor, UPC…', style: 'max-width:280px;' });
  const bulkDeleteBtn = h('button', { class: 'btn btn-danger btn-sm',  style: 'display:none;', onClick: doBulkDelete }, 'Delete selected');
  const bulkGapBtn    = h('button', { class: 'btn btn-warning btn-sm', style: 'display:none;', onClick: doBulkGap   }, 'Fill gaps');
  const selCount      = h('span',   { style: 'font-size:12px;color:var(--text-muted);display:none;' }, '');
  const toolbar = h('div', { class: 'row center', style: 'margin-bottom:14px;gap:10px;flex-wrap:wrap;' },
    searchInput, selCount, bulkGapBtn, bulkDeleteBtn,
  );
  wrap.appendChild(toolbar);

  const tableWrap = h('div', { class: 'table-wrap' });
  wrap.appendChild(tableWrap);

  let paginator = null;
  let currentPageRows = []; // 👈 important for "select all (page)"

  function updateBulkControls() {
    const n = selectedIds.size;
    const show = n > 0;
    bulkDeleteBtn.style.display = show ? '' : 'none';
    bulkGapBtn.style.display    = show ? '' : 'none';
    selCount.style.display      = show ? '' : 'none';
    selCount.textContent        = `${n} selected`;
  }

  async function doBulkDelete() {
    if (!selectedIds.size) return;
    if (!confirm(`Delete ${selectedIds.size} product(s) from Shopify? This cannot be undone.`)) return;
    await withLoading(bulkDeleteBtn, async () => {
      try {
        const res = await api.bulkDelete([...selectedIds]);
        showToast(`Deleted ${res.deleted?.length || 0} product(s)`, 'success');
        selectedIds.clear();
        load(searchInput.value);
      } catch(e) { showToast(e.message, 'error'); }
    });
  }

  async function doBulkGap() {
    if (!selectedIds.size) return;
    await withLoading(bulkGapBtn, async () => {
      try {
        const res = await api.fillGaps([...selectedIds]);
        showToast(`Filled gaps for ${res.filled || 0} product(s)`, 'success');
      } catch(e) { showToast(e.message, 'error'); }
    });
  }

  let debounce;
  searchInput.addEventListener('input', () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => load(searchInput.value), 300);
  });

  async function load(q='') {
    tableWrap.innerHTML = '';
    tableWrap.appendChild(h('div', { class: 'empty-state' }, spinner(), h('span',{},'Loading…')));
    try {
      const rows = await api.shopifyProducts(q);
      // ✅ empty state BEFORE paginator
      if (!rows.length) {
        tableWrap.innerHTML = '';
        tableWrap.appendChild(emptyState('🛍️', 'No products found'));
        if (paginator) paginator.bar.style.display = 'none';
        return;
      }

      if (!paginator) {
        paginator = makePaginator(rows, (pageRows) => {
          currentPageRows = pageRows;
          renderTable(pageRows);
        });
        wrap.appendChild(paginator.bar);
      } else {
        paginator.bar.style.display = '';
      }

      paginator.reset(rows);
    } catch(e) {
      tableWrap.innerHTML = `<div class="alert alert-error" style="margin:16px">${e.message}</div>`;
    }
  }

  function renderTable(rows) {
    tableWrap.innerHTML = '';
    const allCb = h('input', { type: 'checkbox', title: 'Select page' });

    // ✅ ONLY selects current page
    allCb.addEventListener('change', () => {
      currentPageRows.forEach(r => {
        if (allCb.checked) selectedIds.add(r.product_id);
        else selectedIds.delete(r.product_id);
      });

      tableWrap.querySelectorAll('tbody input[type=checkbox]')
        .forEach(cb => cb.checked = allCb.checked);
      updateBulkControls();
    });

    const thead = h('thead', {},
      h('tr', {},
        h('th', { style: 'width:36px;' }, allCb),
        h('th', {}, ''),
        h('th', {}, 'Title'),
        h('th', {}, 'Vendor'),
        h('th', {}, 'UPC'),
        h('th', {}, 'Status'),
        h('th', {}, 'Price'),
        h('th', {}, 'Updated'),
        h('th', {}, ''),
      )
    );
    const tbody = h('tbody', {});

    for (const r of rows) {
      const cb = h('input', { type: 'checkbox' });
      cb.checked = selectedIds.has(r.product_id);
      cb.addEventListener('change', () => {
        if (cb.checked) selectedIds.add(r.product_id); else selectedIds.delete(r.product_id);
        updateBulkControls();
      });

      const images = Array.isArray(r.image_urls) ? r.image_urls : parseJSON(r.image_urls);
      const thumb = images && images[0]
        ? h('img', { class: 'product-thumb', src: images[0], alt: '' })
        : h('div', { class: 'product-thumb-placeholder' }, '♪');

      const variants = Array.isArray(r.variants) ? r.variants : (parseJSON(r.variants) || []);
      const price    = variants[0]?.price ? fmtPrice(variants[0].price) : '—';

      const editBtn = h('button', { class: 'btn btn-ghost btn-sm', onClick: () => openEditModal(r) }, 'Edit');
      const delBtn  = h('button', { class: 'btn btn-danger btn-sm', onClick: () => doDelete(r.product_id, r.title) }, 'Del');

      tbody.appendChild(h('tr', {},
        h('td', { class: 'checkbox-cell' }, cb),
        h('td', {}, thumb),
        h('td', { style: 'max-width:220px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:500;' }, r.title || '—'),
        h('td', { style: 'color:var(--text-secondary);' }, r.vendor || '—'),
        h('td', { class: 'mono', style: 'font-size:11px;color:var(--text-muted);' }, r.upc || '—'),
        h('td', {}, statusBadge(r.status)),
        h('td', { style: 'color:var(--green);font-weight:600;' }, price),
        h('td', { style: 'color:var(--text-muted);font-size:12px;' }, fmt(r.updated_at)),
        h('td', { class: 'row center', style: 'gap:6px;' }, editBtn, delBtn),
      ));
    }

    tableWrap.appendChild(h('table', {}, thead, tbody));
  }

  async function doDelete(id, title) {
    if (!confirm(`Delete "${title || id}" from Shopify? This cannot be undone.`)) return;
    try {
      await api.deleteProduct(id);
      showToast('Product deleted', 'success');
      load(searchInput.value);
    } catch(e) { showToast(e.message, 'error'); }
  }

  function openEditModal(product) {
    const variants = Array.isArray(product.variants) ? product.variants : (parseJSON(product.variants) || []);
    const price = variants[0]?.price || '';

    const titleInput  = h('input', { class: 'input', value: product.title || '' });
    const vendorInput = h('input', { class: 'input', value: product.vendor || '' });
    const priceInput  = h('input', { class: 'input', type: 'number', step: '0.01', value: price });
    const statusSel   = h('select', { class: 'select' });
    ['ACTIVE','DRAFT','ARCHIVED'].forEach(s => {
      const opt = document.createElement('option');
      opt.value = s; opt.textContent = s;
      if (s === product.status) opt.selected = true;
      statusSel.appendChild(opt);
    });

    const saveBtn   = h('button', { class: 'btn btn-primary', onClick: doSave }, 'Save');
    const cancelBtn = h('button', { class: 'btn btn-ghost',   onClick: closeModal }, 'Cancel');

    async function doSave() {
      await withLoading(saveBtn, async () => {
        try {
          const updatedVariants = variants.map((v, i) => i === 0 ? { ...v, price: priceInput.value } : v);
          await api.updateProduct(product.product_id, {
            title:    titleInput.value,
            vendor:   vendorInput.value,
            status:   statusSel.value,
            variants: updatedVariants,
          });
          showToast('Product updated', 'success');
          closeModal();
          load(searchInput.value);
        } catch(e) { showToast(e.message, 'error'); }
      });
    }

    document.body.appendChild(renderModal('Edit Product',
      h('div', { class: 'col', style: 'gap:14px;' },
        h('div', { class: 'input-group' }, h('div', { class: 'input-label' }, 'Title'),  titleInput),
        h('div', { class: 'input-group' }, h('div', { class: 'input-label' }, 'Vendor'), vendorInput),
        h('div', { class: 'input-group' }, h('div', { class: 'input-label' }, 'Price'),  priceInput),
        h('div', { class: 'input-group' }, h('div', { class: 'input-label' }, 'Status'), statusSel),
      ),
      h('div', { class: 'row', style: 'gap:10px;justify-content:flex-end;margin-top:20px;' }, cancelBtn, saveBtn),
    ));
  }

  load();
  return wrap;
}