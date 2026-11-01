import { API } from '../api.js';
import { Modal } from '../components/modal.js';
import { Toast } from '../components/toast.js';
import { buildPager, debounce, esc, Fmt, truncCell } from '../util.js';

const UPC_LEVEL = 'product'; // 'variant' once UPCs move to variants

export class MatchesPage {
    constructor() { this.page = 1; this.q = ''; this.only = false; this._request = 0; }
    destroy() { }

    async render(c) {
        this.c = c;
        c.innerHTML = `
            <div class="page">
                <div class="page-title">UPC Matches</div>
                <div class="search-row">
                <input class="input" id="m-search" placeholder="Search title or vendor…">
                <label class="check-row" style="margin:0 0 0 12px">
                    <input type="checkbox" id="m-only"><span>Only with suggestions</span></label>
                </div>
                <div id="m-pager-top"></div>
                <div class="table-wrap"><table class="cmp">
                <colgroup><col class="c-title"><col class="c-title"><col class="c-vendor"><col class="c-type">
                    <col class="c-price"><col class="c-upc"><col class="c-act"></colgroup>
                <thead><tr><th>Shopify title</th><th>WebAMI title</th><th>Vendor / Artist</th>
                    <th>Type / Format</th><th>Cost / Price</th><th>UPC / Link</th><th></th></tr></thead>
                <tbody id="m-body"></tbody>
                </table></div>
                <div id="m-pager-bottom"></div>
            </div>`;
        c.querySelector('#m-search').addEventListener('input', debounce(e => {
            this.q = e.target.value.trim(); this.page = 1; this._load();
        }));
        c.querySelector('#m-only').addEventListener('change', e => {
            this.only = e.target.checked; this.page = 1; this._load();
        });
        await this._load();
    }

    async _load() {
        const body = this.c.querySelector('#m-body');
        const req = ++this._request;
        body.innerHTML = `<tr><td colspan="7" class="empty-cell">
      <span class="spinner"></span> ${this.only ? 'Calculating matches… (first load can take a while)' : 'Loading…'}
    </td></tr>`;
        for (const id of ['#m-pager-top', '#m-pager-bottom']) this.c.querySelector(id).style.opacity = '0.4';
        try {
            const params = new URLSearchParams({ page: this.page });
            if (this.q) params.set('q', this.q);
            if (this.only) params.set('only_suggested', 'true');
            const data = await API.get(`/api/matches?${params}`);
            if (req !== this._request || !body.isConnected) return;
            this.items = data.items;
            body.innerHTML = data.items.length ? data.items.map((p, i) => {
                const s = p.suggestions[0];
                const link = s && s.href ? `<a href="https://webami.aent.com${esc(s.href)}" target="_blank" rel="noopener">WebAMI ↗</a>` : '';
                const dash = '<span class="muted">—</span>';
                return `<tr>
                    <td>${esc(p.title)}</td>
                    <td>${s ? esc(s.title) : dash}</td>
                    <td><div class="pair"><span>${esc(p.vendor || '—')}</span>
                        <span class="sub side">${s ? esc(s.artist || '—') : '—'}</span></div></td>
                    <td><div class="pair"><span>${esc(p.type || p.product_type || '—')}</span>
                        <span class="sub side">${s ? esc(s.product_type || '—') : '—'}</span></div></td>
                    <td><div class="pair"><span>${p.cost != null ? Fmt.price(p.cost) : '—'}</span>
                        <span class="sub side">${s && s.price != null ? Fmt.price(s.price) : '—'}</span></div></td>
                    <td><div class="pair"><span class="mono">${esc(s ? s.upc : '—')}</span>
                        <span class="sub">${link}</span></div></td>
                    <td>
                        <button class="btn btn-primary btn-sm" data-m="${i}" ${s ? '' : 'disabled'}>Match</button>
                        <button class="btn btn-ghost btn-sm" data-n="${i}">No match</button>
                    </td></tr>`;
            }).join('') : '<tr><td colspan="7" class="empty-cell">Nothing to review</td></tr>';
            body.querySelectorAll('[data-m]').forEach(b =>
                b.addEventListener('click', () => this._match(this.items[+b.dataset.m])));
            body.querySelectorAll('[data-n]').forEach(b =>
                b.addEventListener('click', () => this._noMatch(this.items[+b.dataset.n])));
            for (const id of ['#m-pager-top', '#m-pager-bottom']) {
                buildPager(this.c.querySelector(id), data, p => { this.page = p; this._load(); });
            }
            for (const id of ['#m-pager-top', '#m-pager-bottom']) this.c.querySelector(id).style.opacity = '';
        } catch (e) {
            for (const id of ['#m-pager-top', '#m-pager-bottom']) this.c.querySelector(id).style.opacity = '';
            if (req === this._request && body.isConnected)
                body.innerHTML = `<tr><td colspan="7" class="empty-cell">${esc(e.message)}</td></tr>`;
        }
    }

