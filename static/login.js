'use strict';
/* Sign-in: password, magic link, phone code, Google, sign-up, 2FA. */

const state = { mode: 'password', meta: null, challenge: null, phone: '', signup: null };

const $ = (sel, root = document) => root.querySelector(sel);

function toast(message, kind = '') {
  const box = document.createElement('div');
  box.className = 'toast ' + kind;
  box.textContent = message;
  $('#toast').appendChild(box);
  setTimeout(() => box.remove(), kind === 'error' ? 6500 : 4000);
}

async function post(path, body) {
  let res;
  try {
    res = await fetch(path, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body || {}),
    });
  } catch {
    // No server listening: say so instead of blaming the password.
    throw new Error('Cannot reach the server. Is the app running?');
  }
  const text = await res.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = { message: text }; }
  if (!res.ok || data.ok === false) {
    const err = new Error(data.message || 'That did not work. Try again.');
    err.code = data.code;
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

function body(html) { $('#authBody').innerHTML = html; }

const FORMS = {
  password: `
    <form class="auth-form" data-form="password">
      <label class="field">Email<input name="email" type="email" autocomplete="username" required placeholder="you@business.my"></label>
      <label class="field">Password<input name="password" type="password" autocomplete="current-password" required placeholder="Your password"></label>
      <button class="btn" type="submit">Sign in</button>
      <button class="btn link" type="button" data-action="forgot">Forgot your password?</button>
    </form>`,
  magic: `
    <form class="auth-form" data-form="magic">
      <div class="hint">We email you a link that works once, for 15 minutes.</div>
      <label class="field">Email<input name="email" type="email" autocomplete="username" required placeholder="you@business.my"></label>
      <button class="btn" type="submit">Email me a link</button>
    </form>`,
  phone: `
    <form class="auth-form" data-form="phone">
      <label class="field">Phone number<input name="phone" type="tel" required placeholder="+60123456789"></label>
      <button class="btn" type="submit">Send me a code</button>
      <div class="hint">Standard SMS rates may apply. The code works once, for 5 minutes.</div>
    </form>`,
  signup: `
    <form class="auth-form" data-form="signup">
      <label class="field">Business name<input name="business_name" type="text" required placeholder="Kuih Lapis Aminah"></label>
      <label class="field">Your name<input name="full_name" type="text" required placeholder="Aminah binti Ali"></label>
      <label class="field">Email<input name="email" type="email" autocomplete="username" required placeholder="you@business.my"></label>
      <label class="field">Phone (optional)<input name="phone" type="tel" placeholder="+60123456789"></label>
      <label class="field">Password<input name="password" type="password" autocomplete="new-password" required minlength="10" placeholder="At least 10 characters"></label>
      <label class="row small" style="align-items:flex-start;gap:8px">
        <input name="accept_terms" type="checkbox" required style="width:auto;margin-top:3px">
        <span>I accept the <a href="#" data-action="terms">terms of service</a> and the privacy notice.</span>
      </label>
      <button class="btn" type="submit">Create my account</button>
    </form>`,
};

function showMode(mode) {
  state.mode = mode;
  document.querySelectorAll('#authTabs button').forEach(b =>
    b.classList.toggle('active', b.dataset.mode === mode));
  const titles = {
    password: ['Welcome back', 'Sign in to your business.'],
    magic: ['Sign in by email', 'No password to remember.'],
    phone: ['Sign in by phone', 'A one-time code by SMS.'],
    signup: ['Start with NIVORA', 'One business, one owner, five minutes.'],
  };
  $('#authTitle').textContent = titles[mode][0];
  $('#authSub').textContent = titles[mode][1];
  body(FORMS[mode]);
}

function showRoles() {
  const gate = $('#roleGate');
  const shell = $('#authShell');
  if (!gate || !shell) return;
  gate.hidden = false;
  shell.hidden = true;
  const saved = localStorage.getItem('nivora_shop');
  const box = $('#buyerBox');
  if (box) box.hidden = true;
  if (saved) {
    const input = $('#buyerSlug');
    if (input) input.value = saved;
  }
}

function showSeller() {
  $('#roleGate').hidden = true;
  $('#authShell').hidden = false;
  showMode('password');
}

function openShop() {
  const raw = ($('#buyerSlug') || {}).value || '';
  let slug = raw.trim();
  const match = slug.match(/[?&]b=([A-Za-z0-9_\-]+)/);
  if (match) slug = match[1];
  slug = slug.replace(/^.*\/shop\/?/, '').replace(/[^A-Za-z0-9_\-]/g, '');
  if (!slug) { toast('Enter the shop code your seller gave you.', 'error'); return; }
  location.href = '/shop?b=' + encodeURIComponent(slug);
}

function showTotp() {
  $('#authTitle').textContent = 'Two-factor code';
  $('#authSub').textContent = 'Owners must pass two-factor sign-in.';
  body(`
    <form class="auth-form" data-form="totp">
      <label class="field">6-digit code<input name="code" type="text" inputmode="numeric"
        autocomplete="one-time-code" maxlength="6" required placeholder="123456"></label>
      <button class="btn" type="submit">Verify and sign in</button>
      <button class="btn link" type="button" data-action="restart">Start again</button>
    </form>`);
}

function showTotpSetup(secret, uri, email, devLink) {
  $('#authTitle').textContent = 'Save your two-factor secret';
  $('#authSub').textContent = 'You need this at every sign-in. It is shown once.';
  body(`
    <div class="auth-form">
      <div class="hint">Add this to Google Authenticator, 1Password or Authy: choose “enter a setup key”, then paste it.</div>
      <div class="secret-box" id="secretText">${secret}</div>
      <div class="row"><button class="btn ghost small" type="button" data-action="copy-secret" data-secret="${secret}">Copy secret</button>
        <span class="small muted">Account: ${email}</span></div>
      <div class="hint mono" style="word-break:break-all">${uri}</div>
      <div class="divider"></div>
      ${devLink ? `<div class="warnbox small">Development: no email provider is configured, so here is your
        verification link.<br><a class="btn small" style="margin-top:8px" href="${devLink}">Verify my email</a></div>` : ''}
      <div class="infobox small">Open the verification link we sent you, then sign in with your password and a 6-digit code.</div>
      <button class="btn" type="button" data-action="go-signin">I have saved it</button>
    </div>`);
}

async function afterSignIn(data) {
  if (data.stage === 'totp') {
    state.challenge = data.challenge;
    showTotp();
    toast('Enter the code from your authenticator app.');
    return;
  }
  if (data.stage === 'signed_in' || data.ok) {
    location.href = '/';
    return;
  }
  toast('Signed in.');
  location.href = '/';
}

const handlers = {
  password: async (form) => {
    const data = new FormData(form);
    await afterSignIn(await post('/api/auth/password', {
      email: data.get('email'), password: data.get('password'),
    }));
  },
  magic: async (form) => {
    const data = new FormData(form);
    const result = await post('/api/auth/magic/request', { email: data.get('email') });
    body(`<div class="auth-form">
      <div class="infobox">If that email has an account, the link is on its way. It works once, for 15 minutes.</div>
      ${result.dev_link ? `<div class="warnbox small">Development: no email provider is configured.
        <br><a class="btn small" style="margin-top:8px" href="${result.dev_link}">Open my sign-in link</a></div>` : ''}
      ${state.meta && state.meta.dev_mode
        ? '<div class="hint">The link is also written to <b>data/outbox.log</b> on the server.</div>'
        : ''}
      <button class="btn ghost" type="button" data-action="restart">Back</button></div>`);
  },
  phone: async (form) => {
    const data = new FormData(form);
    state.phone = String(data.get('phone') || '');
    const result = await post('/api/auth/phone/request', { phone: state.phone });
    $('#authTitle').textContent = 'Enter the code';
    $('#authSub').textContent = 'Six digits, sent by SMS.';
    body(`
      <form class="auth-form" data-form="phone-verify">
        ${result.dev_code ? `<div class="warnbox small">Development: no SMS provider is configured. Your code is
          <b class="mono" style="font-size:16px">${result.dev_code}</b></div>` : ''}
        <label class="field">Code<input name="code" type="text" inputmode="numeric" maxlength="6"
          autocomplete="one-time-code" required placeholder="123456"></label>
        <button class="btn" type="submit">Verify</button>
        <button class="btn link" type="button" data-action="restart">Use another way</button>
      </form>`);
    if (state.meta && state.meta.dev_mode && !result.dev_code) {
      toast('Development: the SMS code is written to data/outbox.log.');
    }
  },
  'phone-verify': async (form) => {
    const data = new FormData(form);
    await afterSignIn(await post('/api/auth/phone/verify', {
      phone: state.phone, code: data.get('code'),
    }));
  },
  signup: async (form) => {
    const data = new FormData(form);
    const result = await post('/api/auth/signup', {
      business_name: data.get('business_name'),
      full_name: data.get('full_name'),
      email: data.get('email'),
      phone: data.get('phone') || null,
      password: data.get('password'),
      accept_terms: data.get('accept_terms') === 'on',
    });
    state.signup = result;
    showTotpSetup(result.totp_secret, result.otpauth_uri, data.get('email'), result.dev_link);
  },
  totp: async (form) => {
    const data = new FormData(form);
    const result = await post('/api/auth/totp', {
      challenge: state.challenge, code: data.get('code'),
    });
    await afterSignIn(result);
  },
};

document.addEventListener('submit', async (event) => {
  const form = event.target.closest('form[data-form]');
  if (!form) return;
  event.preventDefault();
  const handler = handlers[form.dataset.form];
  if (!handler) return;
  const button = form.querySelector('button[type=submit]');
  if (button) { button.disabled = true; button.dataset.label = button.textContent; button.textContent = 'Working…'; }
  try {
    await handler(form);
  } catch (err) {
    toast(err.message, 'error');
  } finally {
    if (button) { button.disabled = false; button.textContent = button.dataset.label || 'Continue'; }
  }
});

document.addEventListener('click', async (event) => {
  const target = event.target.closest('[data-mode], [data-action], [data-role]');
  if (!target) return;
  if (target.dataset.role === 'seller') { showSeller(); return; }
  if (target.dataset.role === 'buyer') {
    const saved = localStorage.getItem('nivora_shop');
    if (saved) { location.href = '/shop?b=' + encodeURIComponent(saved); return; }
    $('#buyerBox').hidden = false;
    $('#buyerSlug').focus();
    return;
  }
  if (target.dataset.mode) { showMode(target.dataset.mode); return; }
  const action = target.dataset.action;
  if (action === 'open-shop') { openShop(); return; }
  if (action === 'back-roles') { showRoles(); return; }
  if (action === 'restart') { showMode(state.mode); }
  if (action === 'forgot') {
    showMode('magic');
    toast('Enter your email and we send a reset link.');
    body(`
      <form class="auth-form" data-form="reset-request">
        <div class="hint">We email a link to choose a new password. It works once, for 30 minutes.</div>
        <label class="field">Email<input name="email" type="email" required placeholder="you@business.my"></label>
        <button class="btn" type="submit">Send the reset link</button>
      </form>`);
  }
  if (action === 'terms') {
    event.preventDefault();
    alert('NIVORA terms of service (version ' + (state.meta ? state.meta.terms_version : '') + ').\n\n'
      + 'Use the service lawfully, keep your sign-in details private, and only upload data you have the right to use.\n'
      + 'The service is provided as is, with support at support@nivora.app.');
  }
  if (action === 'copy-secret') {
    try { await navigator.clipboard.writeText(target.dataset.secret); toast('Secret copied.', 'ok'); }
    catch { toast('Select the secret and copy it.', 'error'); }
  }
  if (action === 'go-signin') { showMode('password'); }
});

handlers['reset-request'] = async (form) => {
  const data = new FormData(form);
  const result = await post('/api/auth/reset/request', { email: data.get('email') });
  body(`<div class="auth-form"><div class="infobox">If that email has an account, a reset link is on its way.</div>
    ${result.dev_link ? `<div class="warnbox small">Development: no email provider is configured.
      <br><a class="btn small" style="margin-top:8px" href="${result.dev_link}">Open my reset link</a></div>` : ''}
    <button class="btn ghost" type="button" data-action="restart">Back to sign in</button></div>`);
};

async function boot() {
  const params = new URLSearchParams(location.search);
  const stage = params.get('stage');
  const challenge = params.get('challenge');
  if (stage === 'totp' && challenge) {
    state.challenge = challenge;
    showTotp();
    history.replaceState(null, '', '/login');
    return;
  }
  try {
    const session = await fetch('/api/auth/session', { credentials: 'same-origin' }).then(r => r.json());
    if (session && session.signed_in) { location.href = '/'; return; }
  } catch (err) { /* stay on the page */ }
  try {
    state.meta = await fetch('/api/meta', { credentials: 'same-origin' }).then(r => r.json());
  } catch (err) { state.meta = null; }
  if (state.meta && state.meta.dev_mode) {
    const hint = $('#devHint');
    hint.hidden = false;
    hint.textContent = 'Development mode: no email or SMS provider is configured, so sign-in links and codes appear right here (and in data/outbox.log).';
  }
  showRoles();
  if (state.meta && state.meta.google_enabled && window.google && window.google.accounts) {
    const form = $('#googleForm');
    form.hidden = false;
    window.google.accounts.id.initialize({
      client_id: state.meta.google_client_id,
      callback: async (response) => {
        try { await afterSignIn(await post('/api/auth/google', { credential: response.credential })); }
        catch (err) { toast(err.message, 'error'); }
      },
    });
    window.google.accounts.id.renderButton($('#gsiButton'), { theme: 'outline', size: 'large', width: 360 });
  }
}

showMode('password');
boot();
