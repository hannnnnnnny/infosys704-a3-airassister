'use strict';
/* AirAssist sign-in. The access token lives only in the token variable below, so a page
   refresh starts a fresh sign-in. The page itself is loaded first, which is what establishes
   the anonymous demo session on the hosted deployment. */
let token = null;
const state = {view: 'signin', role: null, displayName: null, username: '', error: null, busy: false};
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
    render();
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

function passengerView() {
  return areaView('Passenger area', 'Refund requests will appear here.');
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
}

function render() {
  main.innerHTML = state.view === 'passenger' ? passengerView() : state.view === 'staff' ? staffView() : signInView();
  const account = document.querySelector('#account');
  if (account) account.innerHTML = state.view === 'signin' ? '' : accountMarkup();
  document.title = 'AirAssist · ' + (state.view === 'signin' ? 'Sign in' : state.role === 'staff' ? 'Staff area' : 'Passenger area');
  bindForms();
}

render();
