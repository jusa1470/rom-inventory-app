const root = document.getElementById('root');

async function api(path, opts = {}) {
  const res = await fetch('/api' + path, {
    method: opts.method || 'GET',
    headers: { 'Content-Type': 'application/json' },
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw Object.assign(new Error(e.detail || res.statusText), { status: res.status });
  }
  return res.json();
}

function el(html) {
  const t = document.createElement('template');
  t.innerHTML = html.trim();
  return t.content.firstChild;
}

function renderLogin() {
  const box = el(`<div class="center"><form class="box">
    <h1>Record<span>Sync</span></h1>
    <input type="password" name="pw" placeholder="Password" autofocus/>
    <div class="err"></div>
    <button>Unlock</button></form></div>`);
  box.querySelector('form').addEventListener('submit', async (e) => {
    e.preventDefault();
    try {
      await api('/login', { method: 'POST', body: { password: e.target.pw.value } });
      renderApp();
    } catch (err) {
      box.querySelector('.err').textContent = err.message;
      e.target.pw.value = '';
    }
  });
  root.replaceChildren(box);
}

function renderApp() {
  const shell = el(`<div><nav><strong>RecordSync</strong><span class="sp"></span>
    <button id="lock">Lock</button></nav><main>Unlocked.</main></div>`);
  shell.querySelector('#lock').onclick = async () => { await api('/logout', { method: 'POST' }); renderLogin(); };
  root.replaceChildren(shell);
}

api('/me').then(renderApp).catch(renderLogin);
