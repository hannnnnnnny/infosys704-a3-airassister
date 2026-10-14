'use strict';
/* AirAssist sign-in. The access token lives only in the token variable below, so a page
   refresh starts a fresh sign-in. The page itself is loaded first, which is what establishes
   the anonymous demo session on the hosted deployment. */
let token = null;
const state = {
  view: 'signin', role: null, displayName: null, username: '', error: null, busy: false,
  me: null, loading: false, loadError: null,
  email: '', confirm: false, fieldErrors: {email: null, confirm: null},
  submitting: false, requestKey: null, retryBusy: false,
  receiptBusy: false, receiptError: null,
};
const main = document.querySelector('main');

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => (
    {'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
}

async function api(path, {method = 'GET', body} = {}) {
  const headers = {};
  if (token) headers.Authorization = 'Bearer ' + token;
  if (body !== undefined) headers['Content-Type'] = 'application/json';
  let response;
  try {
    response = await fetch(path, {method, cache: 'no-store', credentials: 'same-origin',
      headers, body: body === undefined ? undefined : JSON.stringify(body)});
  } catch (error) {
    throw Object.assign(new Error('We could not reach the service. Check the connection and try again.'),
      {code: 'NETWORK_ERROR'});
  }
  let data;
  try {
    data = await response.json();
  } catch (error) {
    throw Object.assign(new Error('The service returned an unreadable response. Please try again.'),
      {code: 'INVALID_RESPONSE', status: response.status});
  }
  if (!response.ok) {
    if (response.status === 401 && path !== '/api/auth/login') {
      endSession('Your session has ended. Sign in again.');
      throw Object.assign(new Error('Your session has ended. Sign in again.'),
        {code: 'SESSION_ENDED', status: 401});
    }
    const message = data?.error?.message || 'The request could not be completed. Please try again.';
    throw Object.assign(new Error(message), {code: data?.error?.code || 'REQUEST_FAILED', status: response.status});
  }
  return data;
}

function signInMessage(error) {
  if (error?.status === 401) return 'Username or password is incorrect.';
  if (error?.status === 429) return 'Too many attempts. Try again in a few minutes.';
  if (error?.status === 503) return "Sign-in isn't available right now.";
  return error?.message || 'Sign-in could not be completed. Please try again.';
}

async function signIn(username, password) {
  if (state.busy) return false;
  const name = String(username || '').trim();
  const secret = String(password || '');
  state.username = name;
  if (!name || !secret) {
    state.error = 'Enter your username and password.';
    render();
    return false;
  }
  state.busy = true;
  state.error = null;
  render();
  try {
    const data = await api('/api/auth/login', {method: 'POST', body: {username: name, password: secret}});
    token = String(data.token || '');
    state.role = data.role === 'staff' ? 'staff' : 'passenger';
    state.displayName = String(data.displayName || '');
    state.view = state.role;
    state.username = '';
    state.busy = false;
    state.error = null;
    if (state.role === 'passenger') {
      state.me = null;
      await loadMe();
    } else {
      render();
    }
    return true;
  } catch (error) {
    state.busy = false;
    state.error = signInMessage(error);
    render();
    return false;
  }
}

function endSession(message) {
  token = null;
  state.view = 'signin';
  state.role = null;
  state.displayName = null;
  state.username = '';
  state.busy = false;
  state.me = null;
  state.loading = false;
  state.loadError = null;
  state.email = '';
  state.confirm = false;
  state.fieldErrors = {email: null, confirm: null};
  state.submitting = false;
  state.requestKey = null;
  state.retryBusy = false;
  state.receiptBusy = false;
  state.receiptError = null;
  state.error = message || null;
  render();
}

function signOut() {
  endSession(null);
}

function messageBlock() {
  return state.error ? `<p class="form-error" role="alert">${esc(state.error)}</p>` : '';
}

function signInView() {
  return `<section class="panel">
    <h1>Kia ora, sign in</h1>
    <form id="signin-form" novalidate>
      <div class="field">
        <label for="username">Username</label>
        <input id="username" name="username" type="text" value="${esc(state.username)}" autocomplete="username" spellcheck="false"${state.busy ? ' disabled' : ''}>
      </div>
      <div class="field">
        <label for="password">Password</label>
        <input id="password" name="password" type="password" autocomplete="current-password"${state.busy ? ' disabled' : ''}>
      </div>
      ${messageBlock()}
      <button class="btn" type="submit"${state.busy ? ' disabled' : ''}>${state.busy ? 'Signing in…' : 'Sign in'}</button>
    </form>
    <p class="demo-accounts">Demo accounts: Mark.don (passenger) · admin (staff)</p>
  </section>`;
}

function areaView(title, copy) {
  return `<section class="panel"><h1>${esc(title)}</h1><p class="area-copy">${esc(copy)}</p></section>`;
}

/* --- passenger refund screens ------------------------------------------------------------ */

const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
  'July', 'August', 'September', 'October', 'November', 'December'];

