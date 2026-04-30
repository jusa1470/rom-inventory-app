import { api } from '../api.js';
import { h, fmt, fmtPrice, badge, spinner, makePaginator, emptyState, closeModal, withLoading, showToast, renderModal } from '../utils.js';

export function renderTrackOrders() {
  const wrap = h('div', {});
  wrap.appendChild(h('div', { class: 'page-title' }, 'Track Orders'));

  const searchInput = h('input', {
    class: 'input',
    placeholder: 'Search order number or name…',
    style: 'max-width:320px;',
  });

  const contentArea = h('div', {});
  wrap.appendChild(h('div', { class: 'row center', style: 'margin-bottom:14px;gap:10px;' }, searchInput));
  wrap.appendChild(contentArea);

  let paginator = null;
  let debounce;
  searchInput.addEventListener('input', () => {
    clearTimeout(debounce);
    debounce = setTimeout(() => loadOrders(searchInput.value), 300);
  });

  async function loadOrders(q = '') {
    contentArea.innerHTML = '';
    contentArea.appendChild(h('div', { class: 'empty-state' }, spinner(), h('span', {}, 'Loading…')));
    try {
      const orders = await api.webamiOrders(q);
      renderOrderList(orders);
    } catch(e) {
      contentArea.innerHTML = `<div class="alert alert-error">${e.message}</div>`;
    }
  }

  function renderOrderList(orders) {
    contentArea.innerHTML = '';
    if (!orders.length) { contentArea.appendChild(emptyState('📦', 'No orders found')); return; }

    const tableWrap = h('div', { class: 'table-wrap' });
    const thead = h('thead', {},
      h('tr', {},
        h('th', {}, 'Order #'),
        h('th', {}, 'Name'),
        h('th', {}, 'Date'),
        h('th', {}, 'Items'),
        h('th', {}, 'Status'),
        h('th', {}, ''),
      )
    );
    const tbody = h('tbody', {});

    function renderRows(rows) {
      tbody.innerHTML = '';

      for (const order of rows) {
        const isFulfilled = order.fulfilled;

        const viewBtn = h('button', { class: 'btn btn-ghost btn-sm', onClick: () => openOrderDetail(order) }, 'View');

        tbody.appendChild(h('tr', {},
          h('td', { style: 'font-weight:600;' }, order.order_number || '—'),
          h('td', {}, order.order_name || '—'),
          h('td', { style: 'color:var(--text-muted);font-size:12px;' }, fmt(order.order_date)),
          h('td', {}, h('span', { class: 'badge badge-new' }, `${order.number_of_products} items`)),
          h('td', {}, isFulfilled
            ? badge('Fulfilled', 'badge-active')
            : badge('Pending', 'badge-draft')
          ),
          h('td', {}, viewBtn),
        ));
      }
    }

    paginator = makePaginator(orders, renderRows);
    tableWrap.appendChild(h('table', {}, thead, tbody));
    tableWrap.appendChild(paginator.bar);
    contentArea.appendChild(tableWrap);
    paginator.render();
  }

  function openOrderDetail(order) {
    // State for this order's received quantities — keyed by item id
    const receivedQtys = {};

    const modalBody = h('div', { class: 'col', style: 'gap:0;' });
    const syncBtn = h('button', { class: 'btn btn-success', style: 'min-width:140px;', onClick: doSyncToShopify }, '🛍 Sync to Shopify');
    const cancelBtn = h('button', { class: 'btn btn-ghost', onClick: closeModal }, 'Close');

    // Load items
    const loadingEl = h('div', { class: 'empty-state' }, spinner(), h('span', {}, 'Loading items…'));
    modalBody.appendChild(loadingEl);

    api.webamiOrderItems(order.guid).then(items => {
      modalBody.innerHTML = '';

      if (!items.length) {
        modalBody.appendChild(emptyState('📦', 'No items on this order'));
        return;
      }

      // Initialize received qtys from existing data
      for (const item of items) {
        receivedQtys[item.id] = item.quantity_received;
      }

      // Items table
      const thead = h('thead', {},
        h('tr', {},
          h('th', {}, 'Title'),
          h('th', {}, 'UPC'),
          h('th', {}, 'Format'),
          h('th', {}, 'Cost'),
          h('th', { style: 'text-align:center;' }, 'Ordered'),
          h('th', { style: 'text-align:center;min-width:140px;' }, 'Received'),
          h('th', { style: 'text-align:center;' }, 'Status'),
        )
      );
      const tbody = h('tbody', {});

      for (const item of items) {
        const statusCell = h('td', { style: 'text-align:center;' });

        function renderStatus() {
          const qty = receivedQtys[item.id] || 0;
          statusCell.innerHTML = '';
          if (qty === 0) {
            statusCell.appendChild(badge('None', 'badge-draft'));
          } else if (qty < item.quantity_ordered) {
            statusCell.appendChild(badge('Partial', 'badge-used'));
          } else {
            statusCell.appendChild(badge('Complete', 'badge-active'));
          }
        }

        // Quantity stepper
        const qtyDisplay = h('span', {
          style: 'display:inline-block;min-width:28px;text-align:center;font-weight:600;font-size:14px;',
        }, String(receivedQtys[item.id] || 0));

        const minusBtn = h('button', {
          class: 'btn btn-ghost btn-sm',
          style: 'padding:0 8px;',
          onClick: async () => {
            const current = receivedQtys[item.id] || 0;
            if (current <= 0) return;
            receivedQtys[item.id] = current - 1;
            qtyDisplay.textContent = String(receivedQtys[item.id]);
            renderStatus();
            await api.markItemReceived(order.guid, item.id, receivedQtys[item.id]);
          },
        }, '−');

        const plusBtn = h('button', {
          class: 'btn btn-ghost btn-sm',
          style: 'padding:0 8px;',
          onClick: async () => {
            const current = receivedQtys[item.id] || 0;
            if (current >= item.quantity_ordered) return;
            receivedQtys[item.id] = current + 1;
            qtyDisplay.textContent = String(receivedQtys[item.id]);
            renderStatus();
            await api.markItemReceived(order.guid, item.id, receivedQtys[item.id]);
          },
        }, '+');

        const stepperCell = h('td', { style: 'text-align:center;' },
          h('div', { style: 'display:flex;align-items:center;justify-content:center;gap:4px;' },
            minusBtn, qtyDisplay, plusBtn,
          )
        );

        renderStatus();

        tbody.appendChild(h('tr', {},
          h('td', { style: 'font-weight:500;max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;' }, item.title || '—'),
          h('td', { class: 'mono', style: 'font-size:11px;color:var(--text-muted);' }, item.upc),
          h('td', {}, item.format ? badge(item.format, 'badge-new') : '—'),
          h('td', { style: 'color:var(--green);font-weight:600;' }, fmtPrice(item.cost)),
          h('td', { style: 'text-align:center;' }, String(item.quantity_ordered)),
          stepperCell,
          statusCell,
        ));
      }

      modalBody.appendChild(h('div', { class: 'table-wrap', style: 'margin-bottom:0;' },
        h('table', {}, thead, tbody)
      ));
    }).catch(e => {
      modalBody.innerHTML = `<div class="alert alert-error">${e.message}</div>`;
    });

    async function doSyncToShopify() {
      await withLoading(syncBtn, async () => {
        try {
          // Collect items that have been fully or partially received
          const receivedItems = Object.entries(receivedQtys)
            .filter(([, qty]) => qty > 0)
            .map(([id, qty]) => ({ id: parseInt(id), quantity_received: qty }));

          if (!receivedItems.length) {
            showToast('No items marked as received', 'warning');
            return;
          }

          // Update inventory quantity in Shopify for each received item
          // Find matching Shopify products by UPC and update inventory
          const items = await api.webamiOrderItems(order.guid);
          let pushed = 0;

          for (const item of items) {
            const qty = receivedQtys[item.id] || 0;
            if (qty === 0) continue;

            const shopifyResults = await api.shopifyProducts(item.upc);
            if (!shopifyResults.length) continue;

            const sp = shopifyResults[0];
            await api.updateProduct(sp.product_id, {
              variants: [{ inventoryQuantity: qty }],
            });
            pushed++;
          }

          showToast(`Synced ${pushed} product(s) to Shopify`, 'success');
          closeModal();
        } catch(e) {
          showToast(`Sync failed: ${e.message}`, 'error');
        }
      });
    }

    const modal = renderModal(
      `Order ${order.order_number || order.guid}`,
      h('div', { style: 'color:var(--text-muted);font-size:12px;margin-top:-12px;margin-bottom:16px;' },
        `${order.order_name || ''}${order.order_name && order.order_date ? ' · ' : ''}${order.order_date ? fmt(order.order_date) : ''}`
      ),
      modalBody,
      h('div', { class: 'row', style: 'gap:10px;justify-content:flex-end;margin-top:20px;' }, cancelBtn, syncBtn),
    );

    // Make modal wider for the table
    modal.querySelector('div[style*="width:480px"]').style.width = '780px';
    document.body.appendChild(modal);
  }

  loadOrders();
  return wrap;
}