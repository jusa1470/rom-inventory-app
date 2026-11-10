import { API } from "../api.js";
import { buildPager, debounce, esc, truncCell } from "../util.js";

const FIELDS = {
  products: [["vendor", "Vendor"], ["product_type", "Product type"], ["type", "MF type"],
    ["genres", "MF genres"], ["category", "Category"]],
  variants: [["image", "Image"], ["price", "Price"], ["cost", "Cost"],
    ["weight", "Weight"], ["release_date", "Release date"], ["upc", "UPC"]],
};

export class MissingPage {
  constructor() {
    this.kind = "products";
    this.page = 1;
    this.q = "";
    this.fields = new Set();
    this._request = 0;
  }
  destroy() {}

  async render(c) {
    this.c = c;
    c.innerHTML = `
      <div class="page">
        <div class="page-title">Missing Data</div>
        <div class="search-row">
          <button class="btn btn-sm" data-k="products">Products</button>
          <button class="btn btn-sm" data-k="variants">Variants</button>
          <input class="input" id="x-search" placeholder="Search title or vendor…" style="margin-left:12px">
        </div>
        <div class="search-row" id="x-fields" style="flex-wrap:wrap"></div>
        <div id="x-pager-top"></div>
        <div class="table-wrap"><table>
          <thead><tr><th>Title</th><th>Vendor</th><th>Missing</th></tr></thead>
          <tbody id="x-body"></tbody></table></div>
        <div id="x-pager-bottom"></div>
      </div>`;
    c.querySelectorAll("[data-k]").forEach((b) =>
      b.addEventListener("click", () => {
        this.kind = b.dataset.k;
        this.fields.clear();
        this.page = 1;
        this._tabs();
        this._load();
      }));
    c.querySelector("#x-search").addEventListener("input", debounce((e) => {
      this.q = e.target.value.trim();
      this.page = 1;
      this._load();
    }));
    this._tabs();
    await this._load();
  }

  _tabs() {
    this.c.querySelectorAll("[data-k]").forEach((b) => {
      b.className = `btn btn-sm ${b.dataset.k === this.kind ? "btn-primary" : "btn-ghost"}`;
    });
    const box = this.c.querySelector("#x-fields");
    box.innerHTML = FIELDS[this.kind].map(([k, l]) =>
      `<label class="check-row" style="margin:0 12px 0 0"><input type="checkbox" data-f="${k}"><span>${l}</span></label>`).join("");
    box.querySelectorAll("[data-f]").forEach((cb) =>
      cb.addEventListener("change", () => {
        cb.checked ? this.fields.add(cb.dataset.f) : this.fields.delete(cb.dataset.f);
        this.page = 1;
        this._load();
      }));
  }

  async _load() {
    const body = this.c.querySelector("#x-body");
    const req = ++this._request;
    try {
      const p = new URLSearchParams({ kind: this.kind, page: this.page });
      if (this.q) p.set("q", this.q);
      this.fields.forEach((f) => p.append("fields", f));
      const data = await API.get(`/api/missing?${p}`);
      if (req !== this._request || !body.isConnected) return;
      body.innerHTML = data.items.length
        ? data.items.map((r) => `<tr>
            <td><div class="pair"><span>${esc(r.title)}</span>
              <span class="sub">${esc(r.variant_title || "")}</span></div></td>
            <td>${truncCell(r.vendor)}</td>
            <td>${r.missing.map((m) => `<span class="badge badge-error" style="margin-right:4px">${esc(m)}</span>`).join("")}</td>
          </tr>`).join("")
        : '<tr><td colspan="3" class="empty-cell">Nothing missing</td></tr>';
      for (const id of ["#x-pager-top", "#x-pager-bottom"])
        buildPager(this.c.querySelector(id), data, (pg) => { this.page = pg; this._load(); });
    } catch (e) {
      if (req === this._request && body.isConnected)
        body.innerHTML = `<tr><td colspan="3" class="empty-cell">${esc(e.message)}</td></tr>`;
    }
  }
}