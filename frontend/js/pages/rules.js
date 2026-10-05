const RULE_COLS = [
  { id:'match_text',   label:'Match Text', sortKey:'match_text',  filterable:true, thStyle:'text-align:left' },
  { id:'match_type',   label:'Type',       sortKey:'match_type',  filterable:true,
    filterType:'select', options:['iexact','icontains','exact','contains','regex'] },
  { id:'action_type',  label:'Action',     sortKey:'action_type', filterable:true,
    filterType:'select', options:['drop','title_suffix','title_prefix','add_tag','description'] },
  { id:'action_value', label:'Value',      sortKey:null,          filterable:true, thStyle:'text-align:left' },
  { id:'priority',     label:'Priority',   sortKey:'priority',    filterable:false, thStyle:'text-align:center' },
  { id:'enabled',      label:'On',         sortKey:null,          filterable:false, thStyle:'text-align:center' },
  { id:'acts',         label:'',           sortKey:null,          filterable:false, thStyle:'text-align:center' },
];
const RULE_COL_W = { match_text:160, match_type:100, action_type:120, action_value:160, priority:60, enabled:60, acts:100 };

class RulesPage {
  constructor() { this.ruleSort = 'priority_desc'; this.ruleFilters = {}; }

  async render(container) {
    container.innerHTML = `
      <div class="page">
        <div class="page-title">Feature Rules</div>
        <p style="font-size:13px;color:var(--text-secondary);margin-bottom:20px;max-width:640px">
          Rules control how Webami product features (e.g. "Indie Exclusive", "Colored Vinyl") are
          applied when building Shopify titles and tags. Rules are matched in priority order (highest first).
          A feature can match multiple rules — all matching actions are applied.
        </p>

        <div class="row" style="margin-bottom:12px">
          <div class="section-label" style="margin:0;flex:1">Rules</div>
          <button class="btn btn-primary btn-sm" id="add-rule-btn">+ Add Rule</button>
        </div>

        <div class="table-wrap" style="margin-bottom:32px">
          <table id="rules-table">
<colgroup>${RULE_COLS.map(c=>`<col style="width:${RULE_COL_W[c.id]||80}px">`).join('')}</colgroup>
            <thead id="rules-thead"></thead>
            <tbody id="rules-body">
              <tr><td colspan="${RULE_COLS.length}" style="text-align:center;color:var(--text-muted);padding:24px">Loading…</td></tr>
            </tbody>
          </table>
        </div>

        <div class="row" style="margin-bottom:12px">
          <div class="section-label" style="margin:0;flex:1">Unknown Features</div>
          <span style="font-size:12px;color:var(--text-muted)">Features seen in Webami data with no matching rule</span>
        </div>
        <div id="unknown-list"></div>

        <div id="rule-form-area"></div>
      </div>`;

    await this._loadRules();
    await this._loadUnknown();

    document.getElementById('add-rule-btn').addEventListener('click', () =>
      this._openForm(null));
  }

async _loadRules() {
    const body  = document.getElementById('rules-body');
    const thead = document.getElementById('rules-thead');
    if (!body) return;
    if (thead) {
      buildSortableHead(thead, RULE_COLS, this.ruleSort, this.ruleFilters,
        s => { this.ruleSort = s; this._loadRules(); },
        (col, val) => { this.ruleFilters[col] = val; this._loadRules(); });
    }
    try {
      const qs = new URLSearchParams({
        sort:        this.ruleSort,
        q:           this.ruleFilters.match_text   || '',
        q_value:     this.ruleFilters.action_value || '',
        match_type:  this.ruleFilters.match_type   || '',
        action_type: this.ruleFilters.action_type  || '',
      });
      const data = await API.get(`/api/rules?${qs}`);
      if (!data.items?.length) {
        body.innerHTML = `<tr><td colspan="${RULE_COLS.length}" style="text-align:center;color:var(--text-muted);padding:24px">No rules yet</td></tr>`;
        return;
      }
      body.innerHTML = data.items.map(r => `
        <tr class="rule-row" style="opacity:${r.enabled ? 1 : 0.45}">
          <td><span class="mono" style="font-size:12px">${esc(r.match_text)}</span></td>
          <td><span class="badge badge-draft" style="font-size:11px">${esc(r.match_type)}</span></td>
          <td><span class="badge ${this._actionBadge(r.action_type)}" style="font-size:11px">${esc(r.action_type)}</span></td>
          <td class="cell-truncate" style="font-size:12px" title="${esc(r.action_value || '')}">${esc(r.action_value || '—')}</td>
          <td style="text-align:center">${r.priority}</td>
          <td style="text-align:center">
            <button class="btn btn-ghost btn-sm toggle-rule" data-id="${r.id}" data-enabled="${r.enabled}" title="${r.enabled ? 'Disable' : 'Enable'}">
              ${r.enabled ? '✓' : '○'}
            </button>
          </td>
          <td style="text-align:center">
            <button class="btn btn-ghost btn-sm edit-rule" data-id="${r.id}">Edit</button>
            <button class="btn btn-danger btn-sm del-rule" data-id="${r.id}" style="margin-left:4px">Del</button>
          </td>
        </tr>`).join('');

      body.querySelectorAll('.edit-rule').forEach(btn =>
        btn.addEventListener('click', () => this._openForm(data.items.find(r => r.id == btn.dataset.id))));
      body.querySelectorAll('.del-rule').forEach(btn =>
        btn.addEventListener('click', () => this._deleteRule(+btn.dataset.id)));
      body.querySelectorAll('.toggle-rule').forEach(btn =>
        btn.addEventListener('click', () => this._toggleRule(+btn.dataset.id, +btn.dataset.enabled === 0 ? 1 : 0)));
    } catch (e) {
      body.innerHTML = `<tr><td colspan="${RULE_COLS.length}" style="color:var(--red);padding:16px">${esc(e.message)}</td></tr>`;
    }
  }

