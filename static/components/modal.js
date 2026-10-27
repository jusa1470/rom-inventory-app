let overlay = null;
let box;
let titleEl;
let bodyEl;
let footerEl;

function init() {
  overlay = document.createElement('div');
  overlay.className = 'modal-overlay';
  box = document.createElement('div');
  box.className = 'modal-box';
  titleEl = document.createElement('h2');
  bodyEl = document.createElement('div');
  footerEl = document.createElement('div');
  footerEl.className = 'modal-footer';
  box.append(titleEl, bodyEl, footerEl);
  overlay.appendChild(box);
  overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
  document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
}

function open({ title = '', body, buttons = [], width = '520px' }) {
  if (!overlay) init();
  box.style.width = width;
  titleEl.textContent = title;
  bodyEl.replaceChildren();
  if (typeof body === 'string') bodyEl.innerHTML = body;
  else bodyEl.appendChild(body);
  footerEl.replaceChildren();
  buttons.forEach(({ label, cls = 'btn-ghost', onClick }) => {
    const btn = document.createElement('button');
    btn.className = `btn ${cls}`;
    btn.textContent = label;
    btn.addEventListener('click', () => { if (onClick) onClick(); });
    footerEl.appendChild(btn);
  });
  document.body.appendChild(overlay);
}

function close() {
  if (overlay) overlay.remove();
}

export const Modal = { open, close };