    async _save(p, upc, title) {
        const product = {}, variants = [];
        if (UPC_LEVEL === 'product') product.upc = upc;
        else variants.push({ id: p.variant_id, upc });
        if (title && title !== p.title) product.title = title;
        try {
            const res = await API.put(`/api/products/${encodeURIComponent(p.product_id)}`, { product, variants });
            Modal.close();
            res.dry_run ? Toast.warning('Test mode: nothing written') : Toast.success('Saved to Shopify');
            this._load();
        } catch (e) { Toast.error(e.message); }
    }

    _match(p, cands = p.suggestions) {
        const body = document.createElement('div');
        body.innerHTML = `
            <div class="muted">Shopify: ${esc(p.title)} — ${esc(p.vendor || '')}</div>
            <div class="table-wrap" style="margin-top:12px"><table class="variants-table">
                <thead><tr><th></th><th>Source</th><th>Title</th><th>Artist</th><th>Format</th><th class="num">Price</th><th>UPC</th><th>Link</th></tr></thead>
                <tbody>${cands.map((c, i) => `<tr>
                <td><input type="radio" name="cand" value="${i}" ${i === 0 ? 'checked' : ''}></td>
                <td>${esc(c.source)}${c.artist_match ? '' : ' (artist differs)'}</td>
                <td>${truncCell(c.title)}</td><td>${truncCell(c.artist)}</td>
                <td>${esc(c.product_type || '—')}</td><td class="num">${c.price != null ? Fmt.price(c.price) : '—'}</td><td class="mono">${esc(c.upc)}</td><td>${c.href ? `<a href="https://webami.aent.com${esc(c.href)}" target="_blank" rel="noopener">↗</a>` : ''}</td></tr>`).join('')}
                </tbody></table></div>
            <div class="input-group" style="margin-top:12px">
                <label class="check-row" style="margin-top:0"><input type="checkbox" name="upd"><span>Update title</span></label>
                <input class="input" name="title">
            </div>`;
        const t = body.querySelector('[name=title]'), chk = body.querySelector('[name=upd]');
        const pick = () => {
            const c = cands[+body.querySelector('[name=cand]:checked').value];
            t.value = c.suggested_title;
            chk.checked = c.suggested_title !== p.title;  // titles differ or features exist
        };
        body.querySelectorAll('[name=cand]').forEach(r => r.addEventListener('change', pick));
        pick();
        Modal.open({
            title: 'Confirm match', body, width: '96vw',
            buttons: [
                {
                    label: 'Confirm', cls: 'btn-primary', onClick: () => {
                        const c = cands[+body.querySelector('[name=cand]:checked').value];
                        this._save(p, c.upc, chk.checked ? t.value.trim() : null);
                    }
                },
                { label: 'Cancel', onClick: Modal.close },
            ],
        });
    }

    _noMatch(p) {
        const body = document.createElement('div');
        body.innerHTML = `
            <div class="muted">${esc(p.title)} — ${esc(p.vendor || '')}</div>
            <div class="form-grid" style="margin-top:12px">
                <div class="input-group"><label class="input-label">UPC</label>
                <input class="input" name="upc"></div>
                <div class="input-group"><label class="input-label">Title</label>
                <input class="input" name="title" value="${esc(p.title)}"></div>
            </div>`;
        Modal.open({
            title: 'No match', body, width: '700px',
            buttons: [
                {
                    label: 'Save manual', cls: 'btn-primary', onClick: () => {
                        const upc = body.querySelector('[name=upc]').value.trim();
                        if (!upc) return Toast.error('UPC required');
                        this._save(p, upc, body.querySelector('[name=title]').value.trim());
                    }
                },
                {
                    label: 'Search WebAMI', onClick: async () => {
                        try {
                            const { items } = await API.get(
                                `/api/products/${encodeURIComponent(p.product_id)}/webami-suggestions?search=true`);
                            items.length ? this._match(p, items) : Toast.info('No search results');
                        } catch (e) { Toast.error(e.message); }
                    }
                },
                {
                    label: 'Ignore', onClick: async () => {
                        await API.post(`/api/matches/${encodeURIComponent(p.product_id)}/ignore`);
                        Modal.close(); this._load();
                    }
                },
                { label: 'Cancel', onClick: Modal.close },
            ],
        });
    }
}