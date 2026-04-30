const BASE = '/api';

export const api = {
  async _req(method, path, body, signal) {
    const isSyncCall = path.startsWith('/sync/') && method === 'POST';
    const controller = new AbortController();
    let timer;
    if (!isSyncCall && !signal) {
      timer = setTimeout(() => controller.abort(), 15_000);
      signal = controller.signal;
    }
    const opts = { method, headers: { 'Content-Type': 'application/json' } };
    if (body !== undefined) opts.body = JSON.stringify(body);
    if (signal) opts.signal = signal;
    try {
      const res = await fetch(BASE + path, opts);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw Object.assign(new Error(err.detail || 'Request failed'), { status: res.status });
      }
      return res.json();
    } catch(e) {
      if (e.name === 'AbortError' && !signal?.aborted) {
        throw Object.assign(new Error('Request timed out'), { status: 408 });
      }
      throw e;
    } finally {
      clearTimeout(timer);
    }
  },

  get:    (p)    => api._req('GET',    p),
  post:   (p, b) => api._req('POST',   p, b),
  put:    (p, b) => api._req('PUT',    p, b),
  delete: (p, b) => api._req('DELETE', p, b),

  // ── Auth ───────────────────────────────────────────────────────────────────
  verify: (pw) => api.post('/auth/verify', { password: pw }),

  // ── Sync status ────────────────────────────────────────────────────────────
  syncStatus:  () => api.get('/sync/status'),
  syncRunning: () => api.get('/sync/running'),
  ackResult:   () => api.post('/sync/ack-result'),
  cancelSync:  () => api.post('/sync/cancel'),

  // ── Webami ─────────────────────────────────────────────────────────────────
  webamiOrders:   (q='') => api.get(`/webami/orders?q=${encodeURIComponent(q)}`),
  webamiProducts: (q='') => api.get(`/webami/products?q=${encodeURIComponent(q)}`),
  webamiOrderItems: (guid) => api.get(`/webami/orders/${encodeURIComponent(guid)}/items`),
  markItemReceived: (guid, itemId, qty) => api._req('PATCH', `/webami/orders/${encodeURIComponent(guid)}/items/${itemId}`, { quantity_received: qty }),

  syncWebamiOrdersFull:   (sig) => api._req('POST', '/sync/webami/orders/full',   undefined, sig),
  syncWebamiOrdersRecent: (sig) => api._req('POST', '/sync/webami/orders/recent', undefined, sig),
  syncWebamiProductsFull: (sig) => api._req('POST', '/sync/webami/products/full', undefined, sig),
  syncWebamiPrices: (upcs, sig) => api._req('POST', '/sync/webami/prices', { upcs: upcs || null }, sig),

  // ── Shopify ────────────────────────────────────────────────────────────────
  shopifyProducts: (q='') => api.get(`/shopify/products?q=${encodeURIComponent(q)}`),

  syncShopifyFull:   (sig) => api._req('POST', '/sync/shopify/full',   undefined, sig),
  syncShopifyRecent: (sig) => api._req('POST', '/sync/shopify/recent', undefined, sig),

  bridgePrices: (upcs, sig) => api._req('POST', '/sync/prices',   { upcs: upcs || null }, sig),
  fillGaps:     (ids,  sig) => api._req('POST', '/sync/gap-fill', { product_ids: ids || null }, sig),

  createProducts: (products) => api.post('/shopify/products', { products }),
  updateProduct:  (id, data) => api.put(`/shopify/products/${encodeURIComponent(id)}`, data),
  deleteProduct:  (id)       => api.delete(`/shopify/products/${encodeURIComponent(id)}`),
  bulkDelete:     (ids)      => api.delete('/shopify/products/bulk', { product_ids: ids }),
};