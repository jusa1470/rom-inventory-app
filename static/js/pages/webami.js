import { api } from '../api.js';
import { h, fmt, fmtPrice, badge, spinner, parseJSON, emptyState, makePaginator } from '../utils.js';

export function renderWebami() {
  const wrap = h('div', {});
  wrap.appendChild(h('div', { class: 'page-title' }, 'Webami'));

  const contentArea = h('div', {});
  wrap.appendChild(contentArea);

  const searchInput = h('input', { class: 'input', placeholder: 'Search title, artist, brand, UPC…', style: 'max-width:320px;' });
  const tableWrap   = h('div', { class: 'table-wrap' });
  const toolbar     = h('div', { class: 'row center', style: 'margin-bottom:14px;gap:10px;' }, searchInput);
  contentArea.appendChild(toolbar);
  contentArea.appendChild(tableWrap);

  let paginator = null;
  let debounce;
  searchInput.addEventListener('input', () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => load(searchInput.value), 300);
  });

  async function load(q='') {
    tableWrap.innerHTML = '';
    tableWrap.appendChild(h('div', { class: 'empty-state' }, spinner(), h('span',{},'Loading…')));
    try {
      const rows = await api.webamiProducts(q);

      // ✅ Empty state handled here (NOT in table renderer)
      if (!rows.length) {
        tableWrap.innerHTML = '';
        tableWrap.appendChild(emptyState('🎵', 'No products found'));
        if (paginator) paginator.bar.style.display = 'none';
        return;
      }

      // ✅ Initialize paginator once
      if (!paginator) {
        paginator = makePaginator(rows, (pageRows) => {
          renderWebamiProductTable(tableWrap, pageRows);
        });
        contentArea.appendChild(paginator.bar);
      } else {
        paginator.bar.style.display = '';
      }

      paginator.reset(rows);

    } catch(e) {
      tableWrap.innerHTML = `<div class="alert alert-error" style="margin:16px">${e.message}</div>`;
    }
  }

  function renderWebamiProductTable(container, rows) {
    container.innerHTML = '';
    if (!rows.length) { container.appendChild(emptyState('🎵', 'No products found')); return; }
    const thead = h('thead', {},
      h('tr', {},
        h('th', {}, ''),
        h('th', {}, 'UPC'),
        h('th', {}, 'Title'),
        h('th', {}, 'Artist/Brand'),
        h('th', {}, 'Format'),
        h('th', {}, 'Cost'),
        h('th', {}, 'Last Scraped'),
      )
    );
    const tbody = h('tbody', {});
    for (const r of rows) {
      const images = Array.isArray(r.image_urls) ? r.image_urls : parseJSON(r.image_urls);
      const thumb = images && images[0]
        ? h('img', { class: 'product-thumb', src: images[0], alt: '' })
        : h('div', { class: 'product-thumb-placeholder' }, '♪');
      tbody.appendChild(h('tr', {},
        h('td', {}, thumb),
        h('td', { class: 'mono', style: 'font-size:12px;color:var(--text-secondary)' }, r.upc || '—'),
        h('td', {}, r.title || h('span', { style: 'color:var(--text-muted)' }, '—')),
        h('td', {}, r.artist || r.brand || h('span', { style: 'color:var(--text-muted)' }, '—')),
        h('td', {}, r.format ? badge(r.format, 'badge-new') : '—'),
        h('td', { style: 'color:var(--green);font-weight:600;' }, fmtPrice(r.cost)),
        h('td', { style: 'color:var(--text-muted);font-size:12px;' }, fmt(r.last_scraped)),
      ));
    }
    container.appendChild(h('table', {}, thead, tbody));
  }

  load();
  return wrap;
}