function firstName(name) {
  const parts = String(name || '').trim().split(/\s+/).filter(Boolean);
  return parts.length ? parts[0] : 'there';
}

function formatAmount(amount, currency) {
  if (typeof amount !== 'number' || !Number.isFinite(amount)) return '';
  const value = amount.toFixed(2);
  const code = String(currency || '').trim();
  return code ? code + ' ' + value : value;
}

function formatDate(value) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value || ''));
  if (!match) return String(value || '');
  const month = MONTHS[Number(match[2]) - 1];
  return month ? `${Number(match[3])} ${month} ${match[1]}` : String(value || '');
}

/* The request key is created once when the request screen is shown and reused for retries of the
   same submission, so a repeated send stays idempotent. It is cleared only after a successful send. */
function prepareRequestKey() {
  if (!state.me || state.me.request) {
    state.requestKey = null;
    return;
  }
  if (!state.requestKey) state.requestKey = crypto.randomUUID();
}

async function loadMe() {
  state.loading = true;
  state.loadError = null;
  render();
  try {
    state.me = await api('/api/me');
    state.loading = false;
    prepareRequestKey();
    render();
  } catch (error) {
    state.loading = false;
    if (state.view !== 'passenger') return;
    state.loadError = error.message || 'We could not load your booking. Please try again.';
    render();
  }
}

async function retryMe() {
  if (state.retryBusy) return;
  state.retryBusy = true;
  state.error = null;
  state.loadError = null;
  await loadMe();
  state.retryBusy = false;
  render();
}

function validateRefund() {
  const email = String(state.email || '').trim();
  const errors = {email: null, confirm: null};
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) errors.email = 'Enter a valid email address.';
  if (!state.confirm) errors.confirm = 'Tick the box to confirm your details are correct.';
  state.fieldErrors = errors;
  return !errors.email && !errors.confirm;
}

async function submitRefund() {
  if (state.submitting) return;
  state.error = null;
  if (!validateRefund()) {
    render();
    return;
  }
  if (!state.requestKey) prepareRequestKey();
  if (!state.requestKey) {
    state.error = 'We could not start your request. Please try again.';
    render();
    return;
  }
  state.submitting = true;
  render();
  try {
    const data = await api('/api/refund-requests', {
      method: 'POST',
      body: {email: String(state.email || '').trim(), confirmed: true, requestKey: state.requestKey},
    });
    state.submitting = false;
    state.requestKey = null;
    if (state.me) state.me.request = data.request;
    state.error = null;
    render();
  } catch (error) {
    state.submitting = false;
    if (error.status === 409) {
      await loadMe();
      return;
    }
    if (state.view !== 'passenger') return;
    state.error = error.message || 'We could not send your request. Please try again.';
    render();
  }
}

