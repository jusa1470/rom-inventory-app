// core.js
import { api } from './api.js';
import { h, showToast } from './utils.js';

// ── State ─────────────────────────────────────────────────────────────────────
export const SESSION_KEY = 'rs_authed';

export const App = {
  authed: sessionStorage.getItem(SESSION_KEY) === '1',
  page: sessionStorage.getItem(SESSION_KEY) === '1' ? 'dashboard' : 'lock',
  syncStatus: {},
  running: null,
  _lastResultAcked: null,
  _pollTimer: null,
  toast: null,
  _toastTimer: null,
};

// ── Router ─────────────────────────────────────────────────────────────────────
export function navigate(page) {
  if (!App.authed && page !== 'lock') { showToast('Please unlock the app first.', 'warning'); return; }
  App.page = page;
  // @ts-ignore
  window.render();
}

// ── Polling ────────────────────────────────────────────────
function appendLogLine(el, msg, level='INFO', color='var(--text-secondary)') {
  const now = new Date();
  const date = now.toLocaleDateString('en-CA');
  const time = now.toLocaleTimeString('en-GB', { hour12: false });
  const ms   = String(now.getMilliseconds()).padStart(3, '0');
  const line = document.createElement('div');
  line.style.color = color;
  line.textContent = `${date} ${time},${ms} [${level}] ui — ${msg}`;
  if (el.textContent === 'Sync log will appear here…') el.textContent = '';
  el.appendChild(line);
  el.scrollTop = el.scrollHeight;
}

async function pollRunning() {
  if (!App.authed) return;
  try {
    const res = await api.syncRunning();
    const was = App.running;
    App.running = res.running;
    if (was !== App.running) renderActivePageBanner();

    const r = res.last_result;
    if (r && !App._lastResultAcked) {
      App._lastResultAcked = r.at;
      if (!was) {
        const logEl = document.querySelector('#sync-activity-log');
        if (logEl) {
          const color = r.status === 'completed' ? 'var(--green)'
                      : r.status === 'cancelled' ? 'var(--orange)'
                      : 'var(--red)';
          const level = r.status === 'failed' ? 'ERROR' : r.status === 'cancelled' ? 'WARN' : 'INFO';
          const detail = r.detail ? ` — ${r.detail}` : '';
          const counts = Object.entries(r.counts || {}).map(([k,v]) => `${k}: ${v}`).join(', ');
          const summary = counts ? ` (${counts})` : '';
          appendLogLine(logEl, `${r.label} ${r.status}${summary}${detail}`, level, color);
        }
        if (r.status === 'failed') showToast(`${r.label} failed${r.detail ? ': ' + r.detail : ''}`, 'error');
      }
      fetch('/api/sync/ack-result', { method: 'POST' }).catch(() => {});
    } else if (!r) {
      App._lastResultAcked = null;
    }
  } catch {}
}

export function startPolling() {
  if (App._pollTimer) return;
  App._pollTimer = setInterval(pollRunning, 2500);
  pollRunning();
}

export function stopPolling() {
  clearInterval(App._pollTimer);
  App._pollTimer = null;
}

// ── Banner ────────────────────────────────────────────────
export function updateRunningBanner(el) {
  if (App.running) {
    el.style.display = '';
    el.querySelector('.banner-label').textContent = App.running;
  } else {
    el.style.display = 'none';
    el.querySelector('.banner-label').textContent = '';
  }
  document.querySelectorAll('.sync-trigger').forEach(b => {
    /** @type {HTMLButtonElement} */ (b).disabled = !!App.running;
    });
}

export function renderActivePageBanner() {
  const banner = document.getElementById('running-banner');
  if (banner) updateRunningBanner(banner);
}
export function makeSyncBanner() {
  const el = h('div', {
    id: 'running-banner',
    class: 'alert alert-info',
    style: 'display:none;margin-bottom:20px;align-items:center;gap:12px;',
  },
    h('span', { class: 'spinner', style: 'border-top-color:var(--blue);border-color:rgba(0,113,188,0.3);border-top-color:#60a8e0;flex-shrink:0;' }),
    h('span', { style: 'flex:1;' },
      'Sync in progress: ',
      h('span', { class: 'banner-label', style: 'font-weight:600;' }, App.running || ''),
    ),
    h('button', {
      class: 'btn btn-danger btn-sm',
      style: 'flex-shrink:0;',
      onClick: async (e) => {
        e.currentTarget.disabled = true;
        e.currentTarget.textContent = 'Cancelling…';
        try { await fetch('/api/sync/cancel', { method: 'POST' }); } catch {}
      },
    }, 'Cancel'),
  );
  updateRunningBanner(el);
  return el;
}

// ── Misc ──────────────────────────────────────────────────
export async function loadSyncStatus() {
  try { App.syncStatus = await api.syncStatus(); } catch {}
}