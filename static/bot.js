/* The shop assistant: a small chat panel for the seller app and the shop page.
   Mount: <div id="botMount" data-mode="seller|buyer" data-name="…"></div> */
(function () {
  const mount = document.getElementById('botMount');
  if (!mount) return;
  const mode = mount.dataset.mode || 'seller';
  const shopName = mount.dataset.name || '';
  const slug = new URLSearchParams(location.search).get('b')
    || localStorage.getItem('nivora_shop') || '';
  const endpoint = mode === 'buyer'
    ? `/api/public/shops/${encodeURIComponent(slug)}/bot`
    : '/api/bot/chat';
  const storeKey = `nivora_bot_${mode}_${slug || 'app'}`;
  const sessionId = (() => {
    let id = localStorage.getItem(storeKey + '_session');
    if (!id) {
      id = (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()).slice(0, 36);
      localStorage.setItem(storeKey + '_session', id);
    }
    return id;
  })();

  let history = [];
  try { history = JSON.parse(localStorage.getItem(storeKey) || '[]').slice(-8); } catch { history = []; }

  const root = document.createElement('div');
  root.className = 'nivora-bot';
  root.innerHTML = `
    <button class="bot-fab" type="button" aria-label="Ask the shop assistant">
      <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" stroke-width="1.8"
           stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
        <path d="M21 11.5a8.4 8.4 0 0 1-8.5 8.4 9.1 9.1 0 0 1-3.6-.7L4 20.5l1.4-4.2A8.3 8.3 0 0 1 4 11.5 8.4 8.4 0 0 1 12.5 3 8.4 8.4 0 0 1 21 11.5Z"/>
      </svg>
      <span class="bot-fab-label">${mode === 'buyer' ? 'Tanya' : 'Ask'}</span>
    </button>
    <section class="bot-panel" hidden aria-label="Shop assistant">
      <header class="bot-head">
        <div>
          <strong>${mode === 'buyer' ? 'Shop assistant' : 'Shop assistant'}</strong>
          <small>${esc(shopName || 'Menu, delivery, payment')}</small>
        </div>
        <button class="bot-close" type="button" aria-label="Close">×</button>
      </header>
      <div class="bot-log" id="botLog" role="log" aria-live="polite"></div>
      <form class="bot-form">
        <input name="message" autocomplete="off" placeholder="${mode === 'buyer' ? 'Harga kuih lapis?' : 'What do I charge for kuih lapis?'}" maxlength="400" required>
        <button type="submit" aria-label="Send">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2"
               stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m5 12 14-7-4 7 4 7Z"/></svg>
        </button>
      </form>
      <p class="bot-foot">Answers come from this shop's menu. Anything unclear, message the seller.</p>
    </section>`;
  mount.appendChild(root);

  const fab = root.querySelector('.bot-fab');
  const panel = root.querySelector('.bot-panel');
  const log = root.querySelector('.bot-log');
  const form = root.querySelector('.bot-form');
  const input = form.querySelector('input');

  function esc(text) {
    return String(text == null ? '' : text).replace(/[&<>"']/g, (c) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function bubble(role, text) {
    const el = document.createElement('div');
    el.className = 'bot-msg ' + role;
    el.innerHTML = esc(text).replace(/\n/g, '<br>');
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  function remember() {
    localStorage.setItem(storeKey, JSON.stringify(history.slice(-8)));
  }

  const greeting = mode === 'buyer'
    ? 'Hai! Tanya saya pasal menu, harga atau penghantaran.'
    : 'Ask me about this shop: menu, prices, delivery, what to say to a customer.';

  if (history.length) {
    history.forEach((turn) => bubble(turn.role === 'bot' ? 'bot' : 'me', turn.text));
  } else {
    bubble('bot', greeting);
  }

  fab.addEventListener('click', () => {
    panel.hidden = !panel.hidden;
    fab.hidden = !panel.hidden;
    if (!panel.hidden) {
      const label = panel.querySelector('.bot-head small');
      if (label && mount.dataset.name) label.textContent = mount.dataset.name;
      setTimeout(() => input.focus(), 30);
    }
  });
  root.querySelector('.bot-close').addEventListener('click', () => {
    panel.hidden = true; fab.hidden = false; fab.focus();
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const message = input.value.trim();
    if (!message) return;
    input.value = '';
    bubble('me', message);
    history.push({ role: 'user', text: message });
    remember();

    const thinking = bubble('bot thinking', 'Thinking…');
    const send = form.querySelector('button');
    send.disabled = true;
    const started = Date.now();
    try {
      const headers = { 'Content-Type': 'application/json' };
      const csrf = window.NIVORA_CSRF
        || (typeof App !== 'undefined' && App.csrf)
        || document.querySelector('meta[name="csrf-token"]')?.content;
      if (csrf) headers['X-CSRF-Token'] = csrf;
      const res = await fetch(endpoint, {
        method: 'POST', credentials: 'same-origin', headers,
        body: JSON.stringify({ message, session_id: sessionId, history: history.slice(-6) }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok || data.ok === false) {
        throw new Error(data.message || 'The assistant is busy. Try again.');
      }
      thinking.remove();
      bubble('bot', data.reply);
      history.push({ role: 'bot', text: data.reply });
      remember();
      const seconds = ((Date.now() - started) / 1000).toFixed(1);
      if (Number(seconds) > 4) {
        const note = document.createElement('div');
        note.className = 'bot-time';
        note.textContent = `${seconds}s`;
        log.appendChild(note);
      }
    } catch (err) {
      thinking.remove();
      bubble('bot error', err.message || 'Something went wrong.');
    } finally {
      send.disabled = false;
      input.focus();
    }
  });
})();
