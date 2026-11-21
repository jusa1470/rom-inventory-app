import { API } from "../api.js";
import { Toast } from "../components/toast.js";
import { buildPager, debounce, esc, truncCell } from "../util.js";

const FIELDS = {
  products: [["title", "Title"], ["vendor", "Vendor"], ["product_type", "Product type"],
    ["type", "MF type"], ["genres", "MF genres"], ["category", "Category"],
    ["mismatch", "Mismatched"]],
  variants: [["title", "Title"], ["image", "Image"], ["price", "Price"], ["cost", "Cost"],
    ["weight", "Weight"], ["release_date", "Release date"], ["upc", "UPC"],
    ["description", "Description"]],
};
const lab = (kind, f) => (FIELDS[kind].find(x => x[0] === f) || [, f])[1];
const k = (kind, id) => `${kind}|${id}`;
const ref = key => { const [kind, id] = key.split("|"); return { kind, id }; };
const BADGE = "width:110px;flex-shrink:0;height:auto;min-height:22px;white-space:normal;justify-content:center;text-align:center;line-height:1.2;padding:3px 8px";
let OPT = { categories: [], type: [], product_type: [], genres: [] };
const optsFor = (kind, f) => kind !== "products" ? null : ({
  type: OPT.type, product_type: OPT.product_type, genres: OPT.genres,
  category: OPT.categories.map(c => c.category) })[f] || null;
const lbl = (f, x) => f === "category" ? String(x).split(" > ").pop() : x;
const field = (kind, f, val, attrs, ph = "enter value") => {
  const a = optsFor(kind, f);
  let v = val ?? "";
  if (a) {
    v = a.find(x => lbl(f, x) === lbl(f, v)) || v;
    const list = [...new Set([v, ...a])].filter(Boolean)
      .sort((x, y) => lbl(f, x).localeCompare(lbl(f, y), undefined, { sensitivity: "base" }));
    return `<select class="input" ${attrs} style="height:28px;min-width:0;flex:1">${["", ...list]
      .map(x => `<option value="${esc(x)}" ${x === v ? "selected" : ""}>${esc(lbl(f, x))}</option>`).join("")}</select>`;
  }
  return `<input class="input" ${attrs} style="height:28px;min-width:0;flex:1" value="${esc(v)}" placeholder="${ph}" title="${esc(v)}">`;
};

export class MissingPage {
  constructor() {
    this.kind = "products"; this.page = 1; this.q = ""; this.review = false;
    this.fields = new Set(); this.sel = new Set(); this.edits = {}; this.byKey = {};
    this._request = 0;
  }
  destroy() {}

