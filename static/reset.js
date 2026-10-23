'use strict';
/* One-time reset link: choose a new password. */

const token = new URLSearchParams(location.search).get('token') || '';

function toast(message, kind = '') {
  const box = document.createElement('div');
  box.className = 'toast ' + kind;
  box.textContent = message;
  document.querySelector('#toast').appendChild(box);
  setTimeout(() => box.remove(), 6000);
}

document.querySelector('#resetForm').addEventListener('submit', async (event) => {
  event.preventDefault();
  const form = event.target;
  const data = new FormData(form);
  if (data.get('password') !== data.get('repeat')) {
    toast('The two passwords are not the same.', 'error');
    return;
  }
  if (!token) {
    toast('This link has no token. Request a new one.', 'error');
    return;
  }
  const button = form.querySelector('button');
  button.disabled = true;
  try {
    const res = await fetch('/api/auth/reset', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ token, new_password: data.get('password') }),
    });
    const body = await res.json();
    if (!res.ok) throw new Error(body.message || 'That link did not work.');
    form.hidden = true;
    document.querySelector('#done').hidden = false;
  } catch (err) {
    toast(err.message, 'error');
    button.disabled = false;
  }
});
