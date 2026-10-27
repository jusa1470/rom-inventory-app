import { API } from '../api.js';
import { el } from '../util.js';

export function renderLogin(root, onSuccess) {
  const box = el(`
    <div class="login">
      <form class="login-box">
        <h1>Record<span>Sync</span></h1>
        <input class="input" type="password" name="pw" placeholder="Password" autofocus>
        <div class="err"></div>
        <button class="btn btn-primary">Unlock</button>
      </form>
    </div>`);
  const form = box.querySelector('form');
  form.addEventListener('submit', async e => {
    e.preventDefault();
    try {
      await API.post('/api/login', { password: form.pw.value });
      onSuccess();
    } catch (err) {
      box.querySelector('.err').textContent = err.message;
      form.pw.value = '';
    }
  });
  root.replaceChildren(box);
}