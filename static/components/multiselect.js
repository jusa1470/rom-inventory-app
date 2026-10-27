import { esc } from '../util.js';

function closeAll(except = null) {
  document.querySelectorAll('.ms-panel:not([hidden])').forEach(p => {
    if (p !== except) p.hidden = true;
  });
}

document.addEventListener('mousedown', e => {
  if (!e.target.closest('.ms-panel, .ms-btn')) closeAll();
});
window.addEventListener('scroll', e => {
  if (!(e.target.closest && e.target.closest('.ms-panel'))) closeAll();
}, true);
window.addEventListener('resize', () => closeAll());

/** Dropdown with searchable checkboxes. Calls onChange(selectedValues). */
export function createMultiSelect({ placeholder = 'All', options = [], onChange }) {
  const chosen = new Set();

  const root = document.createElement('div');
  root.className = 'ms';
  const btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'ms-btn';
  root.appendChild(btn);

  // The panel lives on <body> so table scroll containers can't clip it.
  const panel = document.createElement('div');
  panel.className = 'ms-panel';
  panel.hidden = true;
  panel.innerHTML = `
    <input class="input ms-search" placeholder="Search…">
    <div class="ms-list"></div>
    <button type="button" class="btn btn-ghost btn-sm ms-clear">Clear selection</button>`;
  document.body.appendChild(panel);

  const search = panel.querySelector('.ms-search');
  const list = panel.querySelector('.ms-list');

  function renderButton() {
    btn.textContent = chosen.size ? `${chosen.size} selected` : placeholder;
    btn.classList.toggle('active', chosen.size > 0);
  }

  function renderList() {
    const term = search.value.trim().toLowerCase();
    const shown = options.filter(o => o.toLowerCase().includes(term));
    list.innerHTML = shown.length
      ? shown.map(o => `
          <label class="ms-item">
            <input type="checkbox" value="${esc(o)}" ${chosen.has(o) ? 'checked' : ''}>
            <span>${esc(o)}</span>
          </label>`).join('')
      : '<div class="muted ms-empty">No matches</div>';
  }

  function reset() {
    chosen.clear();
    search.value = '';
    renderButton();
    renderList();
  }

  btn.addEventListener('click', () => {
    if (!panel.hidden) {
      panel.hidden = true;
      return;
    }
    closeAll(panel);
    const r = btn.getBoundingClientRect();
    panel.style.top = `${r.bottom + 4}px`;
    panel.style.left = `${Math.max(8, Math.min(r.left, window.innerWidth - 280))}px`;
    panel.hidden = false;
    search.focus();
  });
  search.addEventListener('input', renderList);
  list.addEventListener('change', e => {
    const cb = e.target;
    if (cb.checked) chosen.add(cb.value);
    else chosen.delete(cb.value);
    renderButton();
    onChange([...chosen]);
  });
  panel.querySelector('.ms-clear').addEventListener('click', () => {
    reset();
    onChange([]);
  });

  renderButton();
  renderList();
  return { el: root, clear: reset, destroy: () => panel.remove() };
}
