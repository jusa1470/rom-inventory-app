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
const TO_LB = { pounds: 1, lb: 1, lbs: 1, ounces: 1 / 16, oz: 1 / 16,
  kilograms: 2.20462, kg: 2.20462, grams: 1 / 453.592, g: 1 / 453.592 };
const toLb = (w, u) =>
  w == null ? null : +(w * (TO_LB[String(u || "").toLowerCase()] ?? 1)).toFixed(4);
const slug = (x) => String(x || "").toLowerCase().replace(/&/g, " and ")
  .replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
const handleTitle = (t, vendor) => {
  const m = String(t || "").match(/^(.*?)\s+-\s+(.+)$/);
  return m && slug(m[2]) === slug(vendor) ? m[1] : t;
};
const makeHandle = (vendor, title, type) =>
  [vendor, handleTitle(title, vendor), type].map(slug).filter(Boolean).join("-");

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
      .addEventListener("click", () => this._openNew());
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

  async _openNew() {
    try { this._opts ||= await API.get("/api/products/new-options"); }
    catch (e) { return Toast.error(e.message); }
    const cats = this._opts.categories;
    const body = document.createElement("div");
    body.innerHTML = `<div class="input-group"><label class="input-label">Product type</label>
      <select class="input" name="cat"><option value="">Select…</option>
      ${cats.map((c, i) => `<option value="${i}">${esc(c.name)}</option>`).join("")}</select></div>`;
    Modal.open({ title: "New product", body, width: "480px", buttons: [
      { label: "Next", cls: "btn-primary", onClick: () => {
        const c = cats[body.querySelector("[name=cat]").value];
        if (!c) return Toast.error("Select a type");
        if (!c.media) return Toast.info("Not supported yet");
        this._openCondition(c);
      } },
      { label: "Cancel", onClick: Modal.close },
    ] });
  }
  
  _openCondition(cat) {
    const body = document.createElement("div");
    body.innerHTML = `<div class="muted">${esc(cat.name)}</div>`;
    Modal.open({ title: "New or used?", body, width: "420px", buttons: [
      { label: "New", cls: "btn-primary", onClick: () => this._openUpc(cat) },
      { label: "Used", cls: "btn-primary", onClick: () => this._openManual(cat, true) },
      { label: "Back", onClick: () => this._openNew() },
      { label: "Cancel", onClick: Modal.close },
    ] });
  }
  
  _openUpc(cat) {
    const body = document.createElement("div");
    body.innerHTML = `<div class="input-group"><label class="input-label">UPC(s)</label>
      <textarea class="input scope-box" name="upc" placeholder="One or more, comma/line separated"></textarea></div>
      <div id="n-st" class="muted" style="margin-top:8px"></div>`;
    const go = async (btn) => {
      const upcs = [...new Set(body.querySelector("[name=upc]").value.split(/[,\s]+/).filter(Boolean))];
      if (!upcs.length) return Toast.error("UPC required");
      btn.disabled = true;
      const st = body.querySelector("#n-st"), items = [];
      for (const [i, u] of upcs.entries()) {
        st.innerHTML = `<span class="spinner"></span>Looking up ${i + 1} of ${upcs.length}…`;
        try {
          const r = await API.get(`/api/products/by-upc/${encodeURIComponent(u)}`);
          items.push({ upc: u, ve: r.variant_exists, pe: r.product_exists, prefill: r.prefill,
                       image: r.image_url, wtitle: r.webami_title });
        } catch (e) { items.push({ upc: u, error: e.message }); }
      }
      this._openReview(cat, items);
    };
    Modal.open({ title: `New ${cat.name}`, body, width: "560px", buttons: [
      { label: "Look up", cls: "btn-primary", onClick: go },
      { label: "Manual entry", onClick: () => this._openManual(cat, false) },
      { label: "Back", onClick: () => this._openCondition(cat) },
      { label: "Cancel", onClick: Modal.close },
    ] });
  }
  