async function downloadReceipt() {
  if (state.receiptBusy) return;
  state.receiptBusy = true;
  state.receiptError = null;
  render();
  try {
    const response = await fetch('/api/refund-requests/receipt', {
      cache: 'no-store', credentials: 'same-origin',
      headers: token ? {Authorization: 'Bearer ' + token} : {},
    });
    if (response.status === 401) {
      endSession('Your session has ended. Sign in again.');
      return;
    }
    if (!response.ok) throw new Error('We could not prepare your receipt. Please try again.');
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = 'airassist-receipt-' + ((state.me?.request?.reference) || 'refund') + '.json';
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    state.receiptBusy = false;
    render();
  } catch (error) {
    state.receiptBusy = false;
    if (state.view !== 'passenger') return;
    state.receiptError = error.message || 'We could not prepare your receipt. Please try again.';
    render();
  }
}

function emailField() {
  const error = state.fieldErrors.email;
  return `<div class="field">
    <label for="refund-email">Email</label>
    <input id="refund-email" name="email" type="email" value="${esc(state.email)}" autocomplete="email" spellcheck="false"${state.submitting ? ' disabled' : ''}${error ? ' aria-invalid="true" aria-describedby="refund-email-error"' : ''}>
    ${error ? `<p class="field-error" id="refund-email-error">${esc(error)}</p>` : ''}
  </div>`;
}

function confirmField() {
  const error = state.fieldErrors.confirm;
  return `<div class="field-check">
    <div class="check-row">
      <input id="refund-confirm" name="confirm" type="checkbox"${state.confirm ? ' checked' : ''}${state.submitting ? ' disabled' : ''}${error ? ' aria-invalid="true" aria-describedby="refund-confirm-error"' : ''}>
      <label for="refund-confirm">I confirm my details are correct</label>
    </div>
    ${error ? `<p class="field-error" id="refund-confirm-error">${esc(error)}</p>` : ''}
  </div>`;
}

function requestView() {
  const flight = state.me.flight || {};
  const quote = state.me.quote;
  const route = `<div class="route">
    <div class="route-end"><span class="route-code">${esc(flight.fromCode)}</span><span class="route-city">${esc(flight.fromCity)}</span></div>
    <span class="route-plane" aria-hidden="true">✈</span>
    <div class="route-end"><span class="route-code">${esc(flight.toCode)}</span><span class="route-city">${esc(flight.toCity)}</span></div>
  </div>`;
  const head = `<h1>Kia ora, ${esc(firstName(state.me.displayName))}</h1>
    <p class="lead">${esc(flight.flight)} on ${esc(formatDate(flight.date))} was cancelled. Sorry about that.</p>
    ${route}`;
  if (state.me.quoteError || !quote || typeof quote.amount !== 'number') {
    return `<section class="panel">${head}
      <div class="notice">
        <p>We couldn't load your refund amount. Try again.</p>
        <button class="btn" type="button" id="retry-quote"${state.retryBusy ? ' disabled' : ''}>${state.retryBusy ? 'Trying…' : 'Retry'}</button>
      </div>
      ${messageBlock()}
    </section>`;
  }
  return `<section class="panel">${head}
    <div class="refund-box">
      <span class="refund-label">Full refund to your original payment</span>
      <span class="refund-amount">${esc(formatAmount(quote.amount, quote.currency))}</span>
    </div>
    <form id="refund-form" novalidate>
      ${emailField()}
      ${confirmField()}
      ${messageBlock()}
      <button class="btn" type="submit"${state.submitting ? ' disabled' : ''}>${state.submitting ? 'Sending…' : 'Request full refund'}</button>
    </form>
  </section>`;
}

function statusCopy(request) {
  const status = String(request.status || 'pending');
  const amount = formatAmount(request.amount, request.currency);
  if (status === 'approved') return {
    status, icon: '✓', headline: 'Refund approved',
    sentence: amount ? amount + ' will go back to your original payment.' : 'Your refund was approved.',
    pill: 'Approved', pillClass: 'pill-approved',
  };
  if (status === 'declined') return {
    status, icon: '✕', headline: 'Refund declined',
    sentence: request.decisionNote || 'This request was declined.',
    pill: 'Declined', pillClass: 'pill-declined',
  };
  return {
    status: 'pending', icon: '⏳', headline: 'Request sent',
    sentence: 'Our refunds team will review it shortly.',
    pill: 'Awaiting approval', pillClass: 'pill-pending',
  };
}

