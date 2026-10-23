'use strict';
/* NIVORA app: plain JavaScript, no build step, no inline handlers (CSP). */

const App = { me: null, csrf: null, tab: 'orders', cache: {}, inbox: { threadId: null } };

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const TABS = ['orders', 'parser', 'recipes', 'production', 'grocery', 'profit', 'inbox', 'settings'];

/* ------------------------------------------------------------------ utils */

function esc(value) {
  return String(value == null ? '' : value)
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;').replaceAll("'", '&#39;');
}

function money(value) {
  const n = Number(value || 0);
  return 'RM ' + (isFinite(n) ? n : 0).toFixed(2);
}

function num(value) {
  const n = Number(value || 0);
  return Number.isInteger(n) ? String(n) : (isFinite(n) ? n.toFixed(3).replace(/0+$/, '').replace(/\.$/, '') : '0');
}

function todayISO() {
  const d = new Date();
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function isoOf(dateObj) {
  return `${dateObj.getFullYear()}-${String(dateObj.getMonth() + 1).padStart(2, '0')}-${String(dateObj.getDate()).padStart(2, '0')}`;
}

function addDays(iso, days) {
  const [year, month, day] = iso.split('-').map(Number);
  return isoOf(new Date(year, month - 1, day + days));
}

function monthRange() {
  const now = new Date();
  return {
    start: isoOf(new Date(now.getFullYear(), now.getMonth(), 1)),
    end: isoOf(new Date(now.getFullYear(), now.getMonth() + 1, 0)),
  };
}

function fmtDay(iso) {
  if (!iso) return '<span class="muted">no date</span>';
  const parts = String(iso).slice(0, 10).split('-').map(Number);
  const d = new Date(parts[0], (parts[1] || 1) - 1, parts[2] || 1);
  if (isNaN(d)) return esc(iso);
  return d.toLocaleDateString('en-MY', { weekday: 'short', day: 'numeric', month: 'short' });
}

function fmtWhen(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (isNaN(d)) return '';
  return d.toLocaleString('en-MY', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit' });
}

function initials(name) {
  return String(name || '?').trim().split(/\s+/).slice(0, 2).map(w => w[0] || '').join('').toUpperCase();
}

function outcomeLabel(outcome) {
  return ({
    call_ok: 'ok', repair_call: 'repaired', safe_reply: 'safe reply',
    repaired: 'repaired once', failed: 'failed', refused: 'refused',
  })[outcome] || outcome;
}

function toast(message, kind = '') {
  const box = document.createElement('div');
  box.className = 'toast ' + kind;
  box.textContent = message;
  $('#toast').appendChild(box);
  setTimeout(() => box.remove(), kind === 'error' ? 6000 : 3500);
}

async function api(path, { method = 'GET', body } = {}) {
  const opts = { method, credentials: 'same-origin', headers: {} };
  if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  if (method !== 'GET' && App.csrf) opts.headers['X-CSRF-Token'] = App.csrf;
  const res = await fetch(path, opts);
  const text = await res.text();
  let data = {};
  try { data = text ? JSON.parse(text) : {}; } catch { data = { message: text }; }
  if (res.status === 401) {
    if (!location.pathname.startsWith('/login')) location.href = '/login';
    throw new Error('Signed out');
  }
  if (!res.ok || data.ok === false) {
    const err = new Error(data.message || 'Something went wrong.');
    err.code = data.code;
    err.status = res.status;
    err.data = data;
    throw err;
  }
  return data;
}

/* ----------------------------------------------------------------- modal */

function openModal(title, body, subtitle = '') {
  $('#modalRoot').innerHTML = `
    <div class="modal-backdrop" data-close="1">
      <div class="modal" role="dialog" aria-modal="true">
        <div class="modal-head">
          <div>
            <h2>${esc(title)}</h2>
            ${subtitle ? `<div class="hint">${esc(subtitle)}</div>` : ''}
          </div>
          <div class="spacer"></div>
          <button class="btn ghost small" data-close="1">Close</button>
        </div>
        <div class="modal-body">${body}</div>
      </div>
    </div>`;
}

function closeModal() { $('#modalRoot').innerHTML = ''; }

$('#modalRoot').addEventListener('click', (event) => {
  if (event.target.dataset.close === '1') closeModal();
});
document.addEventListener('keydown', (event) => { if (event.key === 'Escape') closeModal(); });

/* ------------------------------------------------------------------ boot */

async function boot() {
  try {
    const me = await api('/api/me');
    App.me = me;
    App.csrf = me.csrf_token;
    $('#bizName').textContent = me.tenant.name;
    const botMount = document.getElementById('botMount');
    if (botMount) botMount.dataset.name = me.tenant.name;
    $('#bizPlan').textContent = me.tenant.plan.toUpperCase() + ' plan · ' + me.role;
    if (me.unread) $('#unreadDot') && ($('#unreadDot').hidden = false);
    if (!me.two_factor_enabled) $('#tfaChip') && ($('#tfaChip').hidden = false);
    const tab = (location.hash || '#orders').slice(1);
    setTab(TABS.includes(tab) ? tab : 'orders');
    refreshChip();
    loadNotifications();
    setInterval(loadNotifications, 20000);
    const shop = await api('/api/shop').catch(() => null);
    const sideLink = $('#shopLinkSide');
    if (shop && sideLink) sideLink.href = shop.shop_url;
  } catch (err) {
    if (err.message !== 'Signed out') {
      $('#view').innerHTML = `<div class="card"><h3>Could not load</h3>
        <p class="muted">${esc(err.message)}</p>
        <button class="btn" data-action="retry">Try again</button></div>`;
    }
  }
}

async function refreshChip() {
  try {
    const shop = await api('/api/notifications');
    const chip = $('#usageChip');
    if (chip) {
      chip.className = 'chip ' + (shop.unread ? 'warn' : 'good');
      chip.textContent = shop.unread ? `${shop.unread} new` : 'All caught up';
      chip.hidden = true;
    }
  } catch (err) { /* the chip is not worth an error */ }
}

async function loadNotifications() {
  try {
    const data = await api('/api/notifications');
    App.notifications = data.notifications;
    const badge = $('#bellCount');
    if (badge) {
      badge.hidden = data.unread === 0;
      badge.textContent = data.unread > 9 ? '9+' : String(data.unread);
    }
    const list = $('#bellList');
    if (list) {
      list.innerHTML = data.notifications.length
        ? data.notifications.slice(0, 12).map(n => `
          <div class="bell-item ${n.read_at ? '' : 'unread'}"
               data-action="open-notification" data-order="${n.order_id || ''}" data-id="${n.id}">
            <strong>${esc(n.title)}</strong>
            <span>${esc(n.body || '')} · ${fmtWhen(n.created_at)}</span>
          </div>`).join('')
        : `<div class="bell-empty">${esc(t('notify.empty'))}</div>`;
    }
    const dot = $('#unreadDot');
    if (dot) dot.hidden = !data.unread;
  } catch (err) { /* the bell is not worth an error */ }
}

function setTab(tab) {
  App.tab = tab;
  if (location.hash !== '#' + tab) history.replaceState(null, '', '#' + tab);
  applyLang();
  const view = VIEWS[tab] || VIEWS.orders;
  view().catch(err => {
    $('#view').innerHTML = `<div class="card"><h3>Something went wrong</h3>
      <p class="muted">${esc(err.message)}</p>
      <button class="btn" data-action="retry">${esc(t('action.review'))}</button></div>`;
  });
}

function applyLang() {
  $$('#nav button').forEach(button => {
    const key = 'nav.' + button.dataset.tab;
    if (button.dataset.tab === 'inbox') {
      button.innerHTML = `${esc(t(key))} <span id="unreadDot" class="dot"${App.me && App.me.unread ? '' : ' hidden'}></span>`;
    } else {
      button.textContent = t(key);
    }
    button.classList.toggle('active', button.dataset.tab === App.tab);
  });
  $$('#langSeg button').forEach(button => {
    button.classList.toggle('active', button.dataset.lang === LANG);
  });
  $$('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
  if (App.tab) {
    $('#pageTitle').textContent = t('title.' + App.tab);
    $('#pageSub').textContent = t('sub.' + App.tab);
  }
}

function loading() {
  $('#view').innerHTML = `<div class="grid c4">
    <div class="card"><div class="skeleton" style="width:60%"></div></div>
    <div class="card"><div class="skeleton" style="width:60%"></div></div>
    <div class="card"><div class="skeleton" style="width:60%"></div></div>
    <div class="card"><div class="skeleton" style="width:60%"></div></div></div>`;
}

/* ----------------------------------------------------------------- orders */

const VIEWS = {};

VIEWS.orders = async function () {
  loading();
  const [dash, orders, drafts] = await Promise.all([
    api('/api/dashboard'),
    api('/api/orders?limit=100'),
    api('/api/ai/drafts'),
  ]);
  App.cache.dash = dash;
  App.cache.orders = orders.orders;
  const month = dash.month;
  const upcoming = orders.orders.filter(o => o.status === 'active');
  $('#view').innerHTML = `
    <div class="grid c4">
      <div class="card stat"><span class="label">Active orders</span>
        <span class="value">${dash.active_orders}</span>
        <span class="delta">${dash.due_today} due today</span></div>
      <div class="card stat"><span class="label">Unpaid</span>
        <span class="value">${dash.unpaid_orders}</span>
        <span class="delta">chase before delivery</span></div>
      <div class="card stat"><span class="label">Net profit · month</span>
        <span class="value">${money(month.net_profit)}</span>
        <span class="delta">${money(month.revenue)} revenue · ${month.margin_percent}% margin</span></div>
      <div class="card stat"><span class="label">Waiting for you</span>
        <span class="value">${dash.pending_drafts + dash.unread_messages}</span>
        <span class="delta">${dash.pending_drafts} parsed drafts · ${dash.unread_messages} unread messages</span></div>
    </div>

    ${dash.pending_drafts ? `<div class="warnbox" style="margin-top:14px">
      ${dash.pending_drafts} parsed ${dash.pending_drafts === 1 ? 'draft is' : 'drafts are'} waiting for your approval.
      <button class="btn link" data-action="go-parser">Review them</button></div>` : ''}

    <div class="card flush" style="margin-top:16px">
      <div class="card-head">
        <h3>All orders</h3>
        <span class="badge soft">${orders.orders.length}</span>
        <div class="spacer"></div>
        <input type="text" id="orderSearch" placeholder="Search customer, product, address" style="max-width:260px">
        <button class="btn" data-action="new-order">New order</button>
      </div>
      ${orders.orders.length ? `<div class="table-wrap"><table>
        <thead><tr><th>Customer</th><th>Delivery</th><th>Items</th><th>Status</th><th>Payment</th>
        <th class="right">Total</th><th></th></tr></thead>
        <tbody>${orders.orders.map(orderRow).join('')}</tbody>
      </table></div>` : emptyBox('No orders yet', 'Paste a customer message into the AI parser, or add one by hand.')}
    </div>

    <div class="grid c2" style="margin-top:16px">
      <div class="card flush">
        <div class="card-head"><h3>Next deliveries</h3></div>
        <div class="list">${dash.upcoming.length ? dash.upcoming.map(u => `
          <div class="list-item">
            <div class="avatar">${esc(initials(u.customer_name || 'Walk-in'))}</div>
            <div class="grow">
              <div class="title">${esc(u.customer_name || 'Walk-in customer')}</div>
              <div class="meta">${fmtDay(u.delivery_date)} · ${u.items} item${u.items === 1 ? '' : 's'}</div>
            </div>
            <span class="badge ${esc(u.payment_status)}">${esc(u.payment_status)}</span>
          </div>`).join('') : '<div class="empty">Nothing scheduled yet.</div>'}</div>
      </div>
      <div class="card flush">
        <div class="card-head"><h3>Parsed drafts</h3><div class="spacer"></div>
          <button class="btn ghost small" data-action="go-parser">Open parser</button></div>
        <div class="list">${drafts.drafts.length ? drafts.drafts.slice(0, 5).map(draftRow).join('')
          : '<div class="empty">No drafts waiting. Messages from customers land here.</div>'}</div>
      </div>
    </div>`;

  const search = $('#orderSearch');
  if (search) {
    search.addEventListener('input', () => {
      const q = search.value.toLowerCase();
      $$('tbody tr').forEach(row => {
        row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
      });
    });
  }
};

function orderRow(o) {
  return `<tr>
    <td><div class="title">${esc(o.customer_name || 'Walk-in customer')}</div>
      <div class="meta small muted">${esc(o.source === 'parser' ? 'from a message' : 'added by hand')}</div></td>
    <td class="num">${fmtDay(o.delivery_date)}</td>
    <td class="num">${o.item_count}</td>
    <td><span class="badge ${esc(o.status)}">${esc(o.status)}</span></td>
    <td><span class="badge ${esc(o.payment_status)}">${esc(o.payment_status)}</span></td>
    <td class="right num">${money(o.total)}</td>
    <td class="right"><button class="btn ghost small" data-action="open-order" data-id="${o.id}">Open</button></td>
  </tr>`;
}

function draftRow(draft) {
  const p = draft.payload || {};
  const first = (p.items && p.items[0]) || {};
  return `<div class="list-item">
    <div class="grow">
      <div class="title">${esc(first.product_name || 'Order')} ${first.quantity ? '× ' + num(first.quantity) : ''}</div>
      <div class="meta">${esc(p.customer_name || 'Unknown customer')} · ${fmtDay(p.delivery_date)}
        · ${Math.round(Number(draft.confidence || 0) * 100)}% sure
        ${draft.needs_human ? '<span class="badge review">check this</span>' : ''}</div>
    </div>
    <button class="btn ghost small" data-action="approve-draft" data-id="${draft.id}">Approve</button>
  </div>`;
}

function emptyBox(title, text) {
  return `<div class="empty"><strong>${esc(title)}</strong>${esc(text)}</div>`;
}

async function openOrder(id) {
  const { order } = await api('/api/orders/' + id);
  const profit = await api(`/api/orders/${id}/profit`);
  const p = profit.profit;
  openModal('Order #' + id, `
    <div class="row wrap" style="gap:8px;margin-bottom:12px">
      <span class="badge ${esc(order.status)}">${esc(order.status)}</span>
      <span class="badge ${esc(order.payment_status)}">${esc(order.payment_status)}</span>
      <span class="muted small">${esc(order.customer_name || 'Walk-in')} · ${fmtDay(order.delivery_date)}</span>
    </div>
    ${order.address ? `<div class="small muted" style="margin-bottom:10px">${esc(order.address)}</div>` : ''}
    <table><thead><tr><th>Product</th><th class="right">Qty</th><th class="right">Price</th>
      <th class="right">Unit cost</th><th class="right">Line</th></tr></thead>
      <tbody>${p.lines.map(l => `<tr>
        <td>${esc(l.product_name)}${l.recipe_id ? '' : ' <span class="badge review">no recipe</span>'}</td>
        <td class="right num">${num(l.quantity)}</td>
        <td class="right num">${money(l.unit_price)}</td>
        <td class="right num">${money(l.unit_cost)}</td>
        <td class="right num">${money(l.revenue)}</td></tr>`).join('')}</tbody></table>
    <div class="divider"></div>
    <div class="parse-out">
      <div class="parse-line"><span class="k">Revenue</span><span class="v num">${money(p.revenue)}</span></div>
      <div class="parse-line"><span class="k">Ingredients</span><span class="v num">− ${money(p.cogs)}</span></div>
      <div class="parse-line"><span class="k">Fees</span><span class="v num">− ${money(p.fees)}</span></div>
      <div class="parse-line"><span class="k"><b>Net profit</b></span><span class="v num"><b>${money(p.net_profit)} · ${p.margin_percent}%</b></span></div>
    </div>
    ${p.missing_recipes.length ? `<div class="warnbox">No recipe for ${p.missing_recipes.map(esc).join(', ')}, so its ingredient cost counts as zero. Add the recipe to see the real profit.</div>` : ''}
    <div class="row wrap" style="margin-top:14px">
      <button class="btn small" data-action="set-payment" data-id="${order.id}" data-status="paid">Mark paid</button>
      <button class="btn ghost small" data-action="set-payment" data-id="${order.id}" data-status="deposit">Deposit</button>
      <button class="btn ghost small" data-action="set-payment" data-id="${order.id}" data-status="unpaid">Unpaid</button>
      <div class="spacer"></div>
      <button class="btn ghost small" data-action="set-status" data-id="${order.id}" data-status="done">Mark done</button>
      <button class="btn danger small" data-action="delete-order" data-id="${order.id}">Delete</button>
    </div>`);
}

function newOrderModal() {
  openModal('New order', `
    <form data-form="order" class="form-grid">
      <label class="field">Customer name
        <input name="customer_name" type="text" placeholder="Aminah" required>
      </label>
      <label class="field">Phone
        <input name="customer_phone" type="tel" placeholder="+60123456789">
      </label>
      <label class="field">Delivery date
        <input name="delivery_date" type="date" value="${addDays(todayISO(), 1)}">
      </label>
      <label class="field">Address
        <input name="address" type="text" placeholder="12 Jalan Melati, 43000 Kajang">
      </label>
      <div class="full">
        <div class="row"><strong class="small">Items</strong><div class="spacer"></div>
          <button type="button" class="btn ghost small" data-action="add-item-row">Add item</button></div>
        <div id="itemRows" style="margin-top:8px;display:flex;flex-direction:column;gap:8px">
          ${itemRowHTML(0)}
        </div>
      </div>
      <label class="field full">Note (optional)
        <input name="notes" type="text" placeholder="Less sugar, pick up at 4pm">
      </label>
      <div class="full row"><div class="spacer"></div>
        <button class="btn" type="submit">Save order</button></div>
    </form>`);
}

function itemRowHTML(index) {
  return `<div class="row item-row" style="gap:6px">
    <input name="product_${index}" type="text" placeholder="Product, e.g. kuih lapis" required style="flex:3">
    <input name="qty_${index}" type="number" step="0.001" min="0.001" placeholder="Qty" required style="flex:1">
    <input name="unit_${index}" type="text" placeholder="biji" value="biji" style="flex:1">
    <input name="price_${index}" type="number" step="0.01" min="0" placeholder="RM/pc" style="flex:1">
  </div>`;
}

async function submitOrder(form) {
  const data = new FormData(form);
  const items = [];
  let i = 0;
  while (data.has('product_' + i)) {
    const product = (data.get('product_' + i) || '').trim();
    const qty = Number(data.get('qty_' + i));
    if (product && qty > 0) {
      items.push({
        product_name: product,
        quantity: qty,
        unit: (data.get('unit_' + i) || 'biji').trim() || 'biji',
        unit_price: data.get('price_' + i) ? Number(data.get('price_' + i)) : null,
      });
    }
    i += 1;
  }
  if (!items.length) throw new Error('Add at least one item with a quantity.');
  await api('/api/orders', {
    method: 'POST',
    body: {
      customer_name: data.get('customer_name'),
      customer_phone: data.get('customer_phone') || null,
      delivery_date: data.get('delivery_date') || null,
      address: data.get('address') || null,
      notes: data.get('notes') || null,
      items,
    },
  });
  closeModal();
  toast('Order saved.', 'ok');
  setTab('orders');
}

/* ----------------------------------------------------------------- parser */

VIEWS.parser = async function () {
  loading();
  const drafts = await api('/api/ai/drafts');
  App.cache.drafts = drafts.drafts;
  $('#view').innerHTML = `
    <div class="grid c2">
      <div class="card">
        <h3>Paste the customer message</h3>
        <div class="hint">Bahasa Melayu or English. Nothing leaves your server except the model call.</div>
        <form data-form="parse" style="margin-top:12px;display:flex;flex-direction:column;gap:10px">
          <textarea name="message" id="parseText" placeholder="Salam, saya nak order 20 biji kuih lapis untuk esok. Antar ke 12 Jalan Melati, 43000 Kajang. Nama saya Aminah."></textarea>
          <div class="row wrap">
            <button class="btn" type="submit" id="parseBtn">Read the message</button>
            <button class="btn ghost small" type="button" data-action="sample" data-sample="bm">Example (BM)</button>
            <button class="btn ghost small" type="button" data-action="sample" data-sample="en">Example (EN)</button>
            <div class="spacer"></div>
            <span class="small muted">Max 4,000 characters</span>
          </div>
        </form>
        <div id="parseResult" style="margin-top:14px"></div>
      </div>

      <div class="card flush">
        <div class="card-head"><h3>Waiting for approval</h3><div class="spacer"></div>
          <span class="badge soft">${drafts.drafts.length}</span></div>
        <div class="list" id="draftList">${drafts.drafts.length
          ? drafts.drafts.map(fullDraftRow).join('')
          : '<div class="empty"><strong>Nothing waiting</strong>Parsed orders appear here until you approve them.</div>'}</div>
      </div>
    </div>`;

  const btn = $('#parseBtn');
  if (btn) btn.disabled = false;
};

function fullDraftRow(draft) {
  const p = draft.payload || {};
  const items = (p.items || []).map(i => `<span class="item-pill">${esc(i.product_name)} × ${num(i.quantity)} ${esc(i.unit)}</span>`).join(' ');
  return `<div class="list-item" style="flex-direction:column;gap:8px">
    <div class="row" style="width:100%">
      <div class="grow">
        <div class="title">${esc(p.customer_name || 'Unknown customer')}
          ${draft.needs_human ? '<span class="badge review">check this</span>' : ''}</div>
        <div class="meta">${fmtDay(p.delivery_date)} · ${Math.round(Number(draft.confidence || 0) * 100)}% sure</div>
      </div>
      <button class="btn small" data-action="approve-draft" data-id="${draft.id}">Approve</button>
      <button class="btn ghost small" data-action="reject-draft" data-id="${draft.id}">Reject</button>
    </div>
    <div class="row wrap" style="gap:6px">${items || '<span class="muted small">No items</span>'}</div>
    ${p.address ? `<div class="small muted">${esc(p.address)}</div>` : ''}
    <div class="small muted" style="font-style:italic">“${esc((draft.raw_text || '').slice(0, 160))}${(draft.raw_text || '').length > 160 ? '…' : ''}”</div>
  </div>`;
}

async function runParse() {
  const text = ($('#parseText') || {}).value || '';
  const out = $('#parseResult');
  if (!text.trim()) { toast('Write a message first.', 'error'); return; }
  const btn = $('#parseBtn');
  btn.disabled = true;
  btn.textContent = 'Reading…';
  out.innerHTML = '<div class="skeleton" style="width:100%"></div>';
  try {
    const res = await api('/api/ai/parse', { method: 'POST', body: { message: text } });
    const p = res.payload || {};
    const items = (p.items || []).map(i => `<span class="item-pill">${esc(i.product_name)} × ${num(i.quantity)} ${esc(i.unit)}</span>`).join(' ');
    out.innerHTML = `
      <div class="parse-out">
        <div class="parse-line"><span class="k">Intent</span><span class="v">
          <span class="badge ${p.intent === 'order' ? 'active' : 'soft'}">${esc(p.intent)}</span>
          ${res.needs_human ? '<span class="badge review">needs a person</span>' : ''}</span></div>
        <div class="parse-line"><span class="k">Customer</span><span class="v">${esc(p.customer_name || '—')}</span></div>
        <div class="parse-line"><span class="k">Items</span><span class="v">${items || '<span class="muted">none</span>'}</span></div>
        <div class="parse-line"><span class="k">Delivery</span><span class="v">${p.delivery_date ? fmtDay(p.delivery_date) : '<span class="muted">not given</span>'}</span></div>
        <div class="parse-line"><span class="k">Address</span><span class="v">${esc(p.address || '—')}</span></div>
      </div>
      ${res.draft_id ? `<div class="row" style="margin-top:12px">
        <button class="btn" data-action="approve-draft" data-id="${res.draft_id}">${t('action.approve')} → create order</button>
        <button class="btn ghost small" data-action="reject-draft" data-id="${res.draft_id}">${t('action.reject')}</button></div>` : ''}
      ${p.intent === 'question' ? '<div class="infobox" style="margin-top:10px">This is a question, not an order: nothing was saved.</div>' : ''}`;
    await refreshChip();
    if (App.tab === 'parser') {
      const drafts = await api('/api/ai/drafts');
      const list = $('#draftList');
      if (list) list.innerHTML = drafts.drafts.length ? drafts.drafts.map(fullDraftRow).join('')
        : '<div class="empty"><strong>Nothing waiting</strong>Parsed orders appear here until you approve them.</div>';
    }
  } catch (err) {
    out.innerHTML = `<div class="warnbox">${esc(err.message)}</div>`;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Read the message';
  }
}

/* ---------------------------------------------------------------- recipes */

VIEWS.recipes = async function () {
  loading();
  const [ings, recipes] = await Promise.all([api('/api/ingredients'), api('/api/recipes')]);
  App.cache.ingredients = ings.ingredients;
  App.cache.recipes = recipes.recipes;
  $('#view').innerHTML = `
    <div class="grid c2">
      <div class="card flush">
        <div class="card-head"><h3>Ingredients</h3><div class="spacer"></div>
          <button class="btn small" data-action="new-ingredient">Add ingredient</button></div>
        ${ings.ingredients.length ? `<div class="table-wrap"><table>
          <thead><tr><th>Ingredient</th><th class="right">Pack</th><th class="right">Cost / unit</th></tr></thead>
          <tbody>${ings.ingredients.map(i => `<tr>
            <td>${esc(i.name)}<div class="meta small muted">per ${esc(i.unit)}</div></td>
            <td class="right num">${money(i.pack_price)} / ${num(i.pack_size)} ${esc(i.unit)}</td>
            <td class="right num">${(Number(i.cost_per_unit) || 0).toFixed(4)}</td></tr>`).join('')}</tbody>
        </table></div>` : emptyBox('No ingredients yet', 'Add flour, sugar, santan: the pack you buy and what you pay.')}
      </div>

      <div class="card flush">
        <div class="card-head"><h3>Recipes</h3><div class="spacer"></div>
          <button class="btn small" data-action="new-recipe">New recipe</button></div>
        ${recipes.recipes.length ? `<div class="list">${recipes.recipes.map(r => `
          <div class="list-item">
            <div class="grow">
              <div class="title">${esc(r.product_name)}</div>
              <div class="meta">${r.item_count} ingredients · makes ${r.yield_units} · sells at ${money(r.sell_price)}</div>
            </div>
            <div style="text-align:right">
              <div class="num"><b>${money(r.unit_cost)}</b></div>
              <div class="small muted">margin ${money(r.margin_per_unit)}</div>
            </div>
            <button class="btn ghost small" data-action="open-recipe" data-id="${r.id}">Open</button>
          </div>`).join('')}</div>` : emptyBox('No recipes yet', 'A recipe turns ingredient prices into a cost per piece.')}
      </div>
    </div>

    <div class="card" style="margin-top:16px">
      <h3>Cost from a recipe message</h3>
      <div class="hint">Paste a recipe. The AI reads the ingredients; code prices them from your ingredient list. The AI never sets a price.</div>
      <form data-form="costing" style="margin-top:12px;display:flex;flex-direction:column;gap:10px">
        <textarea name="message" placeholder="Resepi kuih lapis: 500 g gula, 400 g tepung beras, 200 ml santan, 20 ml pewarna. Dapat 40 biji."></textarea>
        <div class="row"><button class="btn" type="submit">Read recipe &amp; cost it</button>
          <span class="small muted">Only ingredients you already stock get a cost.</span></div>
      </form>
      <div id="costResult" style="margin-top:12px"></div>
    </div>`;
};

function ingredientOptions(selected) {
  return App.cache.ingredients.map(i =>
    `<option value="${i.id}" ${String(i.id) === String(selected) ? 'selected' : ''}>${esc(i.name)} (${esc(i.unit)})</option>`
  ).join('');
}

function recipeItemRow(index) {
  return `<div class="row" style="gap:6px">
    <select name="ing_${index}" style="flex:3">${ingredientOptions()}</select>
    <input name="iqty_${index}" type="number" step="0.001" min="0.001" placeholder="Qty in that unit" required style="flex:2">
  </div>`;
}

async function openRecipe(id) {
  const { recipe } = await api('/api/recipes/' + id);
  openModal(recipe.product_name, `
    <div class="row wrap" style="gap:8px;margin-bottom:12px">
      <span class="badge soft">makes ${recipe.yield_units}</span>
      <span class="badge soft">sells at ${money(recipe.sell_price)}</span>
      <span class="badge ${Number(recipe.margin_per_unit) > 0 ? 'paid' : 'unpaid'}">margin ${money(recipe.margin_per_unit)} (${recipe.margin_percent}%)</span>
    </div>
    <table><thead><tr><th>Ingredient</th><th class="right">Quantity</th><th class="right">Cost</th></tr></thead>
      <tbody>${recipe.items.map(i => `<tr><td>${esc(i.ingredient)}</td>
        <td class="right num">${num(i.quantity)} ${esc(i.unit)}</td>
        <td class="right num">${money(i.cost)}</td></tr>`).join('')}</tbody></table>
    <div class="divider"></div>
    <div class="parse-line"><span class="k">Batch cost</span><span class="v num">${money(recipe.batch_cost)}</span></div>
    <div class="parse-line"><span class="k">Cost each</span><span class="v num"><b>${money(recipe.unit_cost)}</b> of ${recipe.yield_units}</span></div>
    <form data-form="recipe-item" data-id="${recipe.id}" style="margin-top:14px">
      <div class="row" style="gap:6px"><select name="ing_0" style="flex:3">${ingredientOptions()}</select>
        <input name="iqty_0" type="number" step="0.001" min="0.001" placeholder="Qty" required style="flex:2">
        <button class="btn small" type="submit">Add</button></div>
    </form>`, 'Recipe and its real ingredient cost');
}

function newRecipeModal() {
  openModal('New recipe', `
    <form data-form="recipe" class="form-grid">
      <label class="field">Recipe name<input name="name" type="text" placeholder="Kuih lapis asas" required></label>
      <label class="field">Product it makes<input name="product_name" type="text" placeholder="kuih lapis" required></label>
      <label class="field">Pieces per batch<input name="yield_units" type="number" min="1" value="40" required></label>
      <label class="field">Selling price each (RM)<input name="sell_price" type="number" step="0.01" min="0" value="1.20"></label>
      <div class="full">
        <div class="row"><strong class="small">Ingredients in one batch</strong><div class="spacer"></div>
          <button type="button" class="btn ghost small" data-action="add-recipe-row">Add ingredient</button></div>
        <div id="recipeRows" style="margin-top:8px;display:flex;flex-direction:column;gap:8px">
          ${recipeItemRow(0)}
        </div>
      </div>
      <div class="full row"><div class="spacer"></div><button class="btn" type="submit">Save recipe</button></div>
    </form>`);
}

async function submitRecipe(form) {
  const data = new FormData(form);
  const items = [];
  let i = 0;
  while (data.has('ing_' + i)) {
    const ingredientId = data.get('ing_' + i);
    const qty = Number(data.get('iqty_' + i));
    if (ingredientId && qty > 0) items.push({ ingredient_id: Number(ingredientId), quantity: qty });
    i += 1;
  }
  if (!items.length) throw new Error('Add at least one ingredient.');
  await api('/api/recipes', {
    method: 'POST',
    body: {
      name: data.get('name'),
      product_name: data.get('product_name'),
      yield_units: Number(data.get('yield_units')),
      sell_price: Number(data.get('sell_price') || 0),
      items,
    },
  });
  closeModal();
  toast('Recipe saved.', 'ok');
  setTab('recipes');
}

async function submitCosting(form) {
  const text = new FormData(form).get('message');
  const out = $('#costResult');
  out.innerHTML = '<div class="skeleton" style="width:100%"></div>';
  try {
    const res = await api('/api/ai/costing', { method: 'POST', body: { message: text } });
    const applied = res.applied || { lines: [], matched_cost: '0' };
    out.innerHTML = `
      <div class="table-wrap"><table><thead><tr><th>Ingredient</th><th class="right">Amount</th>
        <th class="right">Your cost</th></tr></thead><tbody>
        ${applied.lines.map(l => `<tr><td>${esc(l.ingredient)}${l.matched ? '' : ' <span class="badge review">not stocked</span>'}</td>
          <td class="right num">${num(l.quantity)} ${esc(l.unit || '')}</td>
          <td class="right num">${l.matched ? money(l.cost) : '<span class="muted">—</span>'}</td></tr>`).join('')}
      </tbody></table></div>
      <div class="row" style="margin-top:10px"><span class="badge soft">ingredients cost ${money(applied.matched_cost)}</span>
        ${applied.saved ? `<span class="badge paid">saved as recipe #${applied.recipe_id}</span>` : ''}
        <div class="spacer"></div>
        <span class="small muted">${esc(res.provider)} · ${esc(res.checks || '')}</span></div>
      ${applied.unmatched.length ? `<div class="warnbox" style="margin-top:10px">Not priced yet: ${applied.unmatched.map(esc).join(', ')}. Add them under Ingredients with the pack you buy.</div>` : ''}`;
    await refreshChip();
  } catch (err) {
    out.innerHTML = `<div class="warnbox">${esc(err.message)}</div>`;
  }
}

/* ------------------------------------------------------------- production */

VIEWS.production = async function () {
  loading();
  const day = App.cache.planDate || addDays(todayISO(), 1);
  App.cache.planDate = day;
  const plan = await api('/api/production?date=' + day);
  const p = plan.plan;
  $('#view').innerHTML = `
    <div class="card">
      <div class="row wrap">
        <h3>Cook list</h3>
        <div class="spacer"></div>
        <label class="field" style="flex-direction:row;align-items:center;gap:8px">Date
          <input type="date" id="planDate" value="${day}" style="width:auto"></label>
        <button class="btn small" data-action="grocery-from-plan">Shopping list</button>
      </div>
      <div class="hint" style="margin-top:4px">${p.orders} orders for delivery that day.</div>
      ${p.items.length ? `<div class="table-wrap" style="margin-top:12px"><table>
        <thead><tr><th>Product</th><th class="right">Total to make</th><th class="right">Per batch</th>
          <th class="right">Batches</th><th class="right">Orders</th></tr></thead>
        <tbody>${p.items.map(i => `<tr>
          <td>${esc(i.product_name)} ${i.recipe_id ? '' : '<span class="badge review">no recipe</span>'}</td>
          <td class="right num">${num(i.total_quantity)} ${esc(i.unit)}</td>
          <td class="right num">${i.yield_units || '—'}</td>
          <td class="right num"><b>${i.batches == null ? '—' : i.batches}</b></td>
          <td class="right num">${i.order_count}</td></tr>`).join('')}</tbody></table></div>`
        : emptyBox('Nothing to cook', 'No active orders are set for delivery on this date.')}
      ${p.missing_recipes.length ? `<div class="warnbox" style="margin-top:12px">
        These products have no recipe, so batches cannot be counted: ${p.missing_recipes.map(esc).join(', ')}.</div>` : ''}
    </div>
    <div class="grid c3" style="margin-top:16px">
      <div class="card stat"><span class="label">Units that day</span><span class="value">${num(p.total_units)}</span></div>
      <div class="card stat"><span class="label">Products</span><span class="value">${p.items.length}</span></div>
      <div class="card stat"><span class="label">Batches</span>
        <span class="value">${p.items.reduce((sum, i) => sum + (i.batches || 0), 0)}</span></div>
    </div>`;
  $('#planDate').addEventListener('change', (event) => {
    App.cache.planDate = event.target.value;
    VIEWS.production();
  });
};

/* ---------------------------------------------------------------- grocery */

VIEWS.grocery = async function () {
  loading();
  const mode = App.cache.groceryMode || 'day';
  const day = App.cache.groceryDate || addDays(todayISO(), 1);
  const end = mode === 'week' ? addDays(day, 6) : day;
  App.cache.groceryDate = day;
  const data = await api(`/api/grocery?start=${day}&end=${end}`);
  const list = data.list;
  $('#view').innerHTML = `
    <div class="card">
      <div class="row wrap">
        <h3>Shopping list</h3>
        <div class="spacer"></div>
        <div class="seg">
          <button data-action="grocery-mode" data-mode="day" class="${mode === 'day' ? 'active' : ''}">One day</button>
          <button data-action="grocery-mode" data-mode="week" class="${mode === 'week' ? 'active' : ''}">Seven days</button>
        </div>
        <input type="date" id="groceryDate" value="${day}" style="width:auto">
      </div>
      <div class="hint" style="margin-top:4px">${fmtDay(list.start)}${mode === 'week' ? ' to ' + fmtDay(list.end) : ''} ·
        ${list.items.length} ingredients · estimated ${money(list.total_cost)}</div>
      ${list.items.length ? `<div class="table-wrap" style="margin-top:12px"><table>
        <thead><tr><th>Buy</th><th class="right">Needed</th><th class="right">Packs</th>
          <th class="right">Est. cost</th><th>For</th></tr></thead>
        <tbody>${list.items.map(i => `<tr>
          <td><b>${esc(i.ingredient)}</b></td>
          <td class="right num">${num(i.quantity)} ${esc(i.unit)}</td>
          <td class="right num">${i.packs_to_buy == null ? '—' : i.packs_to_buy}</td>
          <td class="right num">${money(i.estimated_cost)}</td>
          <td class="small muted">${i.for_products.map(esc).join(', ')}</td></tr>`).join('')}</tbody>
        <tfoot><tr><th colspan="3">Estimated total</th><th class="right num">${money(list.total_cost)}</th><th></th></tr></tfoot>
      </table></div>` : emptyBox('Nothing to buy', 'This period has no active orders, or the products have no recipe yet.')}
      ${list.missing_recipes.length ? `<div class="warnbox" style="margin-top:12px">
        Skipped (no recipe): ${list.missing_recipes.map(esc).join(', ')}.</div>` : ''}
    </div>`;
  $('#groceryDate').addEventListener('change', (event) => {
    App.cache.groceryDate = event.target.value;
    VIEWS.grocery();
  });
};

/* ----------------------------------------------------------------- profit */

VIEWS.profit = async function () {
  loading();
  const range = monthRange();
  const start = App.cache.profitStart || range.start;
  const end = App.cache.profitEnd || range.end;
  App.cache.profitStart = start;
  App.cache.profitEnd = end;
  const data = await api(`/api/profit?start=${start}&end=${end}`);
  const p = data.profit;
  $('#view').innerHTML = `
    <div class="card">
      <div class="row wrap">
        <h3>Profit &amp; loss</h3>
        <div class="spacer"></div>
        <label class="field" style="flex-direction:row;align-items:center;gap:6px">From
          <input type="date" id="pStart" value="${start}" style="width:auto"></label>
        <label class="field" style="flex-direction:row;align-items:center;gap:6px">To
          <input type="date" id="pEnd" value="${end}" style="width:auto"></label>
      </div>
    </div>
    <div class="grid c4" style="margin-top:14px">
      <div class="card stat"><span class="label">Revenue</span><span class="value">${money(p.revenue)}</span></div>
      <div class="card stat"><span class="label">Ingredients</span><span class="value">${money(p.cogs)}</span></div>
      <div class="card stat"><span class="label">Fees</span><span class="value">${money(p.fees)}</span></div>
      <div class="card stat"><span class="label">Net profit</span><span class="value">${money(p.net_profit)}</span>
        <span class="delta">${p.margin_percent}% margin</span></div>
    </div>
    <div class="card flush" style="margin-top:16px">
      <div class="card-head"><h3>Orders in this period</h3></div>
      ${p.orders.length ? `<div class="table-wrap"><table>
        <thead><tr><th>Order</th><th>Customer</th><th>Delivery</th><th class="right">Revenue</th>
          <th class="right">Cost</th><th class="right">Net</th><th>Payment</th></tr></thead>
        <tbody>${p.orders.map(o => `<tr>
          <td>#${o.order_id}</td><td>${esc(o.customer_name || 'Walk-in')}</td>
          <td>${fmtDay(o.delivery_date)}</td>
          <td class="right num">${money(o.revenue)}</td>
          <td class="right num">${money(o.cogs)}</td>
          <td class="right num"><b>${money(o.net_profit)}</b></td>
          <td><span class="badge ${esc(o.payment_status)}">${esc(o.payment_status)}</span></td></tr>`).join('')}</tbody>
      </table></div>` : emptyBox('No orders in this period', 'Change the dates, or add an order.')}
    </div>`;
  const reload = () => {
    App.cache.profitStart = $('#pStart').value;
    App.cache.profitEnd = $('#pEnd').value;
    VIEWS.profit();
  };
  $('#pStart').addEventListener('change', reload);
  $('#pEnd').addEventListener('change', reload);
};

/* ------------------------------------------------------------------ inbox */

VIEWS.inbox = async function () {
  loading();
  const data = await api('/api/threads');
  const threads = data.threads;
  App.cache.threads = threads;
  const active = threads.find(t => t.id === App.inbox.threadId) || threads[0];
  App.inbox.threadId = active ? active.id : null;
  let thread = null;
  if (active) thread = (await api('/api/threads/' + active.id)).thread;
  $('#view').innerHTML = `
    <div class="inbox">
      <div class="card flush">
        <div class="card-head"><h3>Conversations</h3><div class="spacer"></div>
          <button class="btn small" data-action="new-thread">New link</button></div>
        <div class="thread-list">${threads.length ? threads.map(t => `
          <button data-action="open-thread" data-id="${t.id}" class="${active && t.id === active.id ? 'active' : ''}">
            <div class="t">${esc(t.customer_name || 'Customer')}
              ${t.unread ? `<span class="badge unpaid">${t.unread}</span>` : ''}</div>
            <div class="p">${esc(t.last_body || 'No messages yet')}</div>
          </button>`).join('') : '<div class="empty"><strong>No conversations</strong>Create a link and send it to a customer.</div>'}
        </div>
      </div>
      <div class="card flush">
        ${thread ? `
          <div class="card-head"><h3>${esc(thread.customer_name || 'Customer')}</h3>
            <div class="spacer"></div>
            <button class="btn ghost small" data-action="copy-link" data-token="${esc(thread.public_token)}">Copy customer link</button></div>
          <div class="chat-box">
            <div class="messages" id="messages">${thread.messages.length ? thread.messages.map(m => `
              <div class="msg ${m.direction === 'out' ? 'out' : 'in'}">${esc(m.body)}
                <span class="when">${esc(m.author)} · ${fmtWhen(m.created_at)}</span></div>`).join('')
              : '<div class="empty">No messages yet. The customer writes first.</div>'}</div>
            <form class="composer" data-form="reply" data-id="${thread.id}">
              <input name="body" type="text" placeholder="Reply to ${esc(thread.customer_name || 'the customer')}…" autocomplete="off">
              <button class="btn" type="submit">Send</button>
            </form>
          </div>` : emptyBox('Pick a conversation', 'Or create a link a customer can open on their phone.')}
      </div>
    </div>`;
  const messages = $('#messages');
  if (messages) messages.scrollTop = messages.scrollHeight;
  if (App.me && active) {
    App.me.unread = 0;
    const dot = $('#unreadDot');
    if (dot) dot.hidden = true;
  }
};

function newThreadModal() {
  openModal('Send a customer a chat link', `
    <form data-form="thread" style="display:flex;flex-direction:column;gap:10px">
      <label class="field">Customer name<input name="customer_name" type="text" placeholder="Aminah" required></label>
      <div class="hint">You get one link for this customer. They open it on their phone, write their order, and it lands in your message box.</div>
      <div class="row"><div class="spacer"></div><button class="btn" type="submit">Create link</button></div>
    </form>`);
}

/* --------------------------------------------------------------- settings */

VIEWS.settings = async function () {
  loading();
  const [business, products, ideas, me] = await Promise.all([
    api('/api/settings/business'),
    api('/api/products'),
    api('/api/recipe-ideas'),
    api('/api/me'),
  ]);
  App.cache.business = business;
  App.cache.products = products.products;
  const shopUrl = location.origin + '/shop?b=' + encodeURIComponent(business.slug);
  $('#view').innerHTML = `
    <div class="grid c2">
      <div class="card">
        <h3>${t('setting.business')}</h3>
        <div class="hint">${t('setting.businessHint')}</div>
        <form data-form="business" class="form-grid" style="margin-top:12px">
          <label class="field">${t('setting.name')}<input name="name" value="${esc(business.name)}" required></label>
          <label class="field">${t('setting.tagline')}<input name="tagline" value="${esc(business.tagline || '')}" placeholder="Kuih muih, dibuat setiap pagi"></label>
          <label class="field">${t('setting.phone')}<input name="phone" value="${esc(business.phone || '')}" placeholder="+60123456789"></label>
          <label class="field">${t('setting.address')}<input name="address" value="${esc(business.address || '')}" placeholder="12 Jalan Melati, 43000 Kajang"></label>
          <label class="field full">Opening hours<input name="hours" value="${esc(business.hours || '')}" placeholder="Setiap hari, 9:00 pagi – 6:00 petang"></label>
          <div class="full row"><div class="spacer"></div><button class="btn" type="submit">${t('action.save')}</button></div>
        </form>
      </div>

      <div class="card">
        <h3>${t('setting.shopLink')}</h3>
        <div class="hint">${t('setting.shopHint')}</div>
        <div class="secret-box" style="margin-top:12px">${esc(shopUrl)}</div>
        <div class="row wrap" style="margin-top:10px">
          <button class="btn ghost small" data-action="copy-shop" data-url="${esc(shopUrl)}">${t('action.copy')}</button>
          <a class="btn ghost small" href="${esc(shopUrl)}" target="_blank" rel="noopener">Open shop ↗</a>
        </div>
        <div class="divider"></div>
        <h3>${t('setting.language')}</h3>
        <div class="hint">${t('setting.languageHint')}</div>
        <div class="seg" style="margin-top:10px" id="settingsLang">
          <button data-lang="en">English</button>
          <button data-lang="bm">Bahasa Melayu</button>
        </div>
        <div class="divider"></div>
        <div class="row"><span class="small muted">Two-factor sign-in</span><div class="spacer"></div>
          <span class="badge ${me.two_factor_enabled ? 'paid' : 'unpaid'}">${me.two_factor_enabled ? 'on' : 'off'}</span></div>
        <div class="row" style="margin-top:8px"><span class="small muted">Export</span><div class="spacer"></div>
          <a class="btn ghost small" href="/api/export?format=csv">CSV</a>
          <a class="btn ghost small" href="/api/export?format=json">JSON</a></div>
      </div>
    </div>

    <div class="card flush" style="margin-top:16px">
      <div class="card-head"><h3>${t('setting.menu')}</h3>
        <span class="small muted">${t('setting.menuHint')}</span>
        <div class="spacer"></div>
        <button class="btn small" data-action="new-dish">${t('setting.addDish')}</button></div>
      ${products.products.length ? `<div class="table-wrap"><table>
        <thead><tr><th>${t('setting.menuName')}</th><th>${t('setting.menuCategory')}</th>
          <th class="right">${t('setting.menuPrice')}</th><th>Recipe</th><th></th></tr></thead>
        <tbody>${products.products.map(p => `<tr>
          <td><b>${esc(p.name)}</b><div class="meta small muted">${esc(p.description || '')}</div></td>
          <td>${esc(p.category)}</td>
          <td class="right num">${money(p.price)}</td>
          <td>${p.recipe_id ? '<span class="badge paid">costed</span>' : '<span class="badge review">no recipe</span>'}</td>
          <td class="right"><button class="btn ghost small" data-action="edit-dish" data-id="${p.id}">Edit</button>
            <button class="btn danger small" data-action="delete-dish" data-id="${p.id}">✕</button></td>
        </tr>`).join('')}</tbody></table></div>`
        : `<div class="empty"><strong>${t('setting.noDishes')}</strong></div>`}
    </div>

    <div class="card flush" style="margin-top:16px">
      <div class="card-head"><h3>${t('setting.recipeIdeas')}</h3>
        <div class="spacer"></div>
        <span class="small muted">${t('setting.recipeIdeasHint')}</span></div>
      ${ideas.ideas.length ? `<div class="list">${ideas.ideas.map(idea => `
        <div class="list-item">
          <div class="grow">
            <div class="title">${esc(idea.dish)}</div>
            <div class="meta">${(idea.payload.items || []).map(i => esc(i.ingredient) + ' ' + num(i.quantity) + ' ' + esc(i.unit)).join(' · ')}</div>
            <div class="meta">Makes ${idea.payload.yield_units || '?'} · ${Math.round(Number(idea.payload.confidence || 0) * 100)}% sure</div>
          </div>
          <button class="btn small" data-action="approve-idea" data-id="${idea.id}">${t('setting.approveCost')}</button>
          <button class="btn ghost small" data-action="reject-idea" data-id="${idea.id}">${t('action.reject')}</button>
        </div>`).join('')}</div>`
        : `<div class="empty">${t('setting.noIdeas')}</div>`}
    </div>`;

  $$('#settingsLang button').forEach(button => button.addEventListener('click', () => {
    setLang(button.dataset.lang);
    applyLang();
    setTab('settings');
  }));
};

function dishModal(product) {
  const isEdit = Boolean(product);
  openModal(isEdit ? 'Edit dish' : t('setting.addDish'), `
    <form data-form="product" class="form-grid" data-id="${product ? product.id : ''}">
      <label class="field">${t('setting.menuName')}
        <input name="name" value="${esc(product ? product.name : '')}" required placeholder="Nasi lemak"></label>
      <label class="field">${t('setting.menuPrice')}
        <input name="price" type="number" step="0.01" min="0" value="${product ? Number(product.price).toFixed(2) : ''}" required placeholder="7.50"></label>
      <label class="field">${t('setting.menuCategory')}
        <input name="category" value="${esc(product ? product.category : 'Food')}" placeholder="Rice &amp; meals"></label>
      <label class="field">Photo URL (optional)
        <input name="image_url" value="${esc(product && product.image_url ? product.image_url : '')}" placeholder="https://…"></label>
      <label class="field full">${t('setting.menuDescription')}
        <input name="description" value="${esc(product && product.description ? product.description : '')}" placeholder="Coconut rice, sambal, egg"></label>
      <div class="full row"><div class="spacer"></div>
        <button class="btn" type="submit">${t('action.save')}</button></div>
    </form>`, 'Shows on your shop page straight away.');
}

/* --------------------------------------------------------------- actions */

const actions = {
  'read-all': async () => {
    try {
      await api('/api/notifications/read', { method: 'POST', body: {} });
      loadNotifications();
    } catch (err) { toast(err.message, 'error'); }
  },
  'open-notification': async (btn) => {
    try {
      await api('/api/notifications/read', {
        method: 'POST', body: { notification_id: Number(btn.dataset.id) },
      });
      const panel = $('#bellPanel');
      if (panel) panel.hidden = true;
      loadNotifications();
      setTab(btn.dataset.order ? 'orders' : 'inbox');
    } catch (err) { toast(err.message, 'error'); }
  },
  'copy-shop': async (btn) => {
    try {
      await navigator.clipboard.writeText(btn.dataset.url);
      toast('Shop link copied.', 'ok');
    } catch (err) {
      openModal(t('setting.shopLink'), `<div class="secret-box">${esc(btn.dataset.url)}</div>`);
    }
  },
  'new-dish': () => dishModal(),
  'edit-dish': (btn) => dishModal((App.cache.products || []).find(p => String(p.id) === btn.dataset.id)),
  'delete-dish': async (btn) => {
    if (!confirm('Remove this dish from the menu?')) return;
    try {
      await api(`/api/products/${btn.dataset.id}`, { method: 'DELETE' });
      toast('Dish removed.');
      VIEWS.settings();
    } catch (err) { toast(err.message, 'error'); }
  },
  'approve-idea': async (btn) => {
    try {
      const res = await api(`/api/recipe-ideas/${btn.dataset.id}/approve`, { method: 'POST' });
      if (res.applied && res.applied.saved) {
        toast('Recipe saved and costed from your ingredient prices.', 'ok');
      } else {
        toast('Recipe saved, but its ingredients have no prices yet.', 'error');
      }
      VIEWS.settings();
    } catch (err) { toast(err.message, 'error'); }
  },
  'reject-idea': async (btn) => {
    try {
      await api(`/api/recipe-ideas/${btn.dataset.id}/reject`, { method: 'POST' });
      VIEWS.settings();
    } catch (err) { toast(err.message, 'error'); }
  },
  retry: () => setTab(App.tab),
  'go-parser': () => setTab('parser'),
  'new-order': () => newOrderModal(),
  'open-order': (btn) => openOrder(btn.dataset.id).catch(e => toast(e.message, 'error')),
  'add-item-row': () => {
    const rows = $('#itemRows');
    const index = rows.children.length;
    rows.insertAdjacentHTML('beforeend', itemRowHTML(index));
  },
  'add-recipe-row': () => {
    const rows = $('#recipeRows');
    rows.insertAdjacentHTML('beforeend', recipeItemRow(rows.children.length));
  },
  sample: (btn) => {
    const samples = {
      bm: 'Salam, saya nak order 20 biji kuih lapis dan 10 kotak pineapple tart untuk 24/10. Antar ke 12 Jalan Melati, 43000 Kajang. Nama saya Aminah.',
      en: 'Hi, please order 15 boxes of pineapple tarts and 10 boxes of seri muka for 24/10. Deliver to 8 Lorong Satu, 43300 Seri Kembangan. My name is Mei Ling.',
    };
    const box = $('#parseText');
    if (box) box.value = samples[btn.dataset.sample] || '';
  },
  'approve-draft': async (btn) => {
    try {
      const res = await api(`/api/ai/parse/${btn.dataset.id}/approve`, { method: 'POST' });
      closeModal();
      toast(`Order #${res.order.id} created from the message.`, 'ok');
      setTab('orders');
    } catch (err) { toast(err.message, 'error'); }
  },
  'reject-draft': async (btn) => {
    try {
      await api(`/api/ai/parse/${btn.dataset.id}/reject`, { method: 'POST' });
      toast('Draft rejected.');
      setTab(App.tab);
    } catch (err) { toast(err.message, 'error'); }
  },
  'set-payment': async (btn) => {
    try {
      await api(`/api/orders/${btn.dataset.id}/payment`, {
        method: 'PATCH', body: { payment_status: btn.dataset.status },
      });
      closeModal();
      toast('Payment updated.', 'ok');
      setTab(App.tab);
    } catch (err) { toast(err.message, 'error'); }
  },
  'set-status': async (btn) => {
    try {
      await api(`/api/orders/${btn.dataset.id}`, { method: 'PATCH', body: { status: btn.dataset.status } });
      closeModal();
      toast('Order updated.', 'ok');
      setTab(App.tab);
    } catch (err) { toast(err.message, 'error'); }
  },
  'delete-order': async (btn) => {
    if (!confirm('Delete this order? This cannot be undone.')) return;
    try {
      await api(`/api/orders/${btn.dataset.id}`, { method: 'DELETE' });
      closeModal();
      toast('Order deleted.');
      setTab(App.tab);
    } catch (err) { toast(err.message, 'error'); }
  },
  'new-ingredient': () => openModal('Add an ingredient', `
    <form data-form="ingredient" class="form-grid">
      <label class="field full">Name<input name="name" type="text" placeholder="gula" required></label>
      <label class="field">Unit you price in
        <select name="unit"><option value="g">g</option><option value="ml">ml</option>
          <option value="biji">biji</option><option value="kotak">kotak</option></select></label>
      <label class="field">Pack price (RM)<input name="pack_price" type="number" step="0.01" min="0" placeholder="3.20" required></label>
      <label class="field">Pack size<input name="pack_size" type="number" step="0.001" min="0.001" placeholder="1000" required></label>
      <label class="field">Supplier (optional)<input name="supplier" type="text"></label>
      <div class="full row"><div class="spacer"></div><button class="btn" type="submit">Save ingredient</button></div>
    </form>`),
  'new-recipe': () => newRecipeModal(),
  'open-recipe': (btn) => openRecipe(btn.dataset.id).catch(e => toast(e.message, 'error')),
  'grocery-from-plan': () => {
    App.cache.groceryDate = App.cache.planDate || todayISO();
    App.cache.groceryMode = 'day';
    setTab('grocery');
  },
  'grocery-mode': (btn) => { App.cache.groceryMode = btn.dataset.mode; VIEWS.grocery(); },
  'new-thread': () => newThreadModal(),
  'open-thread': (btn) => { App.inbox.threadId = Number(btn.dataset.id); VIEWS.inbox(); },
  'copy-link': async (btn) => {
    const link = location.origin + '/chat.html?t=' + btn.dataset.token;
    try { await navigator.clipboard.writeText(link); toast('Customer link copied.', 'ok'); }
    catch { openModal('Customer link', `<div class="secret-box">${esc(link)}</div>`); }
  },
  invite: () => openModal('Invite a team member', `
    <form data-form="invite" style="display:flex;flex-direction:column;gap:10px">
      <label class="field">Email<input name="email" type="email" required placeholder="partner@kuih.my"></label>
      <div class="hint">They get OWNER permissions: everything in this business.</div>
      <div class="row"><div class="spacer"></div><button class="btn" type="submit">Invite</button></div>
    </form>`),
  'change-plan': async (btn) => {
    try {
      const res = await api('/api/billing/checkout', { method: 'POST', body: { plan: btn.dataset.plan } });
      if (res.checkout_url) location.href = res.checkout_url;
      else toast('Checkout created.');
    } catch (err) {
      if (err.code === 'payments_not_configured') {
        toast('Payments are not switched on. Contact support to change plan.', 'error');
      } else toast(err.message, 'error');
    }
  },
};

document.addEventListener('click', (event) => {
  const btn = event.target.closest('[data-action]');
  if (!btn) return;
  const fn = actions[btn.dataset.action];
  if (fn) { event.preventDefault(); fn(btn); }
});

/* ------------------------------------------------------------------ forms */

const forms = {
  product: async (form) => {
    const data = new FormData(form);
    const body = {
      name: data.get('name'),
      price: Number(data.get('price')),
      category: data.get('category') || 'Food',
      description: data.get('description') || null,
      image_url: data.get('image_url') || null,
    };
    const id = form.dataset.id;
    if (id) await api('/api/products/' + id, { method: 'PATCH', body });
    else await api('/api/products', { method: 'POST', body });
    closeModal();
    toast('Menu saved.', 'ok');
    VIEWS.settings();
  },
  business: async (form) => {
    const data = new FormData(form);
    await api('/api/settings/business', { method: 'PATCH', body: {
      name: data.get('name'),
      tagline: data.get('tagline') || null,
      phone: data.get('phone') || null,
      address: data.get('address') || null,
      hours: data.get('hours') || null,
    }});
    toast('Shop profile saved.', 'ok');
    VIEWS.settings();
  },
  order: (form) => submitOrder(form),
  parse: async (form) => {
    const box = form.querySelector('textarea');
    $('#parseText') || null;
    await runParse();
  },
  costing: (form) => submitCosting(form),
  recipe: (form) => submitRecipe(form),
  'recipe-item': async (form) => {
    const data = new FormData(form);
    const qty = Number(data.get('iqty_0'));
    const ingredientId = Number(data.get('ing_0'));
    if (!ingredientId || !(qty > 0)) throw new Error('Choose an ingredient and a quantity.');
    await api(`/api/recipes/${form.dataset.id}/items`, {
      method: 'POST', body: { ingredient_id: ingredientId, quantity: qty },
    });
    closeModal();
    toast('Ingredient added.', 'ok');
    setTab('recipes');
  },
  ingredient: async (form) => {
    const data = new FormData(form);
    await api('/api/ingredients', { method: 'POST', body: {
      name: data.get('name'), unit: data.get('unit'),
      pack_price: Number(data.get('pack_price')), pack_size: Number(data.get('pack_size')),
      supplier: data.get('supplier') || null,
    }});
    closeModal();
    toast('Ingredient saved.', 'ok');
    setTab('recipes');
  },
  reply: async (form) => {
    const body = new FormData(form).get('body');
    if (!body || !body.trim()) return;
    try {
      await api(`/api/threads/${form.dataset.id}/reply`, { method: 'POST', body: { body } });
      VIEWS.inbox();
    } catch (err) { toast(err.message, 'error'); }
  },
  thread: async (form) => {
    const name = new FormData(form).get('customer_name');
    try {
      const res = await api('/api/threads', { method: 'POST', body: { customer_name: name } });
      const link = location.origin + res.thread.public_path;
      openModal('Customer link', `
        <p class="small">Send this link to ${esc(name)}. They open it on their phone and write their order.</p>
        <div class="secret-box">${esc(link)}</div>
        <div class="row" style="margin-top:12px"><div class="spacer"></div>
          <button class="btn" data-action="copy-text" data-text="${esc(link)}">Copy link</button></div>`);
      App.inbox.threadId = res.thread.id;
    } catch (err) { toast(err.message, 'error'); }
  },
  'ai-settings': async (form) => {
    const data = new FormData(form);
    try {
      await api('/api/ai/settings', { method: 'PATCH', body: {
        ai_provider: data.get('ai_provider'),
        ai_model: data.get('ai_model'),
        ai_budget_rm: Number(data.get('ai_budget_rm')),
      }});
      toast('AI settings saved. The next call uses them.', 'ok');
      await refreshChip();
      VIEWS.settings();
    } catch (err) { toast(err.message, 'error'); }
  },
  invite: async (form) => {
    const email = new FormData(form).get('email');
    try {
      await api('/api/team', { method: 'POST', body: { email, role: 'OWNER' } });
      closeModal();
      toast('Invited. They can sign in with a magic link.', 'ok');
      VIEWS.settings();
    } catch (err) { toast(err.message, 'error'); }
  },
};

actions['copy-text'] = async (btn) => {
  try { await navigator.clipboard.writeText(btn.dataset.text); toast('Copied.', 'ok'); }
  catch { toast('Select the link and copy it.', 'error'); }
};

document.addEventListener('submit', async (event) => {
  const form = event.target;
  const name = form.dataset.form;
  if (!name || !forms[name]) return;
  event.preventDefault();
  const submit = form.querySelector('button[type=submit]');
  if (submit) submit.disabled = true;
  try {
    await forms[name](form);
  } catch (err) {
    toast(err.message, 'error');
  } finally {
    if (submit) submit.disabled = false;
  }
});

/* ------------------------------------------------------------------- nav */

$$('#nav button').forEach(button => {
  button.addEventListener('click', () => setTab(button.dataset.tab));
});

window.addEventListener('hashchange', () => {
  const tab = (location.hash || '#orders').slice(1);
  if (TABS.includes(tab) && tab !== App.tab) setTab(tab);
});

$('#bell').addEventListener('click', (event) => {
  event.stopPropagation();
  const panel = $('#bellPanel');
  panel.hidden = !panel.hidden;
  if (!panel.hidden) loadNotifications();
});

document.addEventListener('click', (event) => {
  if (!event.target.closest('.bell-wrap')) {
    const panel = $('#bellPanel');
    if (panel) panel.hidden = true;
  }
});

$$('#langSeg button').forEach(button => button.addEventListener('click', () => {
  setLang(button.dataset.lang);
  applyLang();
  setTab(App.tab);
}));

$('#signOut').addEventListener('click', async () => {
  try { await api('/api/auth/logout', { method: 'POST' }); } catch (err) { /* leaving anyway */ }
  location.href = '/login';
});

$('#exportLink').addEventListener('click', (event) => {
  event.preventDefault();
  toast('Preparing your export…');
  location.href = '/api/export?format=json';
});

boot();
