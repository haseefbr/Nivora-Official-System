'use strict';
/* The customer's page: one link, no sign-in, write the order. */

const params = new URLSearchParams(location.search);
const token = params.get('t') || '';
const $ = (sel) => document.querySelector(sel);
let lastCount = -1;

function esc(value) {
  return String(value == null ? '' : value)
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}

function when(iso) {
  const d = new Date(iso);
  return isNaN(d) ? '' : d.toLocaleString('en-MY', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
}

function toast(message, kind = '') {
  const box = document.createElement('div');
  box.className = 'toast ' + kind;
  box.textContent = message;
  $('#toast').appendChild(box);
  setTimeout(() => box.remove(), 5000);
}

async function load() {
  if (!token) {
    $('#messages').innerHTML = '<div class="empty"><strong>Link not valid</strong>Ask the seller for a new chat link.</div>';
    return;
  }
  try {
    const res = await fetch('/api/public/threads/' + encodeURIComponent(token), { credentials: 'same-origin' });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || 'This link is not valid.');
    $('#biz').textContent = 'Chat with ' + data.business;
    document.title = 'Order · ' + data.business;
    const messages = data.thread.messages;
    if (messages.length !== lastCount) {
      lastCount = messages.length;
      $('#messages').innerHTML = messages.length ? messages.map(m => `
        <div class="msg ${m.direction === 'out' ? 'in' : 'out'}">${esc(m.body)}
          <span class="when">${m.direction === 'out' ? 'You' : esc(data.business)} · ${when(m.created_at)}</span></div>`
      ).join('') : '<div class="empty">Write your order below. The seller replies here.</div>';
      const box = $('#messages');
      box.scrollTop = box.scrollHeight;
    }
  } catch (err) {
    $('#messages').innerHTML = `<div class="empty"><strong>Could not open the chat</strong>${esc(err.message)}</div>`;
  }
}

$('#sendForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const input = event.target.querySelector('input[name=body]');
  const body = (input.value || '').trim();
  if (!body) return;
  const button = event.target.querySelector('button');
  button.disabled = true;
  try {
    const res = await fetch('/api/public/threads/' + encodeURIComponent(token) + '/messages', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify({ body }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.message || 'Could not send.');
    input.value = '';
    toast(data.draft_id ? 'Order received. The seller will confirm it.' : 'Message sent.', 'ok');
    lastCount = -1;
    await load();
  } catch (err) {
    toast(err.message, 'error');
  } finally {
    button.disabled = false;
  }
});

load();
setInterval(load, 6000);