  _actionBadge(action) {
    return {
      drop: 'badge-draft', title_suffix: 'badge-active', title_prefix: 'badge-active',
      add_tag: 'badge-new', description: 'badge-used',
    }[action] || 'badge-draft';
  }

  async _loadUnknown() {
    const el = document.getElementById('unknown-list');
    try {
      const data = await API.get('/api/rules/unknown');
      if (!data.items?.length) {
        el.innerHTML = '<div class="empty-state"><div class="empty-state-text">No unknown features 🎉</div></div>';
        return;
      }
      el.innerHTML = data.items.map(f => `
        <div class="pending-item">
          <div class="item-info">
            <div class="item-title"><span class="mono">${esc(f.feature_text)}</span></div>
            <div class="item-meta">Seen ${f.seen_count}× · last ${Fmt.date(f.last_seen)}</div>
          </div>
          <div class="row center" style="gap:6px">
            <button class="btn btn-primary btn-sm create-from-unknown" data-text="${esc(f.feature_text)}" data-id="${f.id}">
              Create Rule
            </button>
            <button class="btn btn-ghost btn-sm dismiss-unknown" data-id="${f.id}">Dismiss</button>
          </div>
        </div>`).join('');

      el.querySelectorAll('.create-from-unknown').forEach(btn =>
        btn.addEventListener('click', () => {
          this._openForm({ match_text: btn.dataset.text, match_type: 'iexact', action_type: 'drop', priority: 0 },
                         btn.dataset.id);
        }));
      el.querySelectorAll('.dismiss-unknown').forEach(btn =>
        btn.addEventListener('click', () => this._dismissUnknown(+btn.dataset.id)));

    } catch (e) {
      el.innerHTML = `<div class="alert alert-error">${esc(e.message)}</div>`;
    }
  }

