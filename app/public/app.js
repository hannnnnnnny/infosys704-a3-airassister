'use strict';
/* AirAssist sign-in. The access token lives only in the token variable below, so a page
   refresh starts a fresh sign-in. The page itself is loaded first, which is what establishes
   the anonymous demo session on the hosted deployment. */
let token = null;
const state = {
  view: 'signin', role: null, displayName: null, username: '', error: null, busy: false,
  me: null, loading: false, loadError: null, selectedBooking: null, refreshing: false,
  email: '', phone: '', confirm: false, fieldErrors: {phone: null, email: null, contact: null, confirm: null},
  submitting: false, requestKey: null, requestKeys: {}, retryBusy: false,
  receiptBusy: false, receiptError: null,
  staff: {
    requests: [],
    loading: false,
    error: null,
    notice: null,
    pendingCount: 0,
    expanded: null,
    deciding: null,
    decisionError: {},
    decisionNote: {},
    decisionBusy: {},
  },
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
      state.selectedBooking = null;
      state.refreshing = false;
      state.email = '';
      state.phone = '';
      state.confirm = false;
      state.fieldErrors = {phone: null, email: null, contact: null, confirm: null};
      state.requestKey = null;
      state.requestKeys = {};
      await loadMe();
    } else {
      state.staff = {
        requests: [],
        loading: false,
        error: null,
        notice: null,
        pendingCount: 0,
        expanded: null,
        deciding: null,
        decisionError: {},
        decisionNote: {},
        decisionBusy: {},
        resetting: false,
        resetConfirm: false,
      };
      await loadStaffRequests();
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
  state.selectedBooking = null;
  state.refreshing = false;
  state.email = '';
  state.phone = '';
  state.confirm = false;
  state.fieldErrors = {phone: null, email: null, contact: null, confirm: null};
  state.submitting = false;
  state.requestKey = null;
  state.requestKeys = {};
  state.retryBusy = false;
  state.receiptBusy = false;
  state.receiptError = null;
  state.staff = {
    requests: [],
    loading: false,
    error: null,
    notice: null,
    pendingCount: 0,
    expanded: null,
    deciding: null,
    decisionError: {},
    decisionNote: {},
    decisionBusy: {},
    resetting: false,
    resetConfirm: false,
  };
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

/* The request key is created once per booking when its request screen is shown and reused
   for retries of the same submission, so a repeated send stays idempotent. */
function tripList() {
  const trips = state.me && Array.isArray(state.me.trips) ? state.me.trips : [];
  return [...trips].sort((a, b) => String(a?.flight?.date || '') < String(b?.flight?.date || '') ? -1 : 1);
}

function selectedTrip() {
  const trips = tripList();
  return trips.find(trip => String(trip?.booking?.reference || '') === String(state.selectedBooking || '')) || null;
}

function tripRequestStatus(trip) {
  if (trip?.request) return String(trip.request.status || 'pending');
  if (trip?.refundable) return 'available';
  return 'ontime';
}

function tripPill(trip) {
  const status = tripRequestStatus(trip);
  if (status === 'pending') return {text: 'Awaiting approval', cls: 'pill-pending'};
  if (status === 'approved') return {text: 'Refunded', cls: 'pill-approved'};
  if (status === 'declined') return {text: 'Declined', cls: 'pill-declined'};
  if (status === 'available') return {text: 'Refund available', cls: 'pill-available'};
  return {text: 'On time', cls: 'pill-ontime'};
}

function tripAmount(trip) {
  if (trip?.request && typeof trip.request.amount === 'number') {
    return formatAmount(trip.request.amount, trip.request.currency);
  }
  if (trip?.quote && typeof trip.quote.amount === 'number') {
    return formatAmount(trip.quote.amount, trip.quote.currency);
  }
  return '';
}

function paymentLine(method) {
  if (!method || !method.brand || !method.last4) return '';
  return `${esc(method.brand)} •••• ${esc(method.last4)}`;
}

function tripPaymentMethod(trip) {
  return trip?.paymentMethod || trip?.booking?.paymentMethod || null;
}

function requestPaymentMethod(request) {
  return request?.paymentMethod || null;
}

function requestContact(request) {
  const contact = request?.contact || {};
  return {
    phone: String(contact.phone || request?.phone || ''),
    email: String(contact.email || request?.email || ''),
  };
}

function openTrip(bookingReference) {
  state.selectedBooking = String(bookingReference || '');
  state.error = null;
  state.receiptError = null;
  prepareRequestKey();
  render();
  return refreshMe();
}

function goHome() {
  state.selectedBooking = null;
  state.error = null;
  state.receiptError = null;
  render();
  return refreshMe();
}

function prepareRequestKey() {
  const trip = selectedTrip();
  if (!trip || !trip.refundable || trip.request) {
    state.requestKey = null;
    return;
  }
  const ref = String(trip.booking.reference || '');
  if (!state.requestKeys[ref]) state.requestKeys[ref] = crypto.randomUUID();
  state.requestKey = state.requestKeys[ref];
}

async function refreshMe() {
  if (state.view !== 'passenger') return;
  state.refreshing = true;
  state.loadError = null;
  render();
  try {
    const fresh = await api('/api/me');
    state.me = fresh;
    state.refreshing = false;
    if (state.selectedBooking && !selectedTrip()) state.selectedBooking = null;
    prepareRequestKey();
    render();
  } catch (error) {
    state.refreshing = false;
    if (state.view !== 'passenger') return;
    if (error && error.code === 'SESSION_ENDED') return;
    state.error = (error && error.message) || 'We could not update your trips. Please try again.';
    render();
  }
}

async function loadMe() {
  state.loading = true;
  state.loadError = null;
  render();
  try {
    state.me = await api('/api/me');
    state.loading = false;
    if (state.selectedBooking && !selectedTrip()) state.selectedBooking = null;
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

function validPhone(value) {
  const text = String(value || '').trim();
  if (!text) return false;
  if (text.length < 7 || text.length > 20) return false;
  if (!/^[0-9+\-() ]+$/.test(text)) return false;
  return (text.match(/[0-9]/g) || []).length >= 7;
}

function validateRefund() {
  const phone = String(state.phone || '').trim();
  const email = String(state.email || '').trim();
  const errors = {phone: null, email: null, contact: null, confirm: null};
  if (phone && !validPhone(phone)) errors.phone = 'Enter a valid mobile number.';
  if (email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) errors.email = 'Enter a valid email address.';
  if (!phone && !email) errors.contact = 'Enter at least one contact detail.';
  if (!state.confirm) errors.confirm = 'Tick the box to confirm your details are correct.';
  state.fieldErrors = errors;
  return !errors.phone && !errors.email && !errors.contact && !errors.confirm;
}

async function submitRefund() {
  if (state.submitting) return;
  state.error = null;
  if (!validateRefund()) {
    render();
    return;
  }
  const trip = selectedTrip();
  const bookingReference = trip ? String(trip.booking.reference || '') : '';
  if (!bookingReference) {
    state.error = 'Choose a trip before requesting a refund.';
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
      body: {
        bookingReference,
        contact: {phone: String(state.phone || '').trim(), email: String(state.email || '').trim()},
        confirmed: true, requestKey: state.requestKey,
      },
    });
    state.submitting = false;
    delete state.requestKeys[bookingReference];
    state.requestKey = null;
    state.error = null;
    await loadMe();
    state.selectedBooking = bookingReference;
    const current = selectedTrip();
    if (current && !current.request && data && data.request) current.request = data.request;
    prepareRequestKey();
    render();
  } catch (error) {
    state.submitting = false;
    if (error.status === 409) {
      await loadMe();
      const trips = tripList();
      if (trips.some(t => String(t?.booking?.reference || '') === bookingReference)) {
        state.selectedBooking = bookingReference;
      }
      render();
      return;
    }
    if (state.view !== 'passenger') { render(); return; }
    state.error = error.message || 'We could not send your request. Please try again.';
    render();
  }
}

async function downloadReceipt() {
  const trip = selectedTrip();
  const bookingReference = trip ? String(trip.booking.reference || trip?.request?.bookingReference || '') : '';
  if (!bookingReference) {
    state.receiptError = 'Choose a trip before downloading a receipt.';
    render();
    return;
  }
  if (state.receiptBusy) return;
  state.receiptBusy = true;
  state.receiptError = null;
  render();
  try {
    const response = await fetch('/api/refund-requests/receipt?booking=' + encodeURIComponent(bookingReference), {
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
    link.download = 'airassist-receipt-' + ((trip?.request?.reference) || 'refund') + '.json';
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

function contactFields() {
  const errors = state.fieldErrors || {};
  return `<fieldset class="contact-group">
    <legend>How can we reach you?</legend>
    <p class="field-hint" id="contact-hint">Enter at least one.</p>
    ${errors.contact ? `<p class="field-error" id="contact-error" role="alert">${esc(errors.contact)}</p>` : ''}
    <div class="field">
      <label for="refund-phone">Mobile</label>
      <input id="refund-phone" name="phone" type="tel" value="${esc(state.phone)}" autocomplete="tel" spellcheck="false"${state.submitting ? ' disabled' : ''}${errors.phone ? ' aria-invalid="true" aria-describedby="refund-phone-error"' : ''}>
      ${errors.phone ? `<p class="field-error" id="refund-phone-error">${esc(errors.phone)}</p>` : ''}
    </div>
    <div class="field">
      <label for="refund-email">Email</label>
      <input id="refund-email" name="email" type="email" value="${esc(state.email)}" autocomplete="email" spellcheck="false"${state.submitting ? ' disabled' : ''}${errors.email ? ' aria-invalid="true" aria-describedby="refund-email-error"' : ''}>
      ${errors.email ? `<p class="field-error" id="refund-email-error">${esc(errors.email)}</p>` : ''}
    </div>
  </fieldset>`;
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

function backLink() {
  return `<button class="back-link" type="button" id="back-trips">← My trips</button>`;
}

function refreshNote() {
  return state.refreshing ? '<p class="area-copy" role="status">Updating your trips…</p>' : '';
}

function homeView() {
  const trips = tripList();
  const needAction = trips.filter(trip => trip?.refundable && !trip?.request).length;
  const inReview = trips.filter(trip => String(trip?.request?.status || '') === 'pending').length;
  const refunded = trips.filter(trip => String(trip?.request?.status || '') === 'approved').length;
  const cards = trips.map(trip => {
    const booking = trip.booking || {};
    const flight = trip.flight || booking || {};
    const pill = tripPill(trip);
    const amount = tripAmount(trip);
    const ref = String(booking.reference || '');
    return `<button type="button" class="trip-card" data-booking="${esc(ref)}" aria-label="${esc((flight.fromCode || '') + ' to ' + (flight.toCode || '') + ', ' + pill.text)}">
      <span class="trip-route">${esc(flight.fromCode || '')} → ${esc(flight.toCode || '')}</span>
      <span class="trip-line">${esc(formatDate(flight.date))} · ${esc(flight.flight || '')} · ${esc(ref)} · ${esc(flight.flightStatus || '')}</span>
      <span class="trip-meta"><span class="pill ${esc(pill.cls)}">${esc(pill.text)}</span>${amount ? `<span class="trip-amount">${esc(amount)}</span>` : ''}</span>
    </button>`;
  }).join('');
  return `<section class="panel home-panel">
    <p class="eyebrow">My trips</p>
    <h1>Kia ora, ${esc(firstName(state.me.displayName))}</h1>
    <p class="lead">Your trips and refunds in one place.</p>
    ${refreshNote()}
    <div class="tiles">
      <div class="tile"><span class="tile-count">${esc(String(needAction))}</span><span class="tile-label">Need action</span></div>
      <div class="tile"><span class="tile-count">${esc(String(inReview))}</span><span class="tile-label">In review</span></div>
      <div class="tile"><span class="tile-count">${esc(String(refunded))}</span><span class="tile-label">Refunded</span></div>
    </div>
    ${trips.length ? `<div class="trips-list">${cards}</div>` : '<p class="area-copy">No trips yet.</p>'}
    ${messageBlock()}
  </section>`;
}

function requestView(trip) {
  const flight = trip.flight || trip.booking || {};
  const booking = trip.booking || {};
  const quote = trip.quote;
  const method = tripPaymentMethod(trip);
  const destination = paymentLine(method);
  const route = `<div class="route">
    <div class="route-end"><span class="route-code">${esc(flight.fromCode)}</span><span class="route-city">${esc(flight.fromCity)}</span></div>
    <span class="route-plane" aria-hidden="true">✈</span>
    <div class="route-end"><span class="route-code">${esc(flight.toCode)}</span><span class="route-city">${esc(flight.toCity)}</span></div>
  </div>`;
  const head = `${backLink()}
    ${refreshNote()}
    <h1>Kia ora, ${esc(firstName(state.me.displayName))}</h1>
    <p class="lead">${esc(flight.flight)} on ${esc(formatDate(flight.date))} was cancelled. Sorry about that.</p>
    ${route}`;
  if (trip.quoteError || !quote || typeof quote.amount !== 'number') {
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
      ${destination ? `<span class="refund-destination">Refund to ${destination}</span>
      <span class="refund-note">The card you used to book this ticket.</span>` : ''}
    </div>
    <form id="refund-form" novalidate>
      ${contactFields()}
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

function statusView(trip) {
  const request = trip.request;
  const copy = statusCopy(request);
  const destination = paymentLine(requestPaymentMethod(request));
  const contact = requestContact(request);
  const followUp = contact.phone || contact.email;
  const declinedExtra = String(request.status || '') === 'declined' && followUp
    ? `<p class="contact-note">Our customer service team will contact you at ${esc(followUp)}.</p>` : '';
  return `<section class="panel">
    <div class="back-row">${backLink()}</div>
    ${refreshNote()}
    <p class="status-icon status-${copy.status}" aria-hidden="true">${esc(copy.icon)}</p>
    <h1>${esc(copy.headline)}</h1>
    <p class="lead">${esc(copy.sentence)}</p>
    ${declinedExtra}
    <dl class="details">
      <div class="detail-row"><dt>Status</dt><dd><span class="pill ${copy.pillClass}">${esc(copy.pill)}</span></dd></div>
      <div class="detail-row"><dt>Amount</dt><dd>${esc(formatAmount(request.amount, request.currency))}</dd></div>
      ${destination ? `<div class="detail-row"><dt>Refund to</dt><dd>${destination}</dd></div>` : ''}
      <div class="detail-row"><dt>Reference</dt><dd>${esc(request.reference)}</dd></div>
    </dl>
    ${messageBlock()}
    <p class="receipt-row"><a class="receipt-link" href="#receipt" id="download-receipt">${state.receiptBusy ? 'Preparing receipt…' : 'Download receipt'}</a></p>
    ${state.receiptError ? `<p class="form-error" role="alert">${esc(state.receiptError)}</p>` : ''}
  </section>`;
}

function onTimeView(trip) {
  const flight = trip.flight || trip.booking || {};
  return `<section class="panel">
    ${backLink()}
    ${refreshNote()}
    <h1>${esc(flight.fromCode || '')} → ${esc(flight.toCode || '')}</h1>
    <p class="lead">Your flight is on time. Nothing to do here.</p>
    <dl class="details">
      <div class="detail-row"><dt>Flight</dt><dd>${esc(flight.flight || '')}</dd></div>
      <div class="detail-row"><dt>Date</dt><dd>${esc(formatDate(flight.date))}</dd></div>
      <div class="detail-row"><dt>Booking</dt><dd>${esc(trip?.booking?.reference || '')}</dd></div>
    </dl>
    ${messageBlock()}
  </section>`;
}

function passengerView() {
  if (state.me && Array.isArray(state.me.trips)) {
    if (!state.selectedBooking) return homeView();
    const trip = selectedTrip();
    if (!trip) return homeView();
    if (trip.request) return statusView(trip);
    if (trip.refundable) return requestView(trip);
    return onTimeView(trip);
  }
  if (state.me) return homeView();
  if (state.loading) return `<section class="panel"><p class="area-copy">Loading your booking…</p></section>`;
  return `<section class="panel">
    <h1>Kia ora</h1>
    <p class="area-copy">We couldn't load your booking details.</p>
    ${state.loadError ? `<p class="form-error" role="alert">${esc(state.loadError)}</p>` : ''}
    <button class="btn" type="button" id="retry-me"${state.retryBusy ? ' disabled' : ''}>${state.retryBusy ? 'Trying…' : 'Retry'}</button>
  </section>`;
}

function isNewRequest(createdAt) {
  if (!createdAt) return false;
  const created = Date.parse(createdAt);
  if (!Number.isFinite(created)) return false;
  const now = Date.now();
  const oneHour = 60 * 60 * 1000;
  return now - created <= oneHour;
}

function routePillLabel(route) {
  if (String(route || '').toLowerCase() === 'fast_track') return 'Fast track';
  return 'Specialist';
}

function routePillClass(route) {
  if (String(route || '').toLowerCase() === 'fast_track') return 'staff-route-fast';
  return 'staff-route-specialist';
}

function statusPillMarkup(status) {
  const s = String(status || '');
  if (s === 'approved') return `<span class="pill pill-approved">Approved</span>`;
  if (s === 'declined') return `<span class="pill pill-declined">Declined</span>`;
  return '';
}

function staffHeaderButton(request, id, expanded) {
  const name = esc(request.passengerName || '');
  const newPill = isNewRequest(request.createdAt) ? ' <span class="staff-pill-new">New</span>' : '';
  const amountText = formatAmount(request.amount, request.currency);
  const line = `Flight disruption · ${esc(amountText)}`;
  const status = String(request.status || '');
  if (status !== 'pending') {
    const pill = statusPillMarkup(status);
    return `<button type="button" class="staff-row-header staff-row-header--processed" disabled aria-disabled="true">
      <span class="staff-row-main">
        <span class="staff-row-name">${name}${newPill}</span>
        <span class="staff-row-sub">${line}</span>
      </span>
      <span class="staff-row-end">${pill}</span>
    </button>`;
  }
  const chevron = `<span class="staff-chevron" aria-hidden="true">›</span>`;
  return `<button type="button" class="staff-row-header" data-ref="${esc(request.reference)}" aria-expanded="${expanded ? 'true' : 'false'}" aria-controls="${esc(id)}" id="${esc(id)}-btn">
      <span class="staff-row-main">
        <span class="staff-row-name">${name}${newPill}</span>
        <span class="staff-row-sub">${line}</span>
      </span>
      <span class="staff-row-end">${chevron}</span>
    </button>`;
}

function expandPanel(request, id, expanded) {
  const status = String(request.status || '');
  if (status !== 'pending') return '';
  const flight = request.flight || {};
  const routePart = `${esc(flight.flight || '')} ${esc(flight.fromCode || '')} → ${esc(flight.toCode || '')}`.trim();
  const datePart = flight.date ? `, ${esc(formatDate(flight.date))}` : '';
  const statusText = flight.flightStatus ? esc(flight.flightStatus) : '';
  const flightStatusPart = statusText ? ` · ${statusText}` : '';
  const fullRefundPart = request.refundType === 'full' ? ' · full refund' : '';
  const flightLine = routePart + datePart + flightStatusPart + fullRefundPart;
  const routeLabel = routePillLabel(request.route);
  const routeClass = routePillClass(request.route);
  const sapLine = `SAP credit memo ${request.sapDocument || ''} · ${formatAmount(request.amount, request.currency)}`;
  const ref = request.reference;
  const busy = state.staff.decisionBusy && state.staff.decisionBusy[ref];
  const deciding = (state.staff.deciding && state.staff.deciding.reference === ref)
    ? state.staff.deciding.decision : null;
  const decisionError = (state.staff.decisionError && state.staff.decisionError[ref]) || '';
  const note = (state.staff.decisionNote && state.staff.decisionNote[ref]) || '';
  let controls = '';
  if (deciding === 'approve') {
    controls = `<div class="staff-decision staff-decision--approve" role="group" aria-label="Approve request">
      <p class="staff-confirm">Approve ${esc(formatAmount(request.amount, request.currency))} for ${esc(request.passengerName || '')}?</p>
      ${decisionError ? `<p class="staff-field-error" role="alert">${esc(decisionError)}</p>` : ''}
      <div class="staff-inline-actions">
        <button type="button" class="btn staff-btn-approve-confirm" data-action="approve-confirm" data-ref="${esc(ref)}"${busy ? ' disabled' : ''}>${busy ? 'Approving…' : 'Yes, approve'}</button>
        <button type="button" class="btn btn-secondary staff-btn-cancel" data-action="cancel-decision" data-ref="${esc(ref)}"${busy ? ' disabled' : ''}>Cancel</button>
      </div>
    </div>`;
  } else if (deciding === 'decline') {
    controls = `<div class="staff-decision staff-decision--decline" role="group" aria-label="Decline request">
      <div class="staff-field">
        <label for="${esc(id)}-note">Reason (shown to the passenger)</label>
        <textarea id="${esc(id)}-note" class="staff-textarea" data-ref="${esc(ref)}" maxlength="500"${busy ? ' disabled' : ''}>${esc(note)}</textarea>
        ${decisionError ? `<p class="staff-field-error" role="alert">${esc(decisionError)}</p>` : ''}
      </div>
      <div class="staff-inline-actions">
        <button type="button" class="btn staff-btn-decline-confirm" data-action="decline-confirm" data-ref="${esc(ref)}"${busy ? ' disabled' : ''}>${busy ? 'Declining…' : 'Decline'}</button>
        <button type="button" class="btn btn-secondary staff-btn-cancel" data-action="cancel-decision" data-ref="${esc(ref)}"${busy ? ' disabled' : ''}>Cancel</button>
      </div>
    </div>`;
  } else {
    controls = `<div class="staff-inline-actions">
      <button type="button" class="btn" data-action="start-approve" data-ref="${esc(ref)}">Approve</button>
      <button type="button" class="btn btn-secondary" data-action="start-decline" data-ref="${esc(ref)}">Decline</button>
    </div>`;
  }
  return `<div class="staff-row-panel" id="${esc(id)}" role="region" aria-labelledby="${esc(id)}-btn"${expanded ? '' : ' hidden'}>
    <p class="staff-flight">${flightLine}</p>
    <span class="staff-route-pill ${esc(routeClass)}">${esc(routeLabel)}</span>
    <p class="staff-sap">${esc(sapLine)}</p>
    ${contactLines(request)}
    ${refundLine(request)}
    ${controls}
  </div>`;
}

function contactLines(request) {
  const contact = requestContact(request);
  const parts = [];
  if (contact.phone) parts.push(`<p class="staff-contact">Mobile ${esc(contact.phone)}</p>`);
  if (contact.email) parts.push(`<p class="staff-contact">Email ${esc(contact.email)}</p>`);
  if (!parts.length) parts.push('<p class="staff-contact">No contact details</p>');
  return parts.join('');
}

function refundLine(request) {
  const line = paymentLine(requestPaymentMethod(request));
  return line ? `<p class="staff-contact">Refund to ${line}</p>` : '';
}

async function loadStaffRequests(showError = true) {
  state.staff.loading = true;
  state.staff.error = null;
  render();
  try {
    const data = await api('/api/staff/requests');
    const requests = Array.isArray(data.requests) ? data.requests : [];
    const pending = requests.filter(r => String(r.status || '') === 'pending');
    state.staff.requests = requests;
    state.staff.pendingCount = pending.length;
    state.staff.loading = false;
    state.staff.error = null;
    state.staff.notice = null;
    render();
  } catch (error) {
    state.staff.loading = false;
    if (showError) {
      state.staff.error = error.message || 'We could not load requests. Please try again.';
    }
    render();
  }
}

async function retryStaffRequests() {
  await loadStaffRequests(true);
}

async function resetDemoData() {
  state.staff.resetting = true;
  state.staff.notice = null;
  render();
  try {
    const data = await api('/api/staff/demo-reset', {method: 'POST', body: {}});
    const requests = Array.isArray(data.requests) ? data.requests : [];
    const pending = requests.filter(r => String(r.status || '') === 'pending');
    state.staff.requests = requests;
    state.staff.pendingCount = pending.length;
    state.staff.expanded = null;
    state.staff.deciding = null;
    state.staff.resetting = false;
    state.staff.resetConfirm = false;
    state.staff.notice = 'Demo data reset.';
    render();
  } catch (error) {
    state.staff.resetting = false;
    state.staff.notice = error.message || 'Could not reset demo data. Please try again.';
    render();
  }
}

function staffView() {
  const s = state.staff;
  let content = '';
  if (s.loading) {
    content = '<p class="area-copy">Loading refund requests…</p>';
  } else if (s.error) {
    content = `<div class="notice"><p>${esc(s.error)}</p><button class="btn" type="button" id="staff-retry">Retry</button></div>`;
  } else if (!s.requests.length) {
    content = '<p class="area-copy">No refund requests yet</p>';
  } else {
    const items = [];
    for (let i = 0; i < s.requests.length; i++) {
      const req = s.requests[i];
      const ref = req.reference || ('r' + i);
      const id = 'staff-row-' + String(ref).replace(/[^a-zA-Z0-9_-]/g, '');
      const expanded = s.expanded === ref;
      const header = staffHeaderButton(req, id, expanded);
      const panel = expandPanel(req, id, expanded);
      items.push(`<div class="staff-row">${header}${panel}</div>`);
    }
    content = `<div class="staff-list">${items.join('')}</div>`;
  }
  const notice = s.notice ? `<p class="form-error" role="alert">${esc(s.notice)}</p>` : '';
  let resetMarkup = '';
  if (!s.resetConfirm) {
    resetMarkup = `<div class="staff-reset">
      <button type="button" class="btn btn-secondary" id="staff-reset-btn" data-action="reset-start">${s.resetting ? 'Resetting…' : 'Reset demo data'}</button>
    </div>`;
  } else {
    resetMarkup = `<div class="staff-reset-confirm" role="group" aria-label="Confirm demo data reset">
      <p class="staff-reset-text">This deletes all refund requests and restores the starting demo data. This can't be undone.</p>
      <div class="staff-inline-actions">
        <button type="button" class="btn btn-secondary" id="staff-reset-yes" data-action="reset-confirm" ${s.resetting ? ' disabled' : ''}>${s.resetting ? 'Resetting…' : 'Yes, reset'}</button>
        <button type="button" class="btn btn-secondary" id="staff-reset-cancel" data-action="reset-cancel" ${s.resetting ? ' disabled' : ''}>Cancel</button>
      </div>
    </div>`;
  }
  return `<section class="panel staff-panel">
    <h1>Refund requests</h1>
    <p class="staff-count">${esc(String(s.pendingCount))} to process</p>
    ${notice}
    ${content}
    ${resetMarkup}
  </section>`;
}

function accountMarkup() {
  const home = state.role === 'passenger' && state.view === 'passenger'
    ? '<a class="signout" href="#my-trips" id="my-trips">My trips</a>' : '';
  return `<span class="account-name">${esc(state.displayName)}</span>${home}<a class="signout" href="#sign-out" id="sign-out">Sign out</a>`;
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
  const home = document.querySelector('#my-trips');
  if (home) home.addEventListener('click', event => {
    event.preventDefault();
    goHome();
  });
  bindPassenger();
  bindStaff();
}

function bindPassenger() {
  const tripsList = document.querySelector('.trips-list');
  if (tripsList) tripsList.addEventListener('click', event => {
    const target = event.target;
    if (!target || typeof target.closest !== 'function') return;
    const card = target.closest('[data-booking]');
    if (!card || !card.dataset) return;
    event.preventDefault();
    openTrip(card.dataset.booking);
  });
  const back = document.querySelector('#back-trips');
  if (back) back.addEventListener('click', event => {
    event.preventDefault();
    goHome();
  });
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
      if (target.name === 'phone') state.phone = target.value;
      if (target.name === 'confirm') state.confirm = target.checked;
      const key = target.name === 'phone' ? 'phone' : target.name === 'email' ? 'email' : target.name === 'confirm' ? 'confirm' : null;
      if (key && state.fieldErrors[key]) {
        state.fieldErrors[key] = null;
        const selector = key === 'phone' ? '#refund-phone-error' : key === 'email' ? '#refund-email-error' : '#refund-confirm-error';
        const note = document.querySelector(selector);
        if (note && note.remove) note.remove();
        if (target.removeAttribute) target.removeAttribute('aria-invalid');
      }
      if ((target.name === 'phone' || target.name === 'email') && state.fieldErrors.contact) {
        state.fieldErrors.contact = null;
        const note = document.querySelector('#contact-error');
        if (note && note.remove) note.remove();
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

async function handleStaffDecision(reference, decision, note) {
  const req = state.staff.requests.find(r => r.reference === reference);
  if (!req) return;
  const version = req.version;
  const key = reference;
  if (decision === 'decline') {
    const trimmed = String(note || '').trim();
    if (!trimmed) {
      state.staff.decisionError = Object.assign({}, state.staff.decisionError, {[key]: 'Reason is required.'});
      render();
      return;
    }
    if (trimmed.length > 500) {
      state.staff.decisionError = Object.assign({}, state.staff.decisionError, {[key]: 'Reason must be 500 characters or less.'});
      render();
      return;
    }
    state.staff.decisionError = Object.assign({}, state.staff.decisionError, {[key]: ''});
    state.staff.decisionNote = Object.assign({}, state.staff.decisionNote, {[key]: trimmed});
    note = trimmed;
  } else {
    state.staff.decisionError = Object.assign({}, state.staff.decisionError, {[key]: ''});
  }
  state.staff.decisionBusy = Object.assign({}, state.staff.decisionBusy, {[key]: true});
  render();
  try {
    const updated = await api(`/api/staff/requests/${reference}/decision`, {
      method: 'POST',
      body: {decision, note, version},
    });
    state.staff.decisionBusy = Object.assign({}, state.staff.decisionBusy, {[key]: false});
    const updatedReq = updated.request || {};
    const idx = state.staff.requests.findIndex(r => r.reference === reference);
    if (idx >= 0) {
      state.staff.requests[idx] = Object.assign({}, state.staff.requests[idx], updatedReq);
    }
    const pending = state.staff.requests.filter(r => String(r.status || '') === 'pending');
    state.staff.pendingCount = pending.length;
    state.staff.expanded = null;
    state.staff.deciding = null;
    state.staff.notice = null;
    state.staff.decisionError = Object.assign({}, state.staff.decisionError);
    state.staff.decisionError[key] = null;
    state.staff.decisionNote = Object.assign({}, state.staff.decisionNote);
    state.staff.decisionNote[key] = '';
    render();
  } catch (error) {
    state.staff.decisionBusy = Object.assign({}, state.staff.decisionBusy, {[key]: false});
    if (error.status === 409) {
      state.staff.expanded = null;
      state.staff.deciding = null;
      await loadStaffRequests(false);
      state.staff.notice = 'This request was already updated. The list has been refreshed.';
      render();
      return;
    }
    state.staff.decisionError = Object.assign({}, state.staff.decisionError, {[key]: error.message || 'Decision failed. Please try again.'});
    render();
  }
}

function bindStaff() {
  const root = document.querySelector('.staff-panel');
  if (!root) return;
  root.addEventListener('click', event => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const header = target.closest('.staff-row-header');
    if (header && !header.disabled && header.dataset.ref) {
      event.preventDefault();
      const ref = header.dataset.ref;
      if (state.staff.expanded === ref) {
        state.staff.expanded = null;
        state.staff.deciding = null;
      } else {
        state.staff.expanded = ref;
        state.staff.deciding = null;
        state.staff.decisionError = Object.assign({}, state.staff.decisionError, {[ref]: ''});
        state.staff.decisionNote = Object.assign({}, state.staff.decisionNote, {[ref]: ''});
      }
      render();
      return;
    }
    const actionBtn = target.closest('button[data-action]');
    if (actionBtn) {
      const action = actionBtn.dataset.action;
      const ref = actionBtn.dataset.ref;
      event.preventDefault();
      if (action === 'reset-start') {
        state.staff.resetConfirm = true;
        state.staff.notice = null;
        render();
        return;
      }
      if (action === 'reset-cancel') {
        state.staff.resetConfirm = false;
        render();
        return;
      }
      if (action === 'reset-confirm') {
        resetDemoData();
        return;
      }
      if (!ref) return;
      if (action === 'start-approve') {
        state.staff.notice = null;
        state.staff.deciding = {reference: ref, decision: 'approve'};
        state.staff.decisionError = Object.assign({}, state.staff.decisionError, {[ref]: ''});
        render();
        return;
      }
      if (action === 'start-decline') {
        state.staff.notice = null;
        state.staff.deciding = {reference: ref, decision: 'decline'};
        state.staff.decisionError = Object.assign({}, state.staff.decisionError, {[ref]: ''});
        render();
        return;
      }
      if (action === 'cancel-decision') {
        state.staff.deciding = null;
        state.staff.decisionError = Object.assign({}, state.staff.decisionError, {[ref]: ''});
        render();
        return;
      }
      if (action === 'approve-confirm') {
        handleStaffDecision(ref, 'approve', '');
        return;
      }
      if (action === 'decline-confirm') {
        const noteValue = (state.staff.decisionNote && state.staff.decisionNote[ref]) || '';
        handleStaffDecision(ref, 'decline', noteValue);
        return;
      }
    }
  });
  root.addEventListener('keydown', event => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const header = target.closest('.staff-row-header');
    if (header && !header.disabled && header.dataset.ref) {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        const ref = header.dataset.ref;
        if (state.staff.expanded === ref) {
          state.staff.expanded = null;
          state.staff.deciding = null;
        } else {
          state.staff.expanded = ref;
          state.staff.deciding = null;
          state.staff.decisionError = Object.assign({}, state.staff.decisionError, {[ref]: ''});
          state.staff.decisionNote = Object.assign({}, state.staff.decisionNote, {[ref]: ''});
        }
        render();
        return;
      }
    }
  });
  root.addEventListener('input', event => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    if (target.tagName === 'TEXTAREA' && target.classList && target.classList.contains('staff-textarea')) {
      const ref = target.dataset.ref;
      if (ref) {
        state.staff.decisionNote = Object.assign({}, state.staff.decisionNote, {[ref]: target.value});
      }
    }
  });
  const retryBtn = document.querySelector('#staff-retry');
  if (retryBtn) {
    retryBtn.addEventListener('click', event => {
      event.preventDefault();
      retryStaffRequests();
    });
  }
}

function render() {
  main.innerHTML = state.view === 'passenger' ? passengerView() : state.view === 'staff' ? staffView() : signInView();
  const account = document.querySelector('#account');
  if (account) account.innerHTML = state.view === 'signin' ? '' : accountMarkup();
  document.title = 'AirAssist · ' + (state.view === 'signin' ? 'Sign in' : state.role === 'staff' ? 'Staff area' : 'Passenger area');
  bindForms();
}

render();
