'use strict';
/* The buyer's shop: menu from the API, basket, checkout, order history. */

const S = {
  slug: new URLSearchParams(location.search).get('b') || localStorage.getItem('nivora_shop') || '',
  shop: null,
  cart: [],
  category: 'all',
  query: '',
  lastOrder: null,
  phone: localStorage.getItem('nivora_phone') || '',
};

const $ = (sel, root = document) => root.querySelector(sel);
const esc = (value) => String(value == null ? '' : value)
  .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;').replaceAll("'", '&#39;');
const money = (value) => 'RM' + Number(value || 0).toFixed(2);
const todayISO = () => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
};
const addDays = (iso, days) => {
  const [y, m, d] = iso.split('-').map(Number);
  const next = new Date(y, m - 1, d + days);
  return `${next.getFullYear()}-${String(next.getMonth() + 1).padStart(2, '0')}-${String(next.getDate()).padStart(2, '0')}`;
};

function toast(message, kind = '') {
  const el = document.createElement('div');
  el.className = 'toast ' + kind;
  el.textContent = message;
  $('#toast').appendChild(el);
  setTimeout(() => el.remove(), kind === 'error' ? 6000 : 3500);
}

async function api(path, options = {}) {
  const opts = { method: options.method || 'GET', credentials: 'same-origin', headers: {} };
  if (options.body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(options.body);
  }
  let res;
  try {
    res = await fetch(path, opts);
  } catch {
    throw new Error('Cannot reach the shop. Check your connection.');
  }
  const text = await res.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = { message: text }; }
  if (!res.ok || data.ok === false) {
    const err = new Error(data.message || 'Something went wrong.');
    err.code = data.code;
    throw err;
  }
  return data;
}

/* ------------------------------------------------------------------ cart */

function cartKey() { return 'nivora_cart_' + S.slug; }

function loadCart() {
  try { S.cart = JSON.parse(localStorage.getItem(cartKey())) || []; } catch { S.cart = []; }
}

function saveCart() {
  localStorage.setItem(cartKey(), JSON.stringify(S.cart));
  renderCart();
}

function cartTotals() {
  const items = S.cart.reduce((sum, line) => sum + line.price * line.quantity, 0);
  const delivery = ($('#orderType') ? $('#orderType').value : 'Delivery') === 'Pickup' ? 0 : 4;
  return { items, delivery, total: items + delivery };
}

function addToCart(id) {
  const product = (S.shop.products || []).find(p => p.id === id);
  if (!product) return;
  const existing = S.cart.find(l => l.id === id);
  if (existing) existing.quantity += 1;
  else S.cart.push({ id, name: product.name, price: Number(product.price), quantity: 1 });
  saveCart();
  toast(`${product.name} added to your basket.`);
  $('#cartCount').textContent = S.cart.reduce((n, l) => n + l.quantity, 0);
}

function changeQty(id, delta) {
  const line = S.cart.find(l => l.id === id);
  if (!line) return;
  line.quantity += delta;
  if (line.quantity <= 0) S.cart = S.cart.filter(l => l.id !== id);
  saveCart();
}

function removeLine(id) {
  S.cart = S.cart.filter(l => l.id !== id);
  saveCart();
}

/* ---------------------------------------------------------------- render */

function renderShop() {
  const shop = S.shop;
  document.title = `${shop.business.name} · order food`;
  $('#shopName').textContent = shop.business.name;
  $('#aboutName').textContent = shop.business.name;
  const botMount = document.getElementById('botMount');
  if (botMount) botMount.dataset.name = shop.business.name;
  if (shop.business.tagline) $('#shopTagline').textContent = shop.business.tagline;
  $('#shopAddress').textContent = shop.business.address || 'Ask the seller for the pickup address.';
  $('#shopPhone').textContent = shop.business.phone || '';
  const signature = shop.products[0];
  if (signature) {
    $('#signatureName').textContent = signature.name;
    $('#signaturePrice').textContent = `${money(signature.price)} · ${signature.category}`;
  }
  renderChips();
  renderMenu();
}

function renderChips() {
  const cats = ['all', ...(S.shop.categories || [])];
  $('#categoryChips').innerHTML = cats.map(cat => `
    <button class="chip ${cat === S.category ? 'active' : ''}" data-cat="${esc(cat)}">
      ${cat === 'all' ? 'All food' : esc(cat)}
    </button>`).join('');
}

