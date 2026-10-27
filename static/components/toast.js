let container = null;

function init() {
  container = document.createElement('div');
  container.className = 'toast-container';
  document.body.appendChild(container);
}

function show(message, type = 'info', duration = 3500) {
  if (!container) init();
  const el = document.createElement('div');
  el.className = `toast toast-${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => {
    el.style.transition = 'opacity 0.3s';
    el.style.opacity = '0';
    setTimeout(() => el.remove(), 300);
  }, duration);
}

export const Toast = {
  success: msg => show(msg, 'success'),
  error: msg => show(msg, 'error', 5000),
  info: msg => show(msg, 'info'),
  warning: msg => show(msg, 'warning', 5000),
};