function statusView() {
  const request = state.me.request;
  const copy = statusCopy(request);
  return `<section class="panel">
    <p class="status-icon status-${copy.status}" aria-hidden="true">${esc(copy.icon)}</p>
    <h1>${esc(copy.headline)}</h1>
    <p class="lead">${esc(copy.sentence)}</p>
    <dl class="details">
      <div class="detail-row"><dt>Status</dt><dd><span class="pill ${copy.pillClass}">${esc(copy.pill)}</span></dd></div>
      <div class="detail-row"><dt>Amount</dt><dd>${esc(formatAmount(request.amount, request.currency))}</dd></div>
      <div class="detail-row"><dt>Reference</dt><dd>${esc(request.reference)}</dd></div>
    </dl>
    <p class="receipt-row"><a class="receipt-link" href="#receipt" id="download-receipt">${state.receiptBusy ? 'Preparing receipt…' : 'Download receipt'}</a></p>
    ${state.receiptError ? `<p class="form-error" role="alert">${esc(state.receiptError)}</p>` : ''}
  </section>`;
}

function passengerView() {
  if (state.me) return state.me.request ? statusView() : requestView();
  if (state.loading) return `<section class="panel"><p class="area-copy">Loading your booking…</p></section>`;
  return `<section class="panel">
    <h1>Kia ora</h1>
    <p class="area-copy">We couldn't load your booking details.</p>
    ${state.loadError ? `<p class="form-error" role="alert">${esc(state.loadError)}</p>` : ''}
    <button class="btn" type="button" id="retry-me"${state.retryBusy ? ' disabled' : ''}>${state.retryBusy ? 'Trying…' : 'Retry'}</button>
  </section>`;
}

function staffView() {
  return areaView('Staff area', 'Refund requests to review will appear here.');
}

function accountMarkup() {
  return `<span class="account-name">${esc(state.displayName)}</span><a class="signout" href="#sign-out" id="sign-out">Sign out</a>`;
}

function bindForms() {
  const form = document.querySelector('#signin-form');
  if (form) form.addEventListener('submit', event => {
    event.preventDefault();
    signIn(form.elements.username.value, form.elements.password.value);
  });
  const out = document.querySelector('#sign-out');
  if (out) out.addEventListener('click', event => {
    event.preventDefault();
    signOut();
  });
  bindPassenger();
}

function bindPassenger() {
  const form = document.querySelector('#refund-form');
  if (form) {
    form.addEventListener('submit', event => {
      event.preventDefault();
      submitRefund();
    });
    form.addEventListener('input', event => {
      const target = event.target;
      if (!target || !target.name) return;
      if (target.name === 'email') state.email = target.value;
      if (target.name === 'confirm') state.confirm = target.checked;
      const key = target.name === 'email' ? 'email' : target.name === 'confirm' ? 'confirm' : null;
      if (key && state.fieldErrors[key]) {
        state.fieldErrors[key] = null;
        const note = document.querySelector(key === 'email' ? '#refund-email-error' : '#refund-confirm-error');
        if (note && note.remove) note.remove();
        if (target.removeAttribute) target.removeAttribute('aria-invalid');
      }
    });
  }
  const retry = document.querySelector('#retry-quote') || document.querySelector('#retry-me');
  if (retry) retry.addEventListener('click', event => {
    event.preventDefault();
    retryMe();
  });
  const receipt = document.querySelector('#download-receipt');
  if (receipt) receipt.addEventListener('click', event => {
    event.preventDefault();
    downloadReceipt();
  });
}

function render() {
  main.innerHTML = state.view === 'passenger' ? passengerView() : state.view === 'staff' ? staffView() : signInView();
  const account = document.querySelector('#account');
  if (account) account.innerHTML = state.view === 'signin' ? '' : accountMarkup();
  document.title = 'AirAssist · ' + (state.view === 'signin' ? 'Sign in' : state.role === 'staff' ? 'Staff area' : 'Passenger area');
  bindForms();
}

render();