function renderMenu() {
  const grid = $('#menuGrid');
  const products = (S.shop.products || []).filter(p => {
    const inCat = S.category === 'all' || p.category === S.category;
    const text = (p.name + ' ' + (p.description || '') + ' ' + p.category).toLowerCase();
    return inCat && text.includes(S.query.toLowerCase());
  });
  grid.innerHTML = products.map(product => `
    <article class="dish">
      <div class="dish-img">
        ${product.image_url
          ? `<img src="${esc(product.image_url)}" alt="${esc(product.name)}" loading="lazy">`
          : `<span class="dish-initial">${esc((product.name || '?')[0])}</span>`}
        <span class="dish-price">${money(product.price)}</span>
      </div>
      <div class="dish-body">
        <span class="dish-cat">${esc(product.category)}</span>
        <h3>${esc(product.name)}</h3>
        <p>${esc(product.description || 'Fresh from the kitchen.')}</p>
        <button class="btn ghost" data-add="${product.id}">Add to basket</button>
      </div>
    </article>`).join('');
  $('#menuEmpty').hidden = products.length > 0;
}

function renderCart() {
  const body = $('#cartItems');
  const count = S.cart.reduce((n, l) => n + l.quantity, 0);
  $('#cartSubtitle').textContent = `${count} item${count === 1 ? '' : 's'}`;
  $('#cartCount').textContent = count;
  if (!S.cart.length) {
    body.innerHTML = `<div class="empty">Your basket is empty.<br><a href="#menu">Choose something from the menu</a>.</div>`;
    $('#cartFooter').hidden = true;
    return;
  }
  body.innerHTML = S.cart.map(line => `
    <div class="cart-line">
      <div class="grow">
        <strong>${esc(line.name)}</strong>
        <small>${money(line.price)} each</small>
        <div class="qty">
          <button data-qty="${line.id}" data-delta="-1" aria-label="Less">−</button>
          <span>${line.quantity}</span>
          <button data-qty="${line.id}" data-delta="1" aria-label="More">+</button>
        </div>
      </div>
      <div>
        <strong>${money(line.price * line.quantity)}</strong>
        <div><button class="btn ghost small" data-remove="${line.id}" style="padding:4px 8px;font-size:11px">Remove</button></div>
      </div>
    </div>`).join('');
  $('#cartFooter').hidden = false;
  const totals = cartTotals();
  $('#cartSubtotal').textContent = money(totals.items);
  $('#cartFee').textContent = money(totals.delivery);
  $('#cartTotal').textContent = money(totals.total);
  const itemsEl = $('#checkoutItems');
  if (itemsEl) itemsEl.textContent = money(totals.items);
  const feeEl = $('#checkoutFee');
  if (feeEl) feeEl.textContent = money(totals.delivery);
  const totalEl = $('#checkoutTotal');
  if (totalEl) totalEl.textContent = money(totals.total);
}

/* --------------------------------------------------------------- overlays */

function openCart() {
  renderCart();
  $('#cartOverlay').hidden = false;
}
function closeCart() { $('#cartOverlay').hidden = true; }

function openCheckout() {
  if (!S.cart.length) return;
  closeCart();
  const date = $('#deliveryDate');
  if (date && !date.value) date.value = addDays(todayISO(), 1);
  $('#checkoutError').hidden = true;
  $('#checkoutOverlay').hidden = false;
  renderCart();
}
function closeCheckout() { $('#checkoutOverlay').hidden = true; }

function showSuccess(order) {
  $('#checkoutOverlay').hidden = true;
  const lines = (order.items || []).map(i => `<div><span>${esc(i.product_name || i.name)} × ${i.quantity}</span><span>${money(i.unit_price)}</span></div>`).join('');
  $('#successReceipt').innerHTML = `
    <div><span>Reference</span><strong>${esc(order.reference)}</strong></div>
    <div><span>Delivery</span><strong>${esc(order.delivery_date)}</strong></div>
    ${lines}
    <div><span>Total</span><strong>${money(order.total)}</strong></div>`;
  const chat = $('#successChat');
  if (order.thread_token) {
    chat.hidden = false;
    chat.href = `/chat.html?t=${encodeURIComponent(order.thread_token)}`;
  }
  $('#successOverlay').hidden = false;
}

/* --------------------------------------------------------------- history */

function localOrders() {
  try { return JSON.parse(localStorage.getItem('nivora_orders_' + S.slug)) || []; } catch { return []; }
}

function saveLocalOrder(order) {
  const saved = localOrders();
  saved.unshift(order);
  localStorage.setItem('nivora_orders_' + S.slug, JSON.stringify(saved.slice(0, 20)));
}

async function renderHistory() {
  const box = $('#myOrders');
  let orders = localOrders();
  if (S.phone) {
    try {
      const res = await api(`/api/public/shops/${encodeURIComponent(S.slug)}/orders?phone=${encodeURIComponent(S.phone)}`);
      if (res.orders && res.orders.length) orders = res.orders;
    } catch { /* the local copy is enough */ }
  }
  if (!orders.length) {
    box.innerHTML = `<div class="empty">No orders yet. Your first order will show here.</div>`;
    return;
  }
  box.innerHTML = orders.map(order => `
    <article class="order-card">
      <div class="order-top">
        <div>
          <span class="order-ref">${esc(order.reference)}</span>
          <span class="pill">${esc(order.status || 'received')}</span>
          <div class="small muted">${esc(order.delivery_date || '')}</div>
        </div>
        <strong>${money(order.total)}</strong>
      </div>
      <div class="order-lines">
        ${(order.items || []).map(i => `<div><span>${esc(i.product_name || i.name)} × ${i.quantity}</span>
          <span>${money(Number(i.unit_price || i.price) * Number(i.quantity))}</span></div>`).join('')}
      </div>
    </article>`).join('');
}

