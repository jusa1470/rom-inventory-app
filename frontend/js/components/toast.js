const Toast = (() => {
  let container;

  function init() {
    container = document.createElement('div');
    Object.assign(container.style, {
      position: 'fixed', bottom: '24px', right: '24px',
      display: 'flex', flexDirection: 'column', gap: '8px',
      zIndex: '9999', pointerEvents: 'none',
    });
    document.body.appendChild(container);
  }

  function show(message, type = 'info', duration = 3500) {
    if (!container) init();
    const colors = {
      success: { bg: 'rgba(140,198,48,0.12)', border: 'rgba(140,198,48,0.4)', color: 'var(--green)' },
      error:   { bg: 'rgba(226,59,68,0.12)',  border: 'rgba(226,59,68,0.4)',  color: '#f08080' },
      info:    { bg: 'rgba(0,113,188,0.12)',  border: 'rgba(0,113,188,0.4)',  color: '#60a8e0' },
      warning: { bg: 'rgba(241,90,36,0.12)',  border: 'rgba(241,90,36,0.4)',  color: 'var(--orange)' },
    };
    const c = colors[type] || colors.info;
    const el = document.createElement('div');
    Object.assign(el.style, {
      background: c.bg, border: `1px solid ${c.border}`, color: c.color,
      padding: '12px 16px', borderRadius: '8px', fontSize: '13px', fontWeight: '500',
      fontFamily: "'DM Sans', sans-serif", maxWidth: '360px', pointerEvents: 'all',
      animation: 'fadeIn 0.2s ease', boxShadow: '0 4px 20px rgba(0,0,0,0.4)',
      lineHeight: '1.4',
    });
    el.textContent = message;
    container.appendChild(el);
    setTimeout(() => {
      el.style.transition = 'opacity 0.3s';
      el.style.opacity = '0';
      setTimeout(() => el.remove(), 300);
    }, duration);
  }

  return {
    success: msg => show(msg, 'success'),
    error:   msg => show(msg, 'error', 5000),
    info:    msg => show(msg, 'info'),
    warning: msg => show(msg, 'warning'),
  };
})();
