import { API } from "../api.js";
import { Modal } from "../components/modal.js";
import { createMultiSelect } from "../components/multiselect.js";
import { Toast } from "../components/toast.js";
import {
  Fmt,
  buildPager,
  debounce,
  esc,
  statusBadge,
  thumb,
  truncCell,
  variantTitle,
} from "../util.js";

const UPC_LEVEL = "product"; // switch to 'variant' once UPCs move to variants

// key = filter name (and filter-options key); sort = backend sort key
const COLUMNS = [
  { label: "", width: 58 },
  { label: "Title", width: 320, key: "title", sort: "title", filter: "text" },
  {
    label: "Vendor",
    width: 160,
    key: "vendor",
    sort: "vendor",
    filter: "text",
  },
  {
    label: "Status",
    width: 120,
    key: "status",
    sort: "status",
    filter: "select",
  },
  {
    label: "Category",
    width: 200,
    key: "category",
    sort: "category",
    filter: "select",
  },
  { label: "Type", width: 140, key: "type", sort: "type", filter: "select" },
  {
    label: "Genres",
    width: 180,
    key: "genres",
    sort: "genres",
    filter: "select",
  },
  { label: "Tags", width: 180, key: "tags", sort: "tags", filter: "select" },
  { label: "Variants", width: 90, sort: "variants", num: true },
  { label: "Price", width: 140, sort: "price", num: true },
  { label: "Qty", width: 80, sort: "qty", num: true },
  { label: "", width: 100, clear: true },
];

const TABLE_MIN_WIDTH = COLUMNS.reduce((n, c) => n + (c.width || 0), 0);

const listText = (v) => (v ? String(v).split(",").join(", ") : "");

function priceRange(variants) {
  const prices = variants
    .map((v) => parseFloat(v.price))
    .filter((n) => !Number.isNaN(n));
  if (!prices.length) return "—";
  const lo = Math.min(...prices);
  const hi = Math.max(...prices);
  return lo === hi ? Fmt.price(lo) : `${Fmt.price(lo)} – ${Fmt.price(hi)}`;
}

const totalQty = (variants) =>
  variants.reduce((n, v) => n + (v.inventory_quantity || 0), 0);

export class ProductsPage {
  constructor() {
    this.page = 1;
    this.q = "";
    this.sort = "title";
    this.dir = "asc";
    this.filters = {};
    this._request = 0;
    this._selects = [];
    this._textInputs = [];
  }

  destroy() {
    this._selects.forEach((s) => s.destroy());
    this._selects = [];
  }

  async render(container) {
    this.c = container;
    container.innerHTML = `
      <div class="page">
        <div class="page-title">Products</div>
        <div class="search-row">
          <input class="input" id="p-search" placeholder="Search all columns — title, vendor, UPC…">
          <button class="btn btn-primary" id="p-new">New product</button>
        </div>
        <div id="pager-top"></div>
        <div class="table-wrap">
          <table style="min-width:${TABLE_MIN_WIDTH}px">
            <colgroup>${COLUMNS.map((c) => `<col${c.width ? ` style="width:${c.width}px"` : ""}>`).join("")}</colgroup>
            <thead id="products-head"></thead>
            <tbody id="products-body"></tbody>
          </table>
        </div>
        <div id="pager-bottom"></div>
      </div>`;

    let options = {};
    try {
      options = await API.get("/api/products/filter-options");
    } catch (e) {
      Toast.error("Failed to load filter options: " + e.message);
    }
    this._buildHead(options);

    this.c
      .querySelector("#p-new")
      .addEventListener("click", () => this._openEdit());
    this.c.querySelector("#p-search").addEventListener(
      "input",
      debounce((e) => {
        this.q = e.target.value.trim();
        this.page = 1;
        this._load();
      }),
    );
    await this._load();
  }

