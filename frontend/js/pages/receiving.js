class ReceivingPage {
  constructor() {
    this.orderId    = null;
    this.orderData  = null;
    this.quantities = {};  // order_item_id → qty entered
  }

  async render(container) {
    // Check if we were deep-linked to a specific order
    const hash = location.hash;
    const match = hash.match(/order=(\d+)/);
    if (match) this.orderId = parseInt(match[1]);

    container.innerHTML = `
      <div class="page">
        <div class="page-title">Receiving</div>

        <div class="row" style="margin-bottom:20px;align-items:center;gap:12px">
          <div class="input-group" style="margin-bottom:0;flex:1;max-width:400px">
            <label class="input-label">Select Order</label>
            <select id="order-select" class="select" style="width:100%">
              <option value="">— Choose an order —</option>
            </select>
          </div>
          <div id="order-status-badge" style="margin-top:20px"></div>
        </div>

        <div id="receiving-content">
          <div class="empty-state">
            <div class="empty-state-icon">📦</div>
            <div class="empty-state-text">Select an order to start receiving</div>
          </div>
        </div>
      </div>`;

    await this._loadOrderList();

    const select = document.getElementById('order-select');
    select.addEventListener('change', () => {
      this.orderId    = parseInt(select.value) || null;
      this.quantities = {};
      this._loadOrder();
    });

    if (this.orderId) {
      select.value = this.orderId;
      await this._loadOrder();
    }
  }

  async _loadOrderList() {
    try {
      const data = await API.get('/api/orders?per_page=100');
      const select = document.getElementById('order-select');
      const statusIcon = { pending: '🕐', partial: '📦', complete: '✅' };
      data.items?.forEach(o => {
        const opt = document.createElement('option');
        opt.value = o.id;
        opt.textContent = `${statusIcon[o.status] || ''} ${o.order_number || o.webami_order_id || `Order #${o.id}`}  (${Fmt.date(o.order_date)})`;
        select.appendChild(opt);
      });
      if (this.orderId) select.value = this.orderId;
    } catch (e) {
      Toast.error('Failed to load orders: ' + e.message);
    }
  }

  async _loadOrder() {
    const content = document.getElementById('receiving-content');
    if (!this.orderId) {
      content.innerHTML = '';
      return;
    }
    content.innerHTML = '<div style="color:var(--text-muted);font-size:13px;padding:16px 0">Loading order…</div>';
    try {
      this.orderData = await API.get(`/api/orders/${this.orderId}`);
      this._renderOrder();
    } catch (e) {
      content.innerHTML = `<div class="alert alert-error">${esc(e.message)}</div>`;
    }
  }

  _renderOrder() {
    const o = this.orderData;
    const content = document.getElementById('receiving-content');

    const badge = document.getElementById('order-status-badge');
    const badgeCls = { complete: 'badge-new', partial: 'badge-used', pending: 'badge-draft' };
    if (badge) badge.innerHTML = `<span class="badge ${badgeCls[o.status] || 'badge-draft'}">${esc(o.status)}</span>`;

    const items = o.items || [];
    const unreceived = items.filter(i => (i.quantity_ordered || 0) > (i.total_received || 0));
    const allDone    = unreceived.length === 0;

    content.innerHTML = `
      <div class="row center" style="margin-bottom:16px">
        <div style="font-size:13px;color:var(--text-secondary)">
          ${items.length} items · ${unreceived.length} still pending
        </div>
        <div style="flex:1"></div>
        ${!allDone ? `
          <button class="btn btn-ghost btn-sm" id="fill-remaining-btn">Fill Remaining</button>
          <button class="btn btn-ghost btn-sm" id="clear-all-btn">Clear All</button>
          <button class="btn btn-primary" id="review-receive-btn">Review & Push</button>
        ` : '<span style="color:var(--green);font-size:13px;font-weight:600">✓ All received</span>'}
      </div>

      <div class="table-wrap">
        <table>
          <colgroup>
            <col style="width:48px"><col style="width:220px"><col style="width:120px">
            <col style="width:90px"><col style="width:90px"><col style="width:90px">
            <col style="width:100px"><col style="width:90px"><col style="width:80px">
          </colgroup>
          <thead><tr>
            <th></th><th>Title</th><th>Vendor</th>
            <th>UPC</th><th>Ordered</th><th>Received</th>
            <th>Enter Qty</th><th>Shopify</th><th>Status</th>
          </tr></thead>
          <tbody id="receive-body"></tbody>
        </table>
      </div>`;

    this._renderRows(items);

    window._undoReceived = async (id) => {
      try {
        await API.delete(`/api/orders/received/${id}`);
        Toast.info('Receipt removed');
        await this._loadOrder();
      } catch (e) { Toast.error(e.message); }
    };

    if (!allDone) {
      document.getElementById('fill-remaining-btn').addEventListener('click', () => {
        items.forEach(item => {
          const remaining = (item.quantity_ordered || 0) - (item.total_received || 0);
          if (remaining > 0) {
            this.quantities[item.id] = remaining;
            const input = document.getElementById(`qty-${item.id}`);
            if (input) input.value = remaining;
          }
        });
      });

      document.getElementById('clear-all-btn').addEventListener('click', () => {
        this.quantities = {};
        items.forEach(item => {
          const input = document.getElementById(`qty-${item.id}`);
          if (input) input.value = '';
        });
      });

      document.getElementById('review-receive-btn').addEventListener('click', () => this._openReview(items));
    }
  }

  _renderRows(items) {
    const body = document.getElementById('receive-body');
    if (!body) return;

    body.innerHTML = items.map(item => {
      const ordered   = item.quantity_ordered  || 0;
      const received  = item.total_received    || 0;
      const remaining = Math.max(0, ordered - received);
      const isComplete = remaining === 0;

      const shopifyStatus = item.variant_id
        ? `<span style="font-size:11px;color:var(--green)">Mapped</span>`
        : `<span style="font-size:11px;color:var(--text-muted)">No match</span>`;

      const rowStyle = isComplete ? 'opacity:0.5' : '';
      const imgSrc   = item.sp_image || item.wp_image || '';

      return `
        <tr style="${rowStyle}">
          <td class="col-thumb">
            ${imgSrc
              ? `<img class="product-thumb" src="${esc(imgSrc)}" onerror="this.style.display='none'">`
              : '<div class="product-thumb-placeholder">♫</div>'}
          </td>
          <td class="col-title cell-truncate" title="${esc(item.title || item.wp_title || '')}">
            ${esc(item.title || item.wp_title || '—')}
            ${item.sp_title && item.sp_title !== item.title
              ? `<div style="font-size:11px;color:var(--text-muted)">${esc(item.sp_title)}</div>` : ''}
          </td>
          <td class="cell-truncate" style="font-size:12px">${esc(item.vendor || '—')}</td>
          <td><span class="mono" style="font-size:11px">${esc(item.webami_upc || '—')}</span></td>
          <td style="text-align:center">${ordered}</td>
          <td style="text-align:center">
            ${received}
            ${(item.received_records || []).map(r => `
              <div style="font-size:10px;display:flex;align-items:center;justify-content:center;gap:4px">
                <span style="color:var(--green)">+${r.quantity_received}</span>
                <button onclick="event.stopPropagation();window._undoReceived(${r.id})"
                  style="background:none;border:none;color:var(--text-muted);cursor:pointer;font-size:11px;padding:0"
                  title="Undo">✕</button>
              </div>`).join('')}
          </td>
          <td style="text-align:center">
            ${isComplete
              ? '<span style="font-size:11px;color:var(--green)">Complete</span>'
              : `<input class="qty-input" id="qty-${item.id}" type="number" min="0" max="${remaining}"
                   value="${this.quantities[item.id] ?? ''}" placeholder="0"
                   data-item-id="${item.id}" data-max="${remaining}">`}
          </td>
          <td style="text-align:center">${shopifyStatus}</td>
          <td>
            ${isComplete
              ? '<span class="badge badge-new">Done</span>'
              : `<span class="badge badge-draft">${remaining} left</span>`}
          </td>
        </tr>`;
    }).join('');

    body.querySelectorAll('.qty-input').forEach(input => {
      input.addEventListener('change', () => {
        const id  = parseInt(input.dataset.itemId);
        const max = parseInt(input.dataset.max);
        const val = Math.max(0, Math.min(parseInt(input.value) || 0, max));
        input.value = val || '';
        this.quantities[id] = val;
      });
    });
  }

  _openReview(items) {
    const entries = Object.entries(this.quantities).filter(([, qty]) => qty > 0);
    if (!entries.length) { Toast.warning('Enter at least one quantity to receive'); return; }

    const itemMap = {};
    items.forEach(i => { itemMap[i.id] = i; });

    const bodyEl = document.createElement('div');
    bodyEl.innerHTML = `
      <div class="table-wrap" style="max-height:400px;overflow-y:auto">
        <table>
          <thead><tr><th style="text-align:left">Title</th><th>Qty to Receive</th><th>Push to Shopify</th></tr></thead>
          <tbody>
            ${entries.map(([id, qty]) => {
              const item = itemMap[id];
              return `
                <tr>
                  <td class="cell-truncate" style="text-align:left">${esc(item?.title || item?.wp_title || '—')}</td>
                  <td style="text-align:center">
                    <input class="qty-input review-qty" data-id="${id}" type="number" min="0"
                      max="${(item?.quantity_ordered||0) - (item?.total_received||0)}" value="${qty}">
                  </td>
                  <td style="text-align:center">
                    <input type="checkbox" class="review-push" data-id="${id}" ${item?.variant_id ? 'checked' : 'disabled'}>
                  </td>
                </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>`;

    Modal.open({
      title: 'Review Before Pushing',
      body: bodyEl,
      buttons: [
        { label: 'Cancel', cls: 'btn-ghost', onClick: Modal.close },
        { label: 'Confirm & Push', cls: 'btn-primary', onClick: () => this._submitReview() },
      ],
    });

    bodyEl.querySelectorAll('.review-qty').forEach(input => {
      input.addEventListener('change', () => {
        const max = parseInt(input.max) || 0;
        const val = Math.max(0, Math.min(parseInt(input.value) || 0, max));
        input.value = val;
        this.quantities[input.dataset.id] = val;
      });
    });
  }

  async _submitReview() {
    const pushFlags = {};
    document.querySelectorAll('.review-push').forEach(cb => {
      pushFlags[cb.dataset.id] = cb.checked;
    });

    const entries = Object.entries(this.quantities)
      .filter(([, qty]) => qty > 0)
      .map(([id, qty]) => ({
        order_item_id:    parseInt(id),
        quantity_received: qty,
        push_to_shopify:  pushFlags[id] ?? true,
      }));

    if (!entries.length) { Toast.warning('Enter at least one quantity to receive'); return; }

    Modal.close();

    try {
      const result = await API.post(`/api/orders/${this.orderId}/receive`, { items: entries });
      const pushed = result.results?.filter(r => r.shopify_updated).length || 0;
      const saved  = result.results?.filter(r => !r.error).length || 0;
      const errors = result.results?.filter(r => r.error) || [];

      if (errors.length) errors.forEach(e => Toast.error(`Item ${e.item_id}: ${e.error}`));

      if (result.dry_run) {
        Toast.warning(`Dry run — would receive ${result.results.length} items (nothing saved)`);
      } else {
        Toast.success(`Received ${saved} items — ${pushed} pushed to Shopify`);
      }
      this.quantities = {};
      await this._loadOrder();
    } catch (e) {
      Toast.error(e.message);
    }
  }

  async _submit() {
    const entries = Object.entries(this.quantities)
      .filter(([, qty]) => qty > 0)
      .map(([id, qty]) => ({
        order_item_id:    parseInt(id),
        quantity_received: qty,
        push_to_shopify:  true,
      }));

    if (!entries.length) {
      Toast.warning('Enter at least one quantity to receive');
      return;
    }

    const btn = document.getElementById('submit-receive-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Pushing…';

    try {
      const result = await API.post(`/api/orders/${this.orderId}/receive`, { items: entries });
      const pushed = result.results?.filter(r => r.shopify_updated).length || 0;
      const saved  = result.results?.filter(r => !r.error).length || 0;
      const errors = result.results?.filter(r => r.error) || [];

      if (errors.length) {
        errors.forEach(e => Toast.error(`Item ${e.item_id}: ${e.error}`));
      }

      if (result.dry_run) {
        Toast.warning(`Dry run — would receive ${result.results.length} items (nothing saved)`);
      } else {
        Toast.success(`Received ${saved} items — ${pushed} pushed to Shopify`);
      }
      this.quantities = {};
      await this._loadOrder();
    } catch (e) {
      Toast.error(e.message);
      btn.disabled = false;
      btn.textContent = 'Push to Shopify';
    }
  }
}
