import { API } from "../api.js";
import { Modal } from "../components/modal.js";
import { Toast } from "../components/toast.js";
import { buildPager, debounce, esc, Fmt, thumb, truncCell } from "../util.js";

const UPC_LEVEL = "variant";

export class MatchesPage {
  constructor() {
    this.page = 1;
    this.q = "";
    this.only = false;
    this._request = 0;
  }
  destroy() {}

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
    c.querySelector("#m-search").addEventListener(
      "input",
      debounce((e) => {
        this.q = e.target.value.trim();
        this.page = 1;
        this._load();
      }),
    );
    c.querySelector("#m-only").addEventListener("change", (e) => {
      this.only = e.target.checked;
      this.page = 1;
      this._load();
    });
    await this._load();
  }

  async _load() {
    const body = this.c.querySelector("#m-body");
    const req = ++this._request;
    body.innerHTML = `<tr><td colspan="7" class="empty-cell">
      <span class="spinner"></span> ${this.only ? "Calculating matches… (first load can take a while)" : "Loading…"}
    </td></tr>`;
    for (const id of ["#m-pager-top", "#m-pager-bottom"])
      this.c.querySelector(id).style.opacity = "0.4";
    try {
      const params = new URLSearchParams({ page: this.page });
      if (this.q) params.set("q", this.q);
      if (this.only) params.set("only_suggested", "true");
      const data = await API.get(`/api/matches?${params}`);
      if (req !== this._request || !body.isConnected) return;
      this.items = data.items;
      body.innerHTML = data.items.length
        ? data.items
            .map((p, i) => {
              const s = p.suggestions[0];
              const link =
                s && s.href
                  ? `<a href="https://webami.aent.com${esc(s.href)}" target="_blank" rel="noopener">WebAMI ↗</a>`
                  : "";
              const dash = '<span class="muted">—</span>';
              return `<tr>
                    <td><div style="display:flex;gap:8px">${thumb(p.image_url, p.title)}
                        <div class="pair"><span>${esc(p.title)}</span>
                            <span class="sub">${esc(p.variant_title || "")}</span>
                            ${p.siblings.length ? `<span class="sub">+${p.siblings.length} other variants</span>` : ""}</div></div></td>
                    <td><div style="display:flex;gap:8px">${thumb(s && s.image_url, s && s.title)}
                        <div class="pair"><span>${s ? esc(s.title) : "—"}</span>
                            <span class="sub">${s && s.kw_extra.length ? "extra: " + esc(s.kw_extra.join(", ")) : ""}</span>
                            ${s && s.used_by.length ? '<span class="badge badge-used">UPC already on a variant</span>' : ""}
                            ${s && s.orders.length ? `<span class="sub">ordered ${s.orders.length}×, last ${Fmt.date(s.orders[0].submitted_at)}</span>` : ""}</div></div></td>
                    <td><div class="pair"><span>${esc(p.vendor || "—")}</span>
                        <span class="sub side">${s ? esc(s.artist || "—") : "—"}</span></div></td>
                    <td><div class="pair"><span>${esc(p.type || p.product_type || "—")}</span>
                        <span class="sub side">${s ? esc(s.product_type || "—") : "—"}</span></div></td>
                    <td><div class="pair"><span>${p.cost != null ? Fmt.price(p.cost) : "—"}</span>
                        <span class="sub side">${s && s.price != null ? Fmt.price(s.price) : "—"}</span></div></td>
                    <td><div class="pair"><span class="mono">${esc(s ? s.upc : "—")}</span>
                        <span class="sub">${link}</span></div></td>
                    <td>
                        <button class="btn btn-primary btn-sm" data-m="${i}" ${s ? "" : "disabled"}>Match</button>
                        <button class="btn btn-ghost btn-sm" data-n="${i}">No match</button>
                    </td></tr>`;
            })
            .join("")
        : '<tr><td colspan="7" class="empty-cell">Nothing to review</td></tr>';
      body
        .querySelectorAll("[data-m]")
        .forEach((b) =>
          b.addEventListener("click", () =>
            this._match(this.items[+b.dataset.m]),
          ),
        );
      body
        .querySelectorAll("[data-n]")
        .forEach((b) =>
          b.addEventListener("click", () =>
            this._noMatch(this.items[+b.dataset.n]),
          ),
        );
      for (const id of ["#m-pager-top", "#m-pager-bottom"]) {
        buildPager(this.c.querySelector(id), data, (p) => {
          this.page = p;
          this._load();
        });
      }
      for (const id of ["#m-pager-top", "#m-pager-bottom"])
        this.c.querySelector(id).style.opacity = "";
    } catch (e) {
      for (const id of ["#m-pager-top", "#m-pager-bottom"])
        this.c.querySelector(id).style.opacity = "";
      if (req === this._request && body.isConnected)
        body.innerHTML = `<tr><td colspan="7" class="empty-cell">${esc(e.message)}</td></tr>`;
    }
  }

  async _save(p, upc, title, vtitle) {
    const product = {},
      variants = [];
    const v = { id: p.variant_id, upc };
    if (vtitle && vtitle !== p.variant_title) v.title = vtitle;
    variants.push(v);
    if (title && title !== p.title) product.title = title;
    try {
      const res = await API.put(
        `/api/products/${encodeURIComponent(p.product_id)}`,
        { product, variants },
      );
      Modal.close();
      res.dry_run
        ? Toast.warning("Test mode: nothing written")
        : Toast.success("Saved to Shopify");
      this._load();
    } catch (e) {
      Toast.error(e.message);
    }
  }

  _match(p, cands = p.suggestions) {
    const body = document.createElement("div");
    body.innerHTML = `
            <div style="display:flex;gap:12px;align-items:center">
                ${p.image_url ? `<img src="${esc(p.image_url)}" style="width:96px;height:96px;object-fit:cover;border-radius:4px">` : ""}
                <div><div>${esc(p.title)} — ${esc(p.vendor || "")}</div>
                    <div class="muted">${esc(p.variant_title || "")} · cost ${p.cost != null ? Fmt.price(p.cost) : "—"}</div>
                    ${
                      p.siblings.length
                        ? `<div class="muted" style="margin-top:6px">Other variants of this product: ${p.siblings
                            .map((s) =>
                              esc(
                                `${s.title}${s.upc ? " (" + s.upc + ")" : ""}`,
                              ),
                            )
                            .join(" · ")}</div>`
                        : ""
                    }
                </div>
            </div>
            <div class="table-wrap" style="margin-top:12px"><table class="variants-table">
            <thead><tr><th></th><th></th><th>Source</th><th>Title</th><th>Artist</th><th>Format</th><th class="num">Price</th><th>UPC</th><th>Link</th><th>Matched / Orders</th></tr></thead>
            <tbody>${cands
              .map(
                (c, i) => `<tr>
              <td><input type="radio" name="cand" value="${i}" ${i === 0 ? "checked" : ""}></td>
              <td>${c.image_url ? `<img src="${esc(c.image_url)}" style="width:72px;height:72px;object-fit:cover;border-radius:4px">` : ''}</td>
              <td>${esc(c.source)}${c.artist_match ? "" : " (artist differs)"}${c.kw_extra && c.kw_extra.length ? " · extra: " + esc(c.kw_extra.join(", ")) : ""}</td>
              <td>${truncCell(c.title)}</td><td>${truncCell(c.artist)}</td>
              <td>${esc(c.product_type || "—")}</td>
              <td class="num">${c.price != null ? Fmt.price(c.price) : "—"}</td>
              <td class="mono">${esc(c.upc)}</td>
              <td>${c.href ? `<a href="https://webami.aent.com${esc(c.href)}" target="_blank" rel="noopener">↗</a>` : ""}</td>
              <td>${c.used_by && c.used_by.length
                ? c.used_by.map(u => `<div class="badge badge-used">on ${esc(u.title)} — ${esc(u.variant_title || '')}</div>`).join('')
                : '<span class="muted">not used</span>'}
              ${(c.orders || []).map(o => `<div class="muted">order ${esc(o.number)} · ${Fmt.date(o.submitted_at)} · qty ${o.quantity}</div>`).join('')}</td></tr>`,
              )
              .join("")}
            </tbody></table></div>
          <div class="form-grid" style="margin-top:12px">
            <div class="input-group"><label class="input-label">Product title</label>
              <input class="input" name="title"></div>
            <div class="input-group"><label class="input-label">Edition</label>
              <input class="input" name="edition"></div>
            <div class="input-group"><label class="input-label">Color</label>
              <input class="input" name="color"></div>
            <div class="input-group"><label class="input-label">Attributes</label>
              <input class="input" name="attributes"></div>
            <div class="input-group"><label class="input-label">Variant title</label>
              <input class="input" name="vtitle" readonly></div>
          </div>
          <label class="check-row"><input type="checkbox" name="upd"><span>Update product and variant titles</span></label>`;
    const f = (n) => body.querySelector(`[name=${n}]`);
    const vt = () => {
      const none = (s) => !s || s.toLowerCase() === "none";
      const color = f("color").value.trim(),
        attrs = f("attributes").value.trim();
      return [
        f("edition").value.trim() || "Standard",
        none(color) ? null : color,
        none(attrs) ? null : attrs,
      ]
        .filter(Boolean)
        .join(" | ");
    };
    const sync = () => {
      f("vtitle").value = vt();
      f("upd").checked =
        f("title").value.trim() !== p.title ||
        f("vtitle").value !== p.variant_title;
    };
    const pick = () => {
      const s =
        cands[+body.querySelector("[name=cand]:checked").value].suggested;
      f("title").value = s.title;
      f("edition").value = s.edition;
      f("color").value = s.color;
      f("attributes").value = s.attributes;
      sync();
    };
    body
      .querySelectorAll("[name=cand]")
      .forEach((r) => r.addEventListener("change", pick));
    ["title", "edition", "color", "attributes"].forEach((n) =>
      f(n).addEventListener("input", sync),
    );
    pick();
    Modal.open({
      title: "Confirm match",
      body,
      width: "96vw",
      buttons: [
        {
          label: "Confirm",
          cls: "btn-primary",
          onClick: () => {
            const c = cands[+body.querySelector("[name=cand]:checked").value];
            const upd = f("upd").checked;
            this._save(
              p,
              c.upc,
              upd ? f("title").value.trim() : null,
              upd ? f("vtitle").value : null,
            );
          },
        },
        { label: "Cancel", onClick: Modal.close },
      ],
    });
  }

  _noMatch(p) {
    const body = document.createElement("div");
    body.innerHTML = `
            <div class="muted">${esc(p.title)} — ${esc(p.vendor || "")}</div>
            <div class="form-grid" style="margin-top:12px">
                <div class="input-group"><label class="input-label">UPC</label>
                <input class="input" name="upc"></div>
                <div class="input-group"><label class="input-label">Title</label>
                <input class="input" name="title" value="${esc(p.title)}"></div>
            </div>`;
    Modal.open({
      title: "No match",
      body,
      width: "700px",
      buttons: [
        {
          label: "Save manual",
          cls: "btn-primary",
          onClick: () => {
            const upc = body.querySelector("[name=upc]").value.trim();
            if (!upc) return Toast.error("UPC required");
            this._save(p, upc, body.querySelector("[name=title]").value.trim());
          },
        },
        {
          label: "Search WebAMI",
          onClick: async () => {
            try {
              const { items } = await API.get(
                `/api/products/${encodeURIComponent(p.product_id)}/webami-suggestions?search=true&variant_id=${encodeURIComponent(p.variant_id)}`,
              );
              items.length
                ? this._match(p, items)
                : Toast.info("No search results");
            } catch (e) {
              Toast.error(e.message);
            }
          },
        },
        {
          label: "Ignore",
          onClick: async () => {
            await API.post(
              `/api/matches/${encodeURIComponent(p.variant_id)}/ignore`,
            );
            Modal.close();
            this._load();
          },
        },
        { label: "Cancel", onClick: Modal.close },
      ],
    });
  }
}