_openManual(cat, used) {
  const o = this._opts, cats = o.categories;
  let pe = null, extra = {}, hits = { items: [], webami: [] };
  const opts = (arr, v) => [...new Set([v || "", ...arr])]
    .map((x) => `<option ${x === v ? "selected" : ""}>${esc(x)}</option>`).join("");
  const f = (g, k, l, v = "") => `<div class="input-group"><label class="input-label">${l}</label>
    <input class="input" data-g="${g}" data-k="${k}" value="${esc(v)}"></div>`;
  const s = (g, k, l, arr, v = "") => `<div class="input-group"><label class="input-label">${l}</label>
    <select class="input" data-g="${g}" data-k="${k}">${opts(arr, v)}</select></div>`;
  const body = document.createElement("div");
  body.innerHTML = `
    <div class="card nm-card">
      <div class="section-label" style="margin-top:0">Product</div>
      <div class="fz-anchor">
        <div class="form-grid">${f("p", "title", "Title")}${f("p", "vendor", "Vendor / artist")}</div>
        <div id="fz" class="fz-drop" hidden></div>
      </div>
      <div class="form-grid">
        ${s("p", "type", "Type", o.type, cat.name)}
        ${s("p", "product_type", "Product type", o.product_type, cat.product_type)}
        ${s("p", "category", "Category", cats.map((c) => c.category), cat.category)}
        ${s("p", "status", "Status", ["ACTIVE", "DRAFT", "ARCHIVED"], "ACTIVE")}
        ${f("p", "genres", "Genres (comma separated)")}
      </div>
      <div id="ev"></div>
    </div>
    <div class="card nm-card">
      <div class="section-label" style="margin-top:0">Variant</div>
      <div class="form-grid">${f("v", "edition", "Edition", "Standard")}${f("v", "color", "Color")}${f("v", "attributes", "Attributes")}</div>
      <div class="section-label">Identifiers</div>
      <div class="form-grid">${f("v", "upc", "UPC")}${f("v", "release_date", "Release date")}</div>
      <div class="section-label">Pricing &amp; stock</div>
      <div class="form-grid">${f("v", "cost", "Cost")}${f("v", "price", "Price")}${f("v", "inventory_quantity", "Qty", "0")}</div>
    </div>`;
  const q = (g, k) => body.querySelector(`[data-g="${g}"][data-k="${k}"]`);
  const fz = body.querySelector("#fz"), ev = body.querySelector("#ev");
  const hide = () => { fz.hidden = true; };
  const KEEP = "#fz, [data-k=title], [data-k=vendor]";

  const setPe = (p) => {
    pe = p && { product_id: p.product_id, title: p.title };
    body.querySelectorAll('[data-g="p"]').forEach((i) => { i.disabled = !!pe; });
    ev.innerHTML = p ? `
      <div class="section-label"><span class="badge badge-used">Adding variant to existing product</span>
        Existing variants (${p.variants.length})</div>
      <div class="ev-list">${p.variants.map((v) => `<div class="ev-item"><span>${esc(v.title || "—")}</span>
        <span class="mono muted">${esc(v.upc || "no UPC")}</span><span class="muted">qty ${v.inventory_quantity ?? 0}</span></div>`).join("")
        || '<div class="muted">No variants</div>'}</div>
      <button class="btn btn-ghost btn-sm" data-clr style="margin-top:10px">Choose a different product</button>` : "";
    ev.querySelector("[data-clr]")?.addEventListener("click", () => setPe(null));
  };

  const useShopify = (p) => {
    q("p", "title").value = p.title;
    q("p", "vendor").value = p.vendor || "";
    q("p", "type").value = p.type || cat.name;
    if (p.product_type) q("p", "product_type").value = p.product_type;
    const c = cats.find((c) => c.category.split(" > ").pop() === p.category_name);
    if (c) q("p", "category").value = c.category;
    q("p", "genres").value = (p.genres || "").split(",").join(", ");
    setPe(p);
    hide();
  };

  const useWm = (w) => {
    extra = {};
    ["edition", "color", "attributes", "upc", "release_date", "cost", "price"]
      .forEach((k) => { q("v", k).value = k === "edition" ? "Standard" : ""; });
    for (const [g, d] of [["p", w.prefill.product], ["v", w.prefill.variant]])
      for (const [k, val] of Object.entries(d)) {
        const i = q(g, k);
        if (i) i.value = val; else if (g === "v") extra[k] = val;
      }
    hide();
  };

  const drawFz = () => {
    const row = (badge, cls, attr, i, main, sub) => `<div class="fz-item" data-${attr}="${i}">
      <span class="badge ${cls}">${badge}</span><div class="pair"><span>${main}</span><span class="sub">${sub}</span></div></div>`;
    fz.innerHTML = hits.items.map((p, i) => row("In Shopify", "badge-active", "sh", i,
        `${esc(p.title)} — ${esc(p.vendor || "")}`,
        `${esc(p.type || "")} · ${p.variants.map((v) => esc(v.title || "—")).join(" · ") || "no variants"}`)).join("")
      + hits.webami.map((w, i) => row("WebAMI", "badge-new", "wm", i,
        `${esc(w.title)} — ${esc(w.artist || "")}`,
        `${esc(w.product_type || "")} · <span class="mono">${esc(w.upc)}</span>${w.used_by.length ? " · UPC already in Shopify" : ""}`)).join("");
    fz.hidden = !fz.innerHTML;
  };

  fz.addEventListener("click", (e) => {
    const t = e.target.closest(".fz-item");
    if (!t) return;
    t.dataset.sh != null ? useShopify(hits.items[+t.dataset.sh]) : useWm(hits.webami[+t.dataset.wm]);
  });
  body.addEventListener("mousedown", (e) => { if (!e.target.closest(KEEP)) hide(); });
  body.addEventListener("focusin", (e) => { if (!e.target.closest(KEEP)) hide(); });

  const look = debounce(async () => {
    if (pe) return;
    try {
      const p = new URLSearchParams({ title: q("p", "title").value, vendor: q("p", "vendor").value, type: cat.name, used });
      hits = await API.get(`/api/products/fuzzy?${p}`);
      drawFz();
    } catch (_) {}
  }, 350);
  ["title", "vendor"].forEach((k) => {
    q("p", k).addEventListener("input", look);
    q("p", k).addEventListener("focus", () => { if (!pe && fz.innerHTML) fz.hidden = false; });
  });
  q("p", "type").addEventListener("change", (e) => {
    const c = cats.find((c) => c.name === e.target.value);
    if (c) { q("p", "product_type").value = c.product_type; q("p", "category").value = c.category; }
  });
  q("v", "cost").addEventListener("input", (e) => {
    const c = parseFloat(e.target.value);
    if (c > 0) q("v", "price").value = (c / 0.66).toFixed(2);
  });

  Modal.open({ title: `${used ? "Used" : "New"} ${cat.name} — manual`, body, width: "96vw", buttons: [
    { label: "Add to review", cls: "btn-primary", onClick: () => {
      const g = { p: {}, v: {} };
      body.querySelectorAll("[data-k]").forEach((i) => { if (i.value.trim()) g[i.dataset.g][i.dataset.k] = i.value.trim(); });
      if (!g.p.title || !g.p.vendor) return Toast.error("Title and vendor required");
      g.p.tags = `${used ? "Used" : "New"}, ${cat.name}`;
      this._openReview(cat, [{ upc: g.v.upc || "", pe, p: g.p, v: { ...extra, ...g.v }, wtitle: "" }]);
    } },
    { label: "Back", onClick: () => (used ? this._openCondition(cat) : this._openUpc(cat)) },
    { label: "Cancel", onClick: Modal.close },
  ] });
}
  
  _openReview(cat, items) {
    const o = this._opts, D = 0.66;
    items.forEach((it) => {
      it.p ||= { ...(it.prefill?.product || {}) };
      it.v ||= { ...(it.prefill?.variant || {}) };
      it.v.inventory_quantity ??= "0";
      it.acts = it.ve ? [["update", "Update existing variant"], ["skip", "Skip"]]
        : it.pe ? [["variant", `Add variant to "${it.pe.title}"`], ["new", "Create separate product"], ["skip", "Skip"]]
        : [["new", "Create product"], ["skip", "Skip"]];
      it.act ||= it.error ? "skip" : it.acts[0][0];
    });
    const body = document.createElement("div");
    const inp = (i, g, k, w) => `<input class="input" style="height:28px;width:${w}px" data-i="${i}" data-g="${g}" data-k="${k}" value="${esc(items[i][g][k] ?? "")}">`;
    const dd = (i, g, k, opts) => { const v = items[i][g][k] || "";
      return `<select class="input" style="height:28px" data-i="${i}" data-g="${g}" data-k="${k}">${[...new Set([v, ...opts])].map((x) => `<option ${x === v ? "selected" : ""}>${esc(x)}</option>`).join("")}</select>`; };
    const draw = () => {
      body.innerHTML = `<div class="muted" id="rv-s" style="margin-bottom:8px"></div>
        <div class="table-wrap modal-fit"><table class="variants-table">
        <thead><tr><th>Item</th><th>Action</th><th>Title</th><th>Vendor</th><th>Type</th><th>Status</th>
          <th>Edition</th><th>Color</th><th>Attributes</th><th>Cost</th><th>Price</th><th>Qty</th><th></th></tr></thead>
        <tbody>${items.length ? items.map((it, i) => it.error
          ? `<tr><td class="mono">${esc(it.upc)}</td><td colspan="11">${esc(it.error)}</td><td><button class="btn btn-ghost btn-sm" data-rm="${i}">Remove</button></td></tr>`
          : `<tr class="${it.ve ? "rv-ex" : it.pe ? "rv-pe" : "rv-new"}">
          <td><div style="display:flex;gap:8px;align-items:center">${thumb(it.image, it.wtitle)}
            <div class="pair"><span>${esc(it.wtitle || "")}</span><span class="sub mono">${esc(it.upc)}</span>
            <span class="badge ${it.ve || it.pe ? "badge-used" : "badge-new"}">${it.ve ? "In Shopify" : it.pe ? "Product in Shopify" : "New"}</span></div></div></td>
          <td><select class="input" style="height:28px" data-act="${i}">${it.acts.map(([v, l]) => `<option value="${v}" ${v === it.act ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></td>
          <td>${inp(i, "p", "title", 220)}</td><td>${inp(i, "p", "vendor", 150)}</td>
          <td>${dd(i, "p", "type", o.type)}</td><td>${dd(i, "p", "status", ["ACTIVE", "DRAFT", "ARCHIVED"])}</td>
          <td>${inp(i, "v", "edition", 130)}</td><td>${inp(i, "v", "color", 130)}</td><td>${inp(i, "v", "attributes", 130)}</td>
          <td>${inp(i, "v", "cost", 70)}</td><td>${inp(i, "v", "price", 70)}</td><td>${inp(i, "v", "inventory_quantity", 60)}</td>
          <td><button class="btn btn-ghost btn-sm" data-rm="${i}">Remove</button></td></tr>`).join("")
          : '<tr><td colspan="13" class="empty-cell">Nothing to review</td></tr>'}</tbody></table></div>`;
      sum();
    };
    const sum = () => {
      const c = (a) => items.filter((x) => x.act === a).length;
      body.querySelector("#rv-s").textContent = `${c("new")} new products · ${c("variant")} new variants · ${c("update")} updates · ${c("skip")} skipped`;
    };
    body.addEventListener("input", (e) => {
      const d = e.target.dataset;
      if (!d.k) return;
      items[+d.i][d.g][d.k] = e.target.value;
      if (d.k === "cost" && parseFloat(e.target.value) > 0) {
        const p = (parseFloat(e.target.value) / D).toFixed(2);
        items[+d.i].v.price = p;
        body.querySelector(`[data-i="${d.i}"][data-k="price"]`).value = p;
      }
    });
    body.addEventListener("change", (e) => {
      const d = e.target.dataset;
      if (d.k) items[+d.i][d.g][d.k] = e.target.value;
      if (d.act != null) { items[+d.act].act = e.target.value; sum(); }
    });
    body.addEventListener("click", (e) => {
      const b = e.target.closest("[data-rm]");
      if (b) { items.splice(+b.dataset.rm, 1); draw(); }
    });
    draw();
    Modal.open({ title: "Review", body, width: "98vw", buttons: [
      { label: "Create / save all", cls: "btn-primary", onClick: (btn) => this._createAll(items, btn) },
      { label: "Back", onClick: () => this._openUpc(cat) },
      { label: "Cancel", onClick: Modal.close },
    ] });
  }
  
  _variantPayload(v) {
    const o = { title: variantTitle(v.edition, v.color, v.attributes) };
    for (const k of ["upc", "description", "release_date", "price", "cost", "image_url"]) if (v[k]) o[k] = v[k];
    if (v.inventory_quantity !== "" && v.inventory_quantity != null) o.inventory_quantity = parseInt(v.inventory_quantity, 10) || 0;
    if (v.weight) o.weight = parseFloat(v.weight);
    return o;
  }
  
  _productPayload(p) {
    const o = { status: "ACTIVE", ...p };
    for (const k of ["tags", "genres"]) if (typeof o[k] === "string") o[k] = o[k].split(",").map((s) => s.trim()).filter(Boolean);
    o.handle ||= makeHandle(o.vendor, o.title, o.type || o.product_type);
    return o;
  }
  
  async _createAll(items, btn) {
    btn.disabled = true;
    let ok = 0;
    const errs = [];
    for (const it of items) {
      if (it.act === "skip" || it.error) continue;
      btn.innerHTML = `<span class="spinner"></span>${ok + errs.length + 1}…`;
      const v = this._variantPayload(it.v);
      try {
        let r;
        if (it.act === "update") {
          delete v.inventory_quantity;
          r = await API.put(`/api/products/${encodeURIComponent(it.ve.product_id)}`, { product: {}, variants: [{ id: it.ve.variant_id, ...v }] });
        } else if (it.act === "variant") {
          r = await API.put(`/api/products/${encodeURIComponent(it.pe.product_id)}`, { product: {}, variants: [v] });
        } else {
          r = await API.post("/api/products", { product: this._productPayload(it.p), variants: [v] });
        }
        if (r.dry_run) { Modal.close(); return Toast.warning("Test mode: nothing written"); }
        ok++;
      } catch (e) { errs.push(`${it.upc || it.p.title}: ${e.message}`); }
    }
    Modal.close();
    errs.length ? Toast.warning(`Saved ${ok}; ${errs.length} failed: ${errs[0]}`) : Toast.success(`Saved ${ok}`);
    this._load();
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
    let vch = {};
    try {
      vch = (await API.get(`/api/products/${encodeURIComponent(productId)}/variant-channels`)).items;
    } catch (_) {}
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
            <th>Channels</th><th>Weight</th><th>Release date</th><th>Variant tags</th><th>Description</th>
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
                <td>${truncCell((vch[v.variant_id] || []).map((c) => c.name).join(", "))}</td>
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

  async _openEdit(p, prefill, onSaved) {
    try { this._opts ||= await API.get("/api/products/new-options"); }
    catch (e) { return Toast.error(e.message); }
    const o = this._opts, cats = o.categories;
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
      status: "ACTIVE",
      variants: [],
      images: [],
    };
    const lbs = (v) => toLb(v.weight, v.weight_unit) ?? "";
    const inp = (name, label, val) => {
      const s = String(val ?? "");
      return `
        <div class="input-group">
          <label class="input-label">${label}</label>
          <input class="input" name="${name}" value="${esc(s)}" data-orig="${esc(s.trim())}">
        </div>`;
    };
    const sel = (name, label, val, arr) => `
        <div class="input-group">
          <label class="input-label">${label}</label>
          <select class="input" name="${name}" data-orig="${esc(String(val ?? "").trim())}">
            ${[...new Set(["", val || "", ...arr])]
              .map((x) => `<option ${x === (val || "") ? "selected" : ""}>${esc(x)}</option>`).join("")}
          </select>
        </div>`;
    const SEL = {
      category: cats.map((c) => c.category.split(" > ").pop()),
      product_type: o.product_type,
      type: o.type,
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
      ["image_url", "Image URL", v.variant_id ? "" : v.image_url],
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
        ${VF(v).map((f) => {
          const h = inp(...f);
          return ["edition", "color", "attributes"].includes(f[0])
            ? h.replace('<div class="input-group">', '<div class="input-group" data-opt>') : h;
        }).join("")}
        <details class="vch" style="grid-column:1/-1"><summary class="input" style="display:flex;align-items:center;cursor:pointer">Channels…</summary>
          <div class="vch-list" style="padding:8px 0"></div></details>
        ${v.variant_id ? `<button type="button" class="btn btn-danger btn-sm" data-delv="${esc(v.variant_id)}">Delete variant</button>` : ""}
      </div>`;
    const body = document.createElement("div");
    body.innerHTML = `
      <div class="form-grid" id="edit-product">
        ${PF.map((f) => (SEL[f[0]] ? sel(...f, SEL[f[0]]) : inp(...f))).join("")}
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
      <div class="section-label" id="vhead">Variants ${needNew && !isNew ? '<button type="button" class="btn btn-ghost btn-sm" id="autofill">Auto-fill from WebAMI</button>' : ""}
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
    body.querySelector("#addv").addEventListener("click", () => {
      body.querySelector("#variants").insertAdjacentHTML("beforeend", vblock({}));
      if (chs.length) fillCh([...body.querySelectorAll("[data-vid]")].pop());
    });

    let chs = [], vch = {};
    const chSum = (row) => {
      const n = row.querySelectorAll("[data-ch]:checked").length;
      row.querySelector(".vch summary").textContent = `${n} of ${chs.length} channels`;
    };
    const fillCh = (row) => {
      const vid = row.getAttribute("data-vid");
      const cur = vid ? new Set((vch[vid] || []).map((c) => c.id)) : null;
      row._orig = cur ? [...cur] : null;
      row.querySelector(".vch-list").innerHTML = chs.map((c) => `
        <label class="check-row" style="margin:0 0 6px"><input type="checkbox" data-ch="${esc(c.id)}" ${!cur || cur.has(c.id) ? "checked" : ""}><span>${esc(c.name)}</span></label>`).join("");
      row.querySelectorAll("[data-ch]").forEach((i) => i.addEventListener("change", () => chSum(row)));
      chSum(row);
    };
    Promise.all([
      API.get("/api/products/channels"),
      isNew ? { items: {} } : API.get(`/api/products/${encodeURIComponent(p.product_id)}/variant-channels`),
    ]).then(([a, b]) => {
      chs = a.items;
      vch = b.items;
      body.querySelectorAll("[data-vid]").forEach(fillCh);
    }).catch((e) => Toast.error(e.message));

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
          const ids = [...r.querySelectorAll("[data-ch]:checked")].map((c) => c.dataset.ch);
          const chg = chs.length > 0 && (!r.getAttribute("data-vid") ||
            chs.some((c) => (r._orig || []).includes(c.id) !== ids.includes(c.id)));
          if (!Object.keys(f).length && !chg) return null;
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
            ...(chg ? { channels: ids } : {}),
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
        if (onSaved) onSaved();
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
        set("image_url", c.image_url);
        const old = p.variants[0];
        if (old) set("inventory_quantity", old.inventory_quantity);
        row.dataset.mid = old?.media_id || p.images?.[0]?.media_id || "";
        row.dataset.barcode = old?.barcode || "";
        set("weight", toLb(c.weight, c.weight_unit) ?? 0);
        const t = body.querySelector('#edit-product [name="title"]');
        if (s.title && t) t.value = s.title;
        const pf = (n) => body.querySelector(`#edit-product [name="${n}"]`);
        const art = c.canon_artist;
        if (art) pf('vendor').value = art;
        if (c.genres && !pf('genres').value.trim())
          pf("genres").value = c.genres.split(",").join(", ");
        const df = c.defaults || {};
        if (df.type && !pf("type").value.trim()) pf("type").value = df.type;
        if (df.product_type) pf("product_type").value = df.product_type;
        if (df.category) pf("category").value = df.category;
        if (df.tags && !pf("tags").value.trim()) pf("tags").value = df.tags;
        const h = makeHandle(pf("vendor").value, pf("title").value,
          pf("type").value || pf("product_type").value);
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
        hf.value = makeHandle(pf2("vendor").value, pf2("title").value,
          pf2("type").value || pf2("product_type").value);
        updNote();
      }));
    
    const applyOpts = () => {
      const c = cats.find((x) => x.name === pf2("type").value);
      const used = /\s-\s*u$/i.test(pf2("title").value.trim())
        || pf2("tags").value.toLowerCase().split(",").some((t) => t.trim() === "used");
      const show = !used && (!pf2("type").value || !!(c && c.media));
      const gm = !pf2("type").value || !!(c && c.media);
      const g = pf2("genres").closest(".input-group");
      g.style.display = gm ? "" : "none";
      body.querySelectorAll("[data-opt]").forEach((x) => { x.style.display = show ? "" : "none"; });
      const af = body.querySelector("#autofill");
      if (af) af.style.display = show ? "" : "none";
      body.querySelector("#addv").style.display = show ? "" : "none";
      body.querySelector("#vhead").firstChild.textContent = show ? "Variants " : "";
    };
    pf2("type").addEventListener("change", (e) => {
      const c = cats.find((x) => x.name === e.target.value);
      if (c) {
        pf2("product_type").value = c.product_type;
        pf2("category").value = c.category.split(" > ").pop();
        pf2("product_type").dispatchEvent(new Event("input"));
      }
      applyOpts();
    });
    pf2("tags").addEventListener("input", applyOpts);
    pf2("title").addEventListener("input", applyOpts);
    body.querySelector("#addv").addEventListener("click", applyOpts);
    applyOpts();

    if (prefill) {
      let row = prefill.variantId
        ? [...body.querySelectorAll("[data-vid]")].find((r) => r.dataset.vid === prefill.variantId)
        : null;
      if (!row) {
        if (!isNew && !needNew)
          body.querySelector("#variants").insertAdjacentHTML("beforeend", vblock({}));
        row = [...body.querySelectorAll("[data-vid]")].pop();
      }
      const put = (root, o) =>
        Object.entries(o || {}).forEach(([k, v]) => {
          const i = root.querySelector(`[name="${k}"]`);
          if (i) i.value = v;
        });
      put(body.querySelector("#edit-product"), prefill.product || {});
      put(row, prefill.variant || {});
      if (prefill.product && prefill.product.title)
        pf2("title").dispatchEvent(new Event("input"));
    }

    Modal.open({
      title: isNew ? "New product" : `Edit: ${p.title}`,
      body,
      width: "96vw",
      buttons: [
        { label: "Save", cls: "btn-primary", onClick: save },
        ...(onSaved ? [{ label: "Skip", onClick: onSaved }] : []),
        { label: "Cancel", onClick: Modal.close },
      ],
    });

    if (afBtn) autofill().then(applyOpts);
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
        <input class="input" name="title" value="${esc(items[0]?.suggested.title || p.title)}">
      </div>`;
    const titleInput = body.querySelector("[name=title]");
    body.querySelectorAll("[name=cand]").forEach((r) =>
      r.addEventListener("change", () => {
        titleInput.value = items[+r.value].suggested.title;
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
