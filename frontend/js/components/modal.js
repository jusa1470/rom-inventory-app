const Modal = (() => {
  let overlay, box, titleEl, bodyEl, footerEl;

  function init() {
    overlay = document.createElement('div');
    Object.assign(overlay.style, {
      position: 'fixed', inset: '0', background: 'rgba(0,0,0,0.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      zIndex: '8888', animation: 'fadeIn 0.15s ease',
    });
    box = document.createElement('div');
    Object.assign(box.style, {
      background: 'var(--bg-card)', border: '1px solid var(--border-light)',
      borderRadius: '12px', padding: '28px 32px', width: '520px', maxWidth: '95vw',
      maxHeight: '85vh', overflowY: 'auto', boxShadow: 'var(--shadow-lg)',
      display: 'flex', flexDirection: 'column', gap: '20px',
    });
    titleEl  = document.createElement('h2');
    Object.assign(titleEl.style, { margin: '0', fontSize: '20px', color: 'var(--text-primary)' });
    bodyEl   = document.createElement('div');
    footerEl = document.createElement('div');
    Object.assign(footerEl.style, { display: 'flex', gap: '8px', justifyContent: 'flex-end' });

    box.append(titleEl, bodyEl, footerEl);
    overlay.appendChild(box);
    overlay.addEventListener('click', e => { if (e.target === overlay) close(); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') close(); });
  }

  function open({ title, body, buttons = [], width }) {
    if (!overlay) init();
    box.style.width = width || '520px';
    titleEl.textContent = title || '';
    if (typeof body === 'string') {
      bodyEl.innerHTML = body;
    } else {
      bodyEl.innerHTML = '';
      bodyEl.appendChild(body);
    }
    footerEl.innerHTML = '';
    buttons.forEach(({ label, cls = 'btn-ghost', onClick }) => {
      const btn = document.createElement('button');
      btn.className = `btn ${cls}`;
      btn.textContent = label;
      btn.addEventListener('click', () => { onClick && onClick(); });
      footerEl.appendChild(btn);
    });
    document.body.appendChild(overlay);
  }

  function close() {
    overlay && overlay.remove();
  }

  function prompt({ title, label, placeholder = '', value = '' }) {
    return new Promise(resolve => {
      const input = document.createElement('input');
      input.className   = 'input';
      input.placeholder = placeholder;
      input.value       = value;
      setTimeout(() => input.focus(), 50);
      open({
        title,
        body: Object.assign(document.createElement('div'), {
          innerHTML: `<div class="input-group"><label class="input-label">${esc(label)}</label></div>`,
        }),
        buttons: [
          { label: 'Cancel', cls: 'btn-ghost', onClick: () => { close(); resolve(null); } },
          { label: 'OK',     cls: 'btn-primary', onClick: () => { close(); resolve(input.value.trim()); } },
        ],
      });
      bodyEl.querySelector('.input-group').appendChild(input);
      input.addEventListener('keydown', e => {
        if (e.key === 'Enter') { close(); resolve(input.value.trim()); }
      });
    });
  }

  return { open, close, prompt };
})();
