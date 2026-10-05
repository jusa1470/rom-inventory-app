class LoginPage {
  constructor(isSetup = false) {
    this.isSetup = isSetup;
  }

  async render(container) {
    container.innerHTML = this.isSetup ? this._setupHTML() : this._loginHTML();
    if (this.isSetup) this._bindSetup(container);
    else               this._bindLogin(container);
  }

  _loginHTML() {
    return `
      <div class="connect-page">
        <div class="connect-box">
          <div class="vinyl-ring"></div>
          <div class="connect-logo">VINYL<span>SYNC</span></div>
          <div class="connect-subtitle">Inventory Management</div>
          <div class="connect-form" id="login-form">
            <div class="input-group">
              <label class="input-label">Password</label>
              <input id="pw-input" class="input" type="password" placeholder="Enter password" autocomplete="current-password">
            </div>
            <div id="login-error" style="display:none" class="alert alert-error"></div>
            <button id="login-btn" class="btn btn-primary btn-lg" style="width:100%">
              Unlock
            </button>
          </div>
        </div>
      </div>`;
  }

  _setupHTML() {
    return `
      <div class="connect-page">
        <div class="connect-box" style="width:560px">
          <div class="vinyl-ring"></div>
          <div class="connect-logo">VINYL<span>SYNC</span></div>
          <div class="connect-subtitle">First-time Setup</div>
          <div class="connect-form">
            <div class="section-label">App Password</div>
            <div class="input-group">
              <label class="input-label">Password (min 6 chars)</label>
              <input id="s-pw" class="input" type="password" placeholder="Choose a password">
            </div>

            <div class="section-label" style="margin-top:8px">Shopify</div>
            <div class="input-group">
              <label class="input-label">Store (e.g. mystore.myshopify.com)</label>
              <input id="s-store" class="input" placeholder="mystore.myshopify.com">
            </div>
            <div class="input-group">
              <label class="input-label">Admin API Token</label>
              <input id="s-token" class="input" type="password" placeholder="shpat_...">
            </div>

            <div class="section-label" style="margin-top:8px">Webami</div>
            <div class="input-group">
              <label class="input-label">Base URL</label>
              <input id="s-wurl" class="input" value="https://aent-m.com">
            </div>
            <div class="input-group">
              <label class="input-label">Username / Email</label>
              <input id="s-wuser" class="input" placeholder="email@example.com">
            </div>
            <div class="input-group">
              <label class="input-label">Password</label>
              <input id="s-wpw" class="input" type="password">
            </div>

            <div id="setup-error" style="display:none" class="alert alert-error"></div>
            <button id="setup-btn" class="btn btn-primary btn-lg" style="width:100%;margin-top:4px">
              Create & Login
            </button>
          </div>
        </div>
      </div>`;
  }

  _bindLogin(container) {
    const input = container.querySelector('#pw-input');
    const btn   = container.querySelector('#login-btn');
    const err   = container.querySelector('#login-error');

    const submit = async () => {
      const pw = input.value.trim();
      if (!pw) return;
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span> Unlocking…';
      err.style.display = 'none';
      try {
        await API.post('/api/auth/login', { password: pw });
        App.onAuthenticated();
      } catch (e) {
        err.textContent = e.message;
        err.style.display = 'flex';
        btn.disabled = false;
        btn.textContent = 'Unlock';
        input.focus();
      }
    };

    btn.addEventListener('click', submit);
    input.addEventListener('keydown', e => { if (e.key === 'Enter') submit(); });
    setTimeout(() => input.focus(), 100);
  }

  _bindSetup(container) {
    const btn = container.querySelector('#setup-btn');
    const err = container.querySelector('#setup-error');

    btn.addEventListener('click', async () => {
      const pw    = container.querySelector('#s-pw').value.trim();
      const store = container.querySelector('#s-store').value.trim();
      const token = container.querySelector('#s-token').value.trim();
      const wurl  = container.querySelector('#s-wurl').value.trim();
      const wuser = container.querySelector('#s-wuser').value.trim();
      const wpw   = container.querySelector('#s-wpw').value.trim();

      err.style.display = 'none';
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner"></span> Setting up…';

      try {
        await API.post('/api/auth/setup', {
          password: pw, shopify_store: store, shopify_token: token,
          webami_base_url: wurl, webami_username: wuser, webami_password: wpw,
        });
        await API.post('/api/auth/login', { password: pw });
        App.onAuthenticated();
      } catch (e) {
        err.textContent = e.message;
        err.style.display = 'flex';
        btn.disabled = false;
        btn.textContent = 'Create & Login';
      }
    });
  }
}