/* ------------------------------------------------------------------ boot */

async function boot() {
  if (!S.slug) {
    $('#menuGrid').innerHTML = '';
    document.querySelector('main').innerHTML = `
      <section class="wrap" style="padding:70px 0;max-width:640px">
        <h1 style="font-size:32px">This is a buyer link</h1>
        <p class="muted">Open the link your seller gave you, or sign in as a seller to copy it.</p>
        <a class="btn primary" href="/login">Go to sign-in</a>
      </section>`;
    return;
  }
  localStorage.setItem('nivora_shop', S.slug);
  try {
    S.shop = await api(`/api/public/shops/${encodeURIComponent(S.slug)}`);
  } catch (err) {
    $('#menuGrid').innerHTML = '';
    document.querySelector('main').innerHTML = `
      <section class="wrap" style="padding:70px 0;max-width:640px">
        <h1 style="font-size:32px">Shop not found</h1>
        <p class="muted">${esc(err.message)}</p>
      </section>`;
    return;
  }
  loadCart();
  renderShop();
  renderCart();
  renderHistory();

  document.addEventListener('click', (event) => {
    const add = event.target.closest('[data-add]');
    if (add) { addToCart(Number(add.dataset.add)); openCart(); return; }
    const qty = event.target.closest('[data-qty]');
    if (qty) { changeQty(Number(qty.dataset.qty), Number(qty.dataset.delta)); return; }
    const remove = event.target.closest('[data-remove]');
    if (remove) { removeLine(Number(remove.dataset.remove)); return; }
    const chip = event.target.closest('[data-cat]');
    if (chip) { S.category = chip.dataset.cat; renderChips(); renderMenu(); return; }
    const close = event.target.closest('[data-close]');
    if (close) {
      if (close.dataset.close === 'cart') closeCart();
      if (close.dataset.close === 'checkout') closeCheckout();
    }
  });

  $('#cartBtn').addEventListener('click', openCart);
  $('#cartOverlay').addEventListener('click', (event) => {
    if (event.target.id === 'cartOverlay') closeCart();
  });
  $('#checkoutBtn').addEventListener('click', openCheckout);
  $('#checkoutOverlay').addEventListener('click', (event) => {
    if (event.target.id === 'checkoutOverlay') closeCheckout();
  });
  $('#orderType').addEventListener('change', (event) => {
    $('#addressField').style.display = event.target.value === 'Pickup' ? 'none' : 'flex';
    renderCart();
  });
  $('#successClose').addEventListener('click', () => {
    $('#successOverlay').hidden = true;
    location.hash = '#orders';
    renderHistory();
  });
  $('#shopName').addEventListener('click', () => { S.query = ''; renderMenu(); });

  $('#checkoutForm').addEventListener('submit', async (event) => {
    event.preventDefault();
    const form = event.target;
    const data = new FormData(form);
    const button = $('#placeOrder');
    button.disabled = true;
    button.textContent = 'Sending to the kitchen…';
    $('#checkoutError').hidden = true;
    try {
      const order = await api(`/api/public/shops/${encodeURIComponent(S.slug)}/orders`, {
        method: 'POST',
        body: {
          customer_name: data.get('customer_name'),
          phone: data.get('phone'),
          address: data.get('address') || null,
          order_type: data.get('order_type'),
          payment_method: data.get('payment_method'),
          notes: data.get('notes') || null,
          delivery_date: data.get('delivery_date'),
          items: S.cart.map(line => ({ product_id: line.id, quantity: line.quantity })),
        },
      });
      const placed = S.cart.map(line => ({
        product_name: line.name, quantity: line.quantity, unit_price: line.price,
      }));
      S.phone = String(data.get('phone') || '');
      localStorage.setItem('nivora_phone', S.phone);
      saveLocalOrder({
        reference: order.reference, status: 'received', total: order.total,
        delivery_date: order.delivery_date, items: placed,
      });
      S.cart = [];
      saveCart();
      form.reset();
      showSuccess({ ...order, items: placed });
      renderHistory();
    } catch (err) {
      $('#checkoutError').textContent = err.message;
      $('#checkoutError').hidden = false;
    } finally {
      button.disabled = false;
      button.textContent = 'Place order';
    }
  });
}

boot();