  async render(c) {
    try { OPT = await API.get("/api/products/new-options"); } catch (_) {}
    this.c = c;
    c.innerHTML = `
      <div class="page">
        <div class="page-title">Missing Data</div>
        <div class="search-row" style="align-items:center">
          <button class="btn btn-sm" data-k="products">Products</button>
          <button class="btn btn-sm" data-k="variants">Variants</button>
          <input class="input" id="x-search" placeholder="Search title or vendor…" style="margin-left:12px">
          <label class="check-row" style="margin:0 0 0 12px"><input type="checkbox" id="x-rev"><span>Needs review</span></label>
        </div>
        <div class="search-row" id="x-fields" style="flex-wrap:wrap"></div>
        <div class="search-row" style="flex-wrap:wrap;align-items:center">
          <button class="btn btn-ghost btn-sm" data-a="sel">Select shown</button>
          <button class="btn btn-ghost btn-sm" data-a="desel">Deselect all</button>
          <button class="btn btn-ghost btn-sm" data-a="stsel">Stage selected</button>
          <button class="btn btn-ghost btn-sm" data-a="stall">Stage all shown</button>
          <button class="btn btn-ghost btn-sm" data-a="rvon">Mark selected for review</button>
          <button class="btn btn-ghost btn-sm" data-a="rvoff">Clear review</button>
          <button class="btn btn-primary btn-sm" data-a="queue">Review queue (<span id="x-count">0</span>)</button>
        </div>
        <div id="x-pager-top"></div>
        <div class="table-wrap"><table class="variants-table fit">
          <colgroup><col style="width:3%"><col style="width:27%"><col style="width:15%"><col style="width:43%"><col style="width:12%"></colgroup>
          <thead><tr><th></th><th>Title</th><th>Vendor</th><th>Missing</th><th></th></tr></thead>
          <tbody id="x-body"></tbody></table></div>
        <div id="x-pager-bottom"></div>
      </div>`;
    c.querySelectorAll("[data-k]").forEach(b => b.addEventListener("click", () => {
      this.kind = b.dataset.k; this.fields.clear(); this.sel.clear(); this.page = 1;
      this._tabs(); this._load();
    }));
    c.querySelector("#x-search").addEventListener("input", debounce(e => {
      this.q = e.target.value.trim(); this.page = 1; this._load();
    }));
    c.querySelector("#x-rev").addEventListener("change", e => {
      this.review = e.target.checked; this.page = 1; this._load();
    });
    const body = c.querySelector("#x-body");
    body.addEventListener("input", e => {
      const d = e.target.dataset;
      if (d.e) (this.edits[d.e] ||= {})[d.f] = e.target.value;
    });
    body.addEventListener("change", e => {
      const d = e.target.dataset;
      if (d.s) e.target.checked ? this.sel.add(d.s) : this.sel.delete(d.s);
      if (d.e) (this.edits[d.e] ||= {})[d.f] = e.target.value;
    });
    body.addEventListener("click", e => {
      const b = e.target.closest("button");
      if (!b) return;
      const r = this.byKey[b.dataset.key];
      if (b.dataset.st) this._stage([r]);
      if (b.dataset.rv) this._review([r], !r.review);
    });
    c.addEventListener("click", e => {
      const a = e.target.closest("button[data-a]")?.dataset.a;
      if (!a) return;
      const shown = Object.values(this.byKey).filter(r => r.kind === this.kind && r.shown);
      const chosen = [...this.sel].map(x => this.byKey[x]).filter(r => r && r.kind === this.kind);
      if (a === "sel") { shown.forEach(r => this.sel.add(k(r.kind, r.id))); this._load(); }
      if (a === "desel") { this.sel.clear(); this._load(); }
      if (a === "stsel") this._stage(chosen);
      if (a === "stall") this._stage(shown);
      if (a === "rvon") this._review(chosen, true);
      if (a === "rvoff") this._review(chosen, false);
      if (a === "queue") this._queue();
    });
    this._tabs();
    this._count();
    await this._load();
  }

  _tabs() {
    this.c.querySelectorAll("[data-k]").forEach(b => {
      b.className = `btn btn-sm ${b.dataset.k === this.kind ? "btn-primary" : "btn-ghost"}`;
    });
    const box = this.c.querySelector("#x-fields");
    box.innerHTML = FIELDS[this.kind].map(([f, l]) =>
      `<label class="check-row" style="margin:0 12px 0 0"><input type="checkbox" data-f="${f}"><span>${l}</span></label>`).join("");
    box.querySelectorAll("[data-f]").forEach(cb => cb.addEventListener("change", () => {
      cb.checked ? this.fields.add(cb.dataset.f) : this.fields.delete(cb.dataset.f);
      this.page = 1; this._load();
    }));
  }

  _v(r, f) {
    return this.edits[k(r.kind, r.id)]?.[f] ?? r.staged[f] ?? r.suggest[f] ?? "";
  }

  async _count() {
    try {
      const { items } = await API.get("/api/missing/queue");
      const el = this.c.querySelector("#x-count");
      if (el) el.textContent = items.length;
    } catch (_) {}
  }

  async _stage(list) {
    const items = [];
    list.forEach(r => r.missing.forEach(f => {
      const v = String(this._v(r, f)).trim();
      if (v) items.push({ kind: r.kind, id: r.id, field: f, value: v });
    }));
    if (!items.length) return Toast.info("Nothing to stage");
    try {
      await API.post("/api/missing/stage", { items });
      list.forEach(r => delete this.edits[k(r.kind, r.id)]);
      Toast.success(`Staged ${items.length} fields`);
      this._count(); this._load();
    } catch (e) { Toast.error(e.message); }
  }

  async _review(list, on) {
    if (!list.length) return Toast.info("Nothing selected");
    try {
      await API.post("/api/missing/review", { kind: this.kind, ids: list.map(r => r.id), on });
      this._load();
    } catch (e) { Toast.error(e.message); }
  }