  _buildHead(options) {
    const labels = document.createElement("tr");
    const filters = document.createElement("tr");
    filters.className = "filter-row";

    COLUMNS.forEach((col) => {
      const th = document.createElement("th");
      th.className = [col.num ? "num" : "", col.sort ? "sortable" : ""]
        .join(" ")
        .trim();
      th.innerHTML = `${col.label}<span class="sort-ind" data-sort="${col.sort || ""}"></span>`;
      if (col.sort) th.addEventListener("click", () => this._setSort(col.sort));
      labels.appendChild(th);

      const fth = document.createElement("th");
      if (col.filter === "text") {
        const input = document.createElement("input");
        input.className = "input filter-input";
        input.placeholder = "Filter…";
        input.addEventListener(
          "input",
          debounce(() => {
            this.filters[col.key] = input.value.trim();
            this.page = 1;
            this._load();
          }),
        );
        this._textInputs.push(input);
        fth.appendChild(input);
      } else if (col.filter === "select") {
        const select = createMultiSelect({
          placeholder: "All",
          options: options[col.key] || [],
          onChange: (values) => {
            this.filters[col.key] = values;
            this.page = 1;
            this._load();
          },
        });
        this._selects.push(select);
        fth.appendChild(select.el);
      } else if (col.clear) {
        const btn = document.createElement("button");
        btn.className = "btn btn-ghost btn-sm";
        btn.textContent = "Clear all";
        btn.addEventListener("click", () => this._clearFilters());
        fth.appendChild(btn);
      }
      filters.appendChild(fth);
    });

    this.c.querySelector("#products-head").replaceChildren(labels, filters);
    this._updateSortIndicators();
  }

  _clearFilters() {
    this.q = "";
    this.filters = {};
    this.page = 1;
    this.c.querySelector("#p-search").value = "";
    this._textInputs.forEach((i) => {
      i.value = "";
    });
    this._selects.forEach((s) => s.clear());
    this._load();
  }

  _setSort(key) {
    if (this.sort === key) {
      this.dir = this.dir === "asc" ? "desc" : "asc";
    } else {
      this.sort = key;
      this.dir = "asc";
    }
    this.page = 1;
    this._updateSortIndicators();
    this._load();
  }

  _updateSortIndicators() {
    this.c.querySelectorAll(".sort-ind").forEach((span) => {
      span.textContent =
        span.dataset.sort === this.sort ? (this.dir === "asc" ? "▲" : "▼") : "";
    });
  }

  _params() {
    const params = new URLSearchParams({
      page: String(this.page),
      sort: this.sort,
      dir: this.dir,
    });
    if (this.q) params.set("q", this.q);
    for (const [key, value] of Object.entries(this.filters)) {
      if (Array.isArray(value)) value.forEach((v) => params.append(key, v));
      else if (value) params.set(key, value);
    }
    return params;
  }

  async _load() {
    const body = this.c.querySelector("#products-body");
    const request = ++this._request;
    try {
      const data = await API.get(`/api/products?${this._params()}`);
      if (request !== this._request || !body.isConnected) return;
      this._renderRows(body, data.items);
      for (const id of ["#pager-top", "#pager-bottom"]) {
        buildPager(this.c.querySelector(id), data, (p) => {
          this.page = p;
          this._load();
        });
      }
    } catch (e) {
      if (request !== this._request || !body.isConnected) return;
      body.innerHTML = `<tr><td colspan="${COLUMNS.length}" class="empty-cell">${esc(e.message)}</td></tr>`;
    }
  }

  _renderRows(body, items) {
    if (!items.length) {
      body.innerHTML = `<tr><td colspan="${COLUMNS.length}" class="empty-cell">No products found</td></tr>`;
      return;
    }
    body.innerHTML = items
      .map(
        (p) => `
      <tr>
        <td>${thumb(p.image_url, p.title)}</td>
        <td>${truncCell(p.title)}</td>
        <td>${truncCell(p.vendor)}</td>
        <td>${statusBadge(p.status)}</td>
        <td>${truncCell(p.category_name)}</td>
        <td>${truncCell(p.type)}</td>
        <td>${truncCell(listText(p.genres))}</td>
        <td>${truncCell(listText(p.tags))}</td>
        <td class="num">${p.variants.length}</td>
        <td class="num">${priceRange(p.variants)}</td>
        <td class="num">${totalQty(p.variants)}</td>
        <td><button class="btn btn-ghost btn-sm" data-id="${esc(p.product_id)}">View</button></td>
      </tr>`,
      )
      .join("");
    body
      .querySelectorAll("button[data-id]")
      .forEach((btn) =>
        btn.addEventListener("click", () => this._openDetail(btn.dataset.id)),
      );
  }