  _openForm(rule, unknownId = null) {
    const isNew = !rule?.id;
    const bodyEl = document.createElement('div');
    bodyEl.innerHTML = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px">
        <div class="input-group" style="grid-column:1/-1">
          <label class="input-label">Match Text</label>
          <input id="rf-match-text" class="input" value="${esc(rule?.match_text || '')}">
        </div>
        <div class="input-group">
          <label class="input-label">Match Type</label>
          <select id="rf-match-type" class="select">
            ${['iexact','icontains','exact','contains','regex'].map(t =>
              `<option value="${t}" ${rule?.match_type === t ? 'selected' : ''}>${t}</option>`).join('')}
          </select>
        </div>
        <div class="input-group">
          <label class="input-label">Action</label>
          <select id="rf-action-type" class="select">
            ${['drop','title_suffix','title_prefix','add_tag','description'].map(a =>
              `<option value="${a}" ${rule?.action_type === a ? 'selected' : ''}>${a}</option>`).join('')}
          </select>
        </div>
        <div class="input-group">
          <label class="input-label">Action Value <span style="color:var(--text-muted)">(leave blank for "drop")</span></label>
          <input id="rf-action-value" class="input" value="${esc(rule?.action_value || '')}">
        </div>
        <div class="input-group">
          <label class="input-label">Priority <span style="color:var(--text-muted)">(higher = first)</span></label>
          <input id="rf-priority" class="input" type="number" value="${rule?.priority ?? 0}">
        </div>
        <div class="input-group" style="grid-column:1/-1">
          <label class="input-label">Notes (optional)</label>
          <input id="rf-notes" class="input" value="${esc(rule?.notes || '')}">
        </div>
      </div>`;

    Modal.open({
      title: isNew ? 'Add Rule' : 'Edit Rule',
      body:  bodyEl,
      buttons: [
        { label: 'Cancel', cls: 'btn-ghost', onClick: Modal.close },
        { label: isNew ? 'Create' : 'Save', cls: 'btn-primary', onClick: () => this._saveRule(rule?.id, unknownId) },
      ],
    });
  }

  async _saveRule(ruleId, unknownId) {
    const payload = {
      match_text:   document.getElementById('rf-match-text')?.value.trim(),
      match_type:   document.getElementById('rf-match-type')?.value,
      action_type:  document.getElementById('rf-action-type')?.value,
      action_value: document.getElementById('rf-action-value')?.value.trim() || null,
      priority:     parseInt(document.getElementById('rf-priority')?.value) || 0,
      notes:        document.getElementById('rf-notes')?.value.trim() || null,
      enabled:      1,
    };
    if (!payload.match_text) { Toast.warning('Match text required'); return; }
    try {
      if (ruleId) {
        await API.put(`/api/rules/${ruleId}`, payload);
      } else {
        await API.post('/api/rules', payload);
        if (unknownId) await API.post(`/api/rules/unknown/${unknownId}/resolve`);
      }
      Toast.success('Rule saved');
      Modal.close();
      await this._loadRules();
      await this._loadUnknown();
    } catch (e) { Toast.error(e.message); }
  }

  async _toggleRule(id, enabled) {
    try {
      const rules = (await API.get('/api/rules')).items;
      const rule  = rules.find(r => r.id === id);
      if (rule) await API.put(`/api/rules/${id}`, { ...rule, enabled });
      await this._loadRules();
    } catch (e) { Toast.error(e.message); }
  }

  async _deleteRule(id) {
    if (!confirm('Delete this rule?')) return;
    try {
      await API.delete(`/api/rules/${id}`);
      Toast.success('Rule deleted');
      await this._loadRules();
    } catch (e) { Toast.error(e.message); }
  }

  async _dismissUnknown(id) {
    try {
      await API.post(`/api/rules/unknown/${id}/resolve`);
      await this._loadUnknown();
    } catch (e) { Toast.error(e.message); }
  }
}