  async _load() {
    const body = this.c.querySelector("#x-body");
    const req = ++this._request;
    try {
      const p = new URLSearchParams({ kind: this.kind, page: this.page });
      if (this.q) p.set("q", this.q);
      if (this.review) p.set("review", "true");
      this.fields.forEach(f => p.append("fields", f));
      const data = await API.get(`/api/missing?${p}`);
      if (req !== this._request || !body.isConnected) return;
      Object.values(this.byKey).forEach(r => { r.shown = false; });
      data.items.forEach(r => { r.kind = this.kind; r.shown = true; this.byKey[k(r.kind, r.id)] = r; });
      body.innerHTML = data.items.length ? data.items.map(r => {
        const key = k(r.kind, r.id);
        return `<tr>
          <td><input type="checkbox" data-s="${esc(key)}" ${this.sel.has(key) ? "checked" : ""}></td>
          <td><div class="pair"><span title="${esc(r.title)}">${esc(r.title)}</span><span class="sub" title="${esc(r.variant_title || "")}">${esc(r.variant_title || "")}</span></div>
            ${r.kind === "products" ? `<div class="muted" style="white-space:normal;line-height:1.4"><div>Category: ${esc(r.current.category || "—")}</div><div>Product type: ${esc(r.current.product_type || "—")}</div><div>Type: ${esc(r.current.type || "—")}</div></div>` : ""}
            ${r.review ? '<span class="badge badge-used">Review</span>' : ""}</td>
          <td>${truncCell(r.vendor)}</td>
          <td style="white-space:normal">${r.missing.map(f => `
            <div style="display:flex;gap:6px;align-items:center;margin:2px 0">
              <span class="badge ${r.staged[f] != null ? "badge-new" : "badge-error"}" style="${BADGE}">${esc(lab(r.kind, f))}</span>
              ${field(r.kind, f, this._v(r, f), `data-e="${esc(key)}" data-f="${f}"`)}
              ${r.current && r.current[f] ? `<span class="muted" style="flex-shrink:0;max-width:140px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(r.current[f])}">now: ${esc(r.current[f])}</span>` : ""}
            </div>`).join("")}</td>
          <td style="white-space:normal;overflow:visible"><div style="display:flex;flex-direction:column;gap:4px"><button class="btn btn-primary btn-sm" data-st="1" data-key="${esc(key)}">Stage</button>
            <button class="btn btn-ghost btn-sm" data-rv="1" data-key="${esc(key)}">${r.review ? "Clear review" : "Needs review"}</button></div></td>
        </tr>`;
      }).join("") : '<tr><td colspan="5" class="empty-cell">Nothing missing</td></tr>';
      for (const id of ["#x-pager-top", "#x-pager-bottom"])
        buildPager(this.c.querySelector(id), data, pg => { this.page = pg; this._load(); });
    } catch (e) {
      if (req === this._request && body.isConnected)
        body.innerHTML = `<tr><td colspan="5" class="empty-cell">${esc(e.message)}</td></tr>`;
    }
  }