  async _openDetail(productId) {
    let p;
    try {
      p = await API.get(`/api/products/${encodeURIComponent(productId)}`);
    } catch (e) {
      Toast.error(e.message);
      return;
    }

    const item = (label, value) => `
      <div>
        <div class="input-label">${label}</div>
        <div class="detail-value">${esc(value || "—")}</div>
      </div>`;

    const body = document.createElement("div");
    body.innerHTML = `
      <div class="detail-grid">
        ${item("Vendor", p.vendor)}
        ${item("Handle", p.handle)}
        ${item("Status", p.status)}
        ${item("Category", p.category_name)}
        ${item("Product type", p.product_type)}
        ${item("Genres", listText(p.genres))}
        ${item("Type", p.type)}
        ${item("UPC", p.upc)}
        ${item("Tags", listText(p.tags))}
        ${item("Last synced", Fmt.datetime(p.last_synced))}
      </div>
      ${p.images.length
        ? `
        <div class="section-label">Product images (${p.images.length})</div>
        <div class="image-strip">
          ${p.images.map((img) => `<img src="${esc(img.url)}" alt="${esc(p.title)}">`).join("")}
        </div>`
        : ""
      }
      <div class="section-label">Variants (${p.variants.length})</div>
      <div class="table-wrap">
        <table class="variants-table">
          <thead><tr>
            <th></th><th>Title</th><th>UPC</th>
            <th class="num">Price</th><th class="num">Cost</th><th class="num">Qty</th>
            <th>Weight</th><th>Release date</th><th>Variant tags</th><th>Description</th>
          </tr></thead>
          <tbody>
            ${p.variants
        .map(
          (v) => `
              <tr>
                <td>${thumb(v.image_url, v.title)}</td>
                <td>${truncCell(v.title)}</td>
                <td class="mono">${esc(Fmt.upc(v.upc))}</td>
                <td class="num">${Fmt.price(v.price)}</td>
                <td class="num">${Fmt.price(v.cost)}</td>
                <td class="num">${Fmt.qty(v.inventory_quantity)}</td>
                <td>${v.weight != null ? esc(`${v.weight} ${v.weight_unit || ""}`) : "—"}</td>
                <td>${esc(v.release_date || "—")}</td>
                <td>${truncCell(listText(v.variant_tags))}</td>
                <td>${truncCell(v.description)}</td>
              </tr>`,
        )
        .join("")}
          </tbody>
        </table>
      </div>`;

      try {
        const { items } = await API.get(`/api/products/${encodeURIComponent(productId)}/receipts`);
        if (items.length) body.insertAdjacentHTML("beforeend", `
          <div class="section-label">Receipts (${items.length})</div>
          <div class="table-wrap"><table class="variants-table">
            <thead><tr><th>Date</th><th>Order</th><th>UPC</th><th class="num">Qty</th><th></th></tr></thead>
            <tbody>${items.map((r) => `<tr>
              <td>${Fmt.datetime(r.created_at)}</td><td class="mono">${esc(r.number)}</td>
              <td class="mono">${esc(r.upc)}</td><td class="num">${r.qty}</td>
              <td>${r.reversed_at ? '<span class="badge badge-draft">Undone</span>' : ""}</td></tr>`).join("")}
            </tbody></table></div>`);
      } catch (_) { /* non-critical */ }

    Modal.open({
      title: p.title,
      body,
      width: "96vw",
      buttons: [
        { label: "Edit", cls: "btn-primary", onClick: () => this._openEdit(p) },
        { label: "Match WebAMI", onClick: () => this._openMatch(p) },
        {
          label: "Delete product",
          cls: "btn-danger",
          onClick: () => this._delete(p),
        },
        { label: "Close", onClick: Modal.close },
      ],
    });
  }

  _openEdit(p) {
    const isNew = !p;
    p = p || {
      title: "",
      vendor: "",
      product_type: "",
      handle: "",
      category_name: "",
      type: "",
      upc: "",
      release_date: "",
      genres: "",
      tags: "",
      status: "DRAFT",
      variants: [],
      images: [],
    };
    const LB = {
      POUNDS: 1,
      OUNCES: 1 / 16,
      KILOGRAMS: 2.20462,
      GRAMS: 1 / 453.592,
    };
    const lbs = (v) =>
      v.weight == null ? "" : +(v.weight * (LB[v.weight_unit] ?? 1)).toFixed(4);
    const inp = (name, label, val) => {
      const s = String(val ?? "");
      return `
        <div class="input-group">
          <label class="input-label">${label}</label>
          <input class="input" name="${name}" value="${esc(s)}" data-orig="${esc(s.trim())}">
        </div>`;
    };
    const PF = [
      ["title", "Title", p.title],
      ["vendor", "Vendor", p.vendor],
      ["product_type", "Product type", p.product_type],
      ["handle", "Handle", p.handle],
      ["category", "Category (name)", p.category_name],
      ["type", "Type", p.type],
      ["upc", "UPC", p.upc],
      ["release_date", "Release date", p.release_date],
      ["genres", "Genres (comma separated)", listText(p.genres)],
      ["tags", "Tags (comma separated)", listText(p.tags)],
    ];
    const VF = (v) => [
      ...(() => {
        const [e, c, a] = (v.title || "").split(" | ");
        return [
          ["edition", "Edition", e || "Standard"],
          ["color", "Color", c || ""],
          ["attributes", "Attributes", a || ""],
        ];
      })(),
      ["upc", "UPC", v.upc],
      ["description", "Description", v.description],
      ["release_date", "Release date", v.release_date],
      ["variant_tags", "Variant tags", v.variant_tags],
      ["price", "Price", v.price],
      ["cost", "Cost", v.cost],
      ["inventory_quantity", "Qty", v.inventory_quantity],
      ["weight", "Weight (lbs)", lbs(v)],
    ];

    const needNew = p.variants.every(
      (v) => !v.title || v.title === "Default Title",
    );
    const vblock = (v) => `
      <div class="form-grid" data-vid="${esc(v.variant_id)}" data-iid="${esc(v.inventory_item_id)}" data-mid="${esc(v.media_id)}" data-barcode="${esc(v.barcode)}"
           style="margin-bottom:16px">
        ${VF(v).map((f) => inp(...f)).join("")}
        ${v.variant_id ? `<button type="button" class="btn btn-danger btn-sm" data-delv="${esc(v.variant_id)}">Delete variant</button>` : ""}
      </div>`;
    const body = document.createElement("div");
    body.innerHTML = `
      <div class="form-grid" id="edit-product">
        ${PF.map((f) => inp(...f)).join("")}
        <div class="input-group">
          <label class="input-label">Status</label>
          <select class="input" name="status" data-orig="${esc(p.status)}">
            ${["ACTIVE", "DRAFT", "ARCHIVED"]
        .map(
          (s) =>
            `<option ${s === p.status ? "selected" : ""}>${s}</option>`,
        )
        .join("")}
          </select>
        </div>
      </div>
      <div class="section-label">Variants ${needNew && !isNew ? '<button type="button" class="btn btn-ghost btn-sm" id="autofill">Auto-fill from WebAMI</button>' : ""}
        <button type="button" class="btn btn-ghost btn-sm" id="addv">Add variant</button></div>
      <div id="variants">${(needNew ? [{}] : p.variants).map(vblock).join("")}</div>`;
    body.addEventListener("click", async (e) => {
      const d = e.target.closest("[data-delv]");
      if (!d || !confirm("Delete this variant? This cannot be undone.")) return;
      try {
        const res = await API.delete(
          `/api/products/${encodeURIComponent(p.product_id)}/variants/${encodeURIComponent(d.dataset.delv)}`,
        );
        if (res.dry_run) return Toast.warning("Test mode: nothing written");
        d.closest("[data-vid]").remove();
        Toast.success("Variant deleted");
        this._load();
      } catch (err) {
        Toast.error(err.message);
      }
    });
    body
      .querySelector("#addv")
      .addEventListener("click", () =>
        body
          .querySelector("#variants")
          .insertAdjacentHTML("beforeend", vblock({})),
      );

    const changed = (root) => {
      const out = {};
      root.querySelectorAll("[name]").forEach((i) => {
        const val = i.value.trim();
        if (val !== i.dataset.orig) out[i.name] = val;
      });
      return out;
    };

    const save = async (btn) => {
      const product = changed(body.querySelector("#edit-product"));
      ["tags", "genres"].forEach((k) => {
        if (k in product)
          product[k] = product[k]
            .split(",")
            .map((s) => s.trim())
            .filter(Boolean);
      });
      const variants = [...body.querySelectorAll("[data-vid]")]
        .map((r) => {
          const f = changed(r);
          if (!Object.keys(f).length) return null;
          if ("edition" in f || "color" in f || "attributes" in f) {
            const g = (n) => r.querySelector(`[name="${n}"]`).value.trim();
            f.title = variantTitle(g("edition"), g("color"), g("attributes"));
          }
          delete f.edition;
          delete f.color;
          delete f.attributes;
          if ("inventory_quantity" in f) {
            f.inventory_quantity = parseInt(String(f.inventory_quantity), 10);
          }
          if ("weight" in f) f.weight = parseFloat(String(f.weight));
          return {
            id: r.getAttribute("data-vid") ?? "",
            ...f,
            ...("inventory_quantity" in f
              ? { inventory_item_id: r.getAttribute("data-iid") ?? "" }
              : {}),
            ...(!r.getAttribute("data-vid") && r.dataset.mid
              ? { media_id: r.dataset.mid }
              : {}),
            ...(!r.getAttribute("data-vid") && r.dataset.barcode
              ? { barcode: r.dataset.barcode }
              : {}),
          };
        })
        .filter(Boolean);
      if (variants.some((v) => !v.id)) {
        product.upc = "";
        product.release_date = "";
      }
      if (!Object.keys(product).length && !variants.length)
        return Modal.close();
      const label = btn.textContent;
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span>Saving…';
      try {
        const res = isNew
          ? await API.post('/api/products', { product, variants })
          : await API.put(`/api/products/${encodeURIComponent(p.product_id)}`, { product, variants });
        Modal.close();
        res.dry_run ? Toast.warning('Test mode: nothing written') : Toast.success('Saved to Shopify');
        this._load();
      } catch (e) {
        Toast.error(e.message);
        btn.disabled = false;
        btn.textContent = label;
      }
    };

    const autofill = async () => {
      try {
        const { items } = await API.get(
          `/api/products/${encodeURIComponent(p.product_id)}/webami-suggestions`,
        );
        const c = items[0];
        if (!c) return Toast.info("No suggestion");
        const s = c.suggested;
        const row = body.querySelector('[data-vid=""]');
        const set = (n, val) => {
          const i = row.querySelector(`[name="${n}"]`);
          if (i && val != null && val !== "" && val !== "None") i.value = val;
        };
        set("edition", s.edition);
        set("color", s.color);
        set("attributes", s.attributes);
        set("upc", c.upc || p.upc);
        set("description", c.description);
        set("release_date", c.release_date);
        const old = p.variants[0];
        if (old) set("inventory_quantity", old.inventory_quantity);
        row.dataset.mid = old?.media_id || p.images?.[0]?.media_id || "";
        row.dataset.barcode = old?.barcode || "";
        const LBS = { lb: 1, lbs: 1, oz: 1 / 16, kg: 2.20462, g: 1 / 453.592 };
        const wl =
          c.weight != null
            ? +(c.weight * (LBS[c.weight_unit] ?? 1)).toFixed(4)
            : null;
        set("weight", wl ?? 0.0);
        const t = body.querySelector('#edit-product [name="title"]');
        if (s.title && t) t.value = s.title;
        const pf = (n) => body.querySelector(`#edit-product [name="${n}"]`);
        if (c.canon_artist) pf('vendor').value = c.canon_artist;
        if (c.genres && !pf('genres').value.trim())
          pf("genres").value = c.genres.split(",").join(", ");
        const slug = (x) =>
          String(x || "")
            .toLowerCase()
            .replace(/&/g, " and ")
            .replace(/[^a-z0-9]+/g, "-")
            .replace(/^-|-$/g, "");
        const tt = pf('title').value, vv = pf('vendor').value;
        const tm = tt.match(/^(.*?)\s+-\s+(.+)$/);
        const h = [vv, tm && slug(tm[2]) === slug(vv) ? tm[1] : tt, pf('type').value || pf('product_type').value]
          .map(slug)
          .filter(Boolean)
          .join("-");
        if (h) pf("handle").value = h;
        if (c.price != null) {
          set("cost", c.price.toFixed(2));
          set("price", (c.price / 0.66).toFixed(2));
        }
      } catch (e) {
        Toast.error(e.message);
      }
    };
    const afBtn = body.querySelector("#autofill");
    if (afBtn) afBtn.addEventListener("click", autofill);

    const slug = x => String(x || '').toLowerCase().replace(/&/g, ' and ')
      .replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
    const handleTitle = (t, vendor) => {
      const m = String(t || '').match(/^(.*?)\s+-\s+(.+)$/);
      return m && slug(m[2]) === slug(vendor) ? m[1] : t;
    };
    const pf2 = n => body.querySelector(`#edit-product [name="${n}"]`);
    const hf = pf2("handle");
    const note = document.createElement("div");
    note.className = "muted";
    note.style.display = "none";
    note.textContent = "Handle will change — old product URL will break";
    hf.parentNode.appendChild(note);
    const updNote = () => {
      note.style.display = !isNew && hf.value.trim() !== hf.dataset.orig ? "" : "none";
    };
    hf.addEventListener("input", updNote);
    ["vendor", "title", "type", "product_type"].forEach(n =>
      pf2(n).addEventListener("input", () => {
        hf.value = [pf2("vendor").value, handleTitle(pf2("title").value, pf2("vendor").value),
        pf2("type").value || pf2("product_type").value].map(slug).filter(Boolean).join("-");
        updNote();
      }));

    Modal.open({
      title: isNew ? "New product" : `Edit: ${p.title}`,
      body,
      width: "96vw",
      buttons: [
        { label: "Save", cls: "btn-primary", onClick: save },
        { label: "Cancel", onClick: Modal.close },
      ],
    });

    if (afBtn) autofill();
  }