  async _queue() {
    const sel = new Set();
    let items = [];
    const post = (u, b) => API.post(`/api/missing/${u}`, b).catch(e => Toast.error(e.message));
    const load = async () => { ({ items } = await API.get("/api/missing/queue")); draw(); };
    const draw = () => {
      const g = new Map();
      items.forEach(i => { const key = k(i.kind, i.id); if (!g.has(key)) g.set(key, []); g.get(key).push(i); });
      const lines = [...g];
      [...sel].forEach(x => { if (!g.has(x)) sel.delete(x); });
      this.c.innerHTML = `<div class="page" id="mq">
        <div class="page-title">Review Missing Data</div>
        <div class="search-row">
          <button class="btn btn-ghost btn-sm" data-a="back">‹ Back</button>
          <button class="btn btn-ghost btn-sm" data-a="all">Select all</button>
          <button class="btn btn-ghost btn-sm" data-a="none">Deselect all</button>
          <button class="btn btn-ghost btn-sm" data-a="rmsel">Remove selected</button>
          <button class="btn btn-danger btn-sm" data-a="rmall">Remove all</button></div>
        <div class="table-wrap"><table class="variants-table fit">
          <colgroup><col style="width:3%"><col style="width:27%"><col style="width:58%"><col style="width:12%"></colgroup>
          <thead><tr><th></th><th>Item</th><th>Changes</th><th></th></tr></thead><tbody>
          ${lines.length ? lines.map(([key, fs]) => {
            const f0 = fs[0];
            const left = FIELDS[f0.kind].filter(([n]) => n !== "mismatch" && !fs.some(x => x.field === n));
            return `<tr>
              <td><input type="checkbox" data-s="${esc(key)}" ${sel.has(key) ? "checked" : ""}></td>
              <td><div class="pair"><span title="${esc(f0.title)}">${esc(f0.title)}</span><span class="sub" title="${esc((f0.variant_title || "") + " · " + (f0.vendor || ""))}">${esc(f0.variant_title || "")} · ${esc(f0.vendor || "")}</span></div></td>
              <td style="white-space:normal">${fs.map(x => `
                <div style="display:flex;gap:6px;align-items:center;margin:2px 0">
                  <span class="badge badge-active" style="${BADGE}">${esc(lab(x.kind, x.field))}</span>
                  ${field(x.kind, x.field, x.value, `data-v="${esc(key)}" data-f="${x.field}"`)}
                  <button class="btn btn-ghost btn-sm" data-rf="${esc(key)}" data-f="${x.field}">✕</button></div>`).join("")}
                ${left.length ? `<div style="display:flex;gap:6px;margin-top:6px" data-add="${esc(key)}">
                  <select class="input" style="height:28px;max-width:140px">${left.map(([n, l]) => `<option value="${n}">${l}</option>`).join("")}</select>
                  <span class="addv" style="flex:1;display:flex;min-width:0">${field(f0.kind, left[0][0], "", "", "value")}</span>
                  <button class="btn btn-ghost btn-sm" data-a="add">Add</button></div>` : ""}</td>
              <td><button class="btn btn-ghost btn-sm" data-rl="${esc(key)}">Remove</button></td></tr>`;
          }).join("") : '<tr><td colspan="4" class="empty-cell">Queue is empty</td></tr>'}
          </tbody></table></div>
        <div class="rv-bar"><span class="muted">${sel.size} selected</span><div style="flex:1"></div>
          <button class="btn btn-primary" data-a="push">Push selected (${sel.size})</button></div></div>`;
      const root = this.c.querySelector("#mq");
      root.addEventListener("change", async e => {
        if (e.target.matches("[data-add] > select")) {
          const w = e.target.parentElement;
          w.querySelector(".addv").innerHTML = field(ref(w.dataset.add).kind, e.target.value, "", "", "value");
          return;
        }
        const d = e.target.dataset;
        if (d.s) { e.target.checked ? sel.add(d.s) : sel.delete(d.s); return draw(); }
        if (d.v) {
          const value = e.target.value.trim();
          if (!value) { Toast.error("Value required"); return load(); }
          await post("stage", { items: [{ ...ref(d.v), field: d.f, value }] });
        }
      });
      root.addEventListener("click", async e => {
        const b = e.target.closest("button");
        if (!b) return;
        const d = b.dataset;
        if (d.a === "back") return this.render(this.c);
        if (d.a === "all") { lines.forEach(([x]) => sel.add(x)); return draw(); }
        if (d.a === "none") { sel.clear(); return draw(); }
        if (d.a === "rmsel" || d.a === "rmall") {
          const ks = d.a === "rmall" ? lines.map(l => l[0]) : [...sel];
          if (!ks.length || !confirm(`Remove ${ks.length} lines?`)) return;
          await post("queue/remove", { items: ks.map(ref) });
          return load();
        }
        if (d.rl) { await post("queue/remove", { items: [ref(d.rl)] }); return load(); }
        if (d.rf) { await post("queue/remove", { items: [{ ...ref(d.rf), field: d.f }] }); return load(); }
        if (d.a === "add") {
          const w = b.closest("[data-add]");
          const value = w.querySelector(".addv").firstElementChild.value.trim();
          if (!value) return Toast.error("Enter a value");
          await post("stage", { items: [{ ...ref(w.dataset.add), field: w.querySelector("select").value, value }] });
          return load();
        }
        if (d.a === "push") {
          if (!sel.size) return Toast.info("Nothing selected");
          b.disabled = true;
          b.innerHTML = `<span class="spinner"></span>Pushing ${sel.size}…`;
          try {
            const r = await API.post("/api/missing/queue/push", { keys: [...sel] });
            if (r.dry_run) Toast.warning("Test mode: nothing written");
            else if (r.errors.length) Toast.warning(`Pushed ${r.pushed}; ${r.errors[0]}`);
            else Toast.success(`Pushed ${r.pushed}`);
          } catch (err) { Toast.error(err.message); }
          return load();
        }
      });
    };
    try { await load(); } catch (e) { Toast.error(e.message); }
  }
}