  async _openMatch(p, search = false) {
    let items;
    try {
      ({ items } = await API.get(
        `/api/products/${encodeURIComponent(p.product_id)}/webami-suggestions?search=${search}`,
      ));
    } catch (e) {
      Toast.error(e.message);
      return;
    }
    const body = document.createElement("div");
    body.innerHTML = `
      <div class="muted">Current UPC: ${esc(p.upc || "—")} · Vendor: ${esc(p.vendor || "—")}</div>
      <div class="table-wrap" style="margin-top:12px">
        <table class="variants-table">
          <thead><tr><th></th><th>Source</th><th>Title</th><th>Artist</th><th>Format</th>
            <th>UPC</th><th class="num">Price</th></tr></thead>
          <tbody>
            ${items.length
        ? items
          .map(
            (c, i) => `
              <tr>
                <td><input type="radio" name="cand" value="${i}" ${i === 0 ? "checked" : ""}></td>
                <td>${esc(c.source)}${c.artist_match ? "" : " (artist differs)"}</td>
                <td>${truncCell(c.title)}</td>
                <td>${truncCell(c.artist)}</td>
                <td>${esc(c.product_type || "—")}</td>
                <td class="mono">${esc(c.upc)}</td>
                <td class="num">${c.price != null ? Fmt.price(c.price) : "—"}</td>
              </tr>`,
          )
          .join("")
        : '<tr><td colspan="7" class="empty-cell">No matches</td></tr>'
      }
          </tbody>
        </table>
      </div>
      <div class="input-group" style="margin-top:12px">
        <label class="check-row" style="margin-top:0">
          <input type="checkbox" name="upd_title"><span>Update title</span></label>
        <input class="input" name="title" value="${esc(items[0]?.suggested_title || p.title)}">
      </div>`;
    const titleInput = body.querySelector("[name=title]");
    body.querySelectorAll("[name=cand]").forEach((r) =>
      r.addEventListener("change", () => {
        titleInput.value = items[+r.value].suggested_title;
      }),
    );

    const save = async () => {
      const sel = body.querySelector("[name=cand]:checked");
      if (!sel) return;
      const c = items[+sel.value];
      const product = {};
      const variants = [];
      if (UPC_LEVEL === "product") product.upc = c.upc;
      else variants.push({ id: p.variants[0].variant_id, upc: c.upc });
      const title = titleInput.value.trim();
      if (
        body.querySelector("[name=upd_title]").checked &&
        title &&
        title !== p.title
      ) {
        product.title = title;
      }
      try {
        const res = await API.put(
          `/api/products/${encodeURIComponent(p.product_id)}`,
          { product, variants },
        );
        Modal.close();
        res.dry_run
          ? Toast.warning("Test mode: nothing written")
          : Toast.success("UPC saved to Shopify");
        this._load();
      } catch (e) {
        Toast.error(e.message);
      }
    };

    Modal.open({
      title: `Match WebAMI: ${p.title}`,
      body,
      width: "96vw",
      buttons: [
        { label: "Confirm match", cls: "btn-primary", onClick: save },
        { label: "Search WebAMI", onClick: () => this._openMatch(p, true) },
        { label: "Cancel", onClick: Modal.close },
      ],
    });
  }

  async _delete(p) {
    if (
      !confirm(
        `Delete "${p.title}" and all its variants from Shopify? This cannot be undone.`,
      )
    )
      return;
    try {
      const res = await API.delete(
        `/api/products/${encodeURIComponent(p.product_id)}`,
      );
      Modal.close();
      res.dry_run
        ? Toast.warning("Test mode: nothing written")
        : Toast.success("Product deleted");
      this._load();
    } catch (e) {
      Toast.error(e.message);
    }
  }
}
