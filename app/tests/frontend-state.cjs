'use strict';
// Runs the real browser functions in an isolated VM. No network, database or Web Storage.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const publicDir = path.join(__dirname, '..', 'public');
const source = fs.readFileSync(path.join(publicDir, 'app.js'), 'utf8');

function storage() {
  const values = new Map();
  const writes = [];
  return {
    values, writes,
    getItem: k => (values.has(k) ? values.get(k) : null),
    setItem: (k, v) => { writes.push([k, String(v)]); values.set(k, String(v)); },
    removeItem: k => { values.delete(k); }
  };
}

function harness(store = storage()) {
  const nodes = new Map();
  const body = {};
  const main = {contains: () => false, focus() {}, innerHTML: ''};
  const document = {
    body, activeElement: body, title: '', cookie: '',
    querySelector: s => (s === 'main' ? main : nodes.get(s) || null),
    querySelectorAll: () => [],
    addEventListener() {}
  };
  const box = {
    document, history: {}, location: {search: ''},
    sessionStorage: store, localStorage: store,
    URLSearchParams, Date, console, setTimeout, clearTimeout,
    window: {scrollTo() {}, addEventListener() {}},
    fetch: async () => { throw new Error('Unexpected network call'); }
  };
  vm.createContext(box);
  vm.runInContext(source, box);
  return {box, store, nodes, state: vm.runInContext('state', box), token: () => vm.runInContext('token', box)};
}

function ok(payload) { return async () => ({ok: true, status: 200, json: async () => payload}); }
function fail(status, message = 'server text') {
  return async () => ({ok: false, status, json: async () => ({error: {code: 'X', message}})});
}

const tests = [];
const test = (name, fn) => tests.push({name, fn});

test('signing in routes a passenger to the passenger area', async () => {
  const h = harness();
  h.box.fetch = ok({token: 'tok-passenger', role: 'passenger', displayName: 'Mark Don'});
  assert.equal(await h.box.signIn('Mark.don', 'secret'), true);
  assert.equal(h.state.view, 'passenger');
  assert.equal(h.state.displayName, 'Mark Don');
  assert.equal(h.token(), 'tok-passenger');
  assert.match(h.box.passengerView(), /Passenger area/);
});

test('signing in routes staff to the staff area', async () => {
  const h = harness();
  h.box.fetch = ok({token: 'tok-staff', role: 'staff', displayName: 'Refunds team'});
  assert.equal(await h.box.signIn('admin', 'secret'), true);
  assert.equal(h.state.view, 'staff');
  assert.equal(h.state.role, 'staff');
  assert.match(h.box.staffView(), /Staff area/);
});

test('the header shows the display name and a sign out link after sign-in', async () => {
  const h = harness();
  const account = {innerHTML: ''};
  h.nodes.set('#account', account);
  h.box.fetch = ok({token: 'tok', role: 'passenger', displayName: 'Mark Don'});
  await h.box.signIn('Mark.don', 'secret');
  assert.match(account.innerHTML, /Mark Don/);
  assert.match(account.innerHTML, /Sign out/);
});

test('the sign-in page shows the heading, fields and demo accounts without a password', () => {
  const h = harness();
  const html = h.box.signInView();
  assert.match(html, /Kia ora, sign in/);
  assert.match(html, /for="username">Username/);
  assert.match(html, /for="password">Password/);
  assert.match(html, /Demo accounts: Mark\.don \(passenger\) · admin \(staff\)/);
  assert.doesNotMatch(html, /name="password"[^>]*value=/);
});

test('the access token is never written to Web Storage or cookies', async () => {
  assert.doesNotMatch(source, /(localStorage|sessionStorage)\s*\./);
  assert.doesNotMatch(source, /document\s*\.\s*cookie/);
  const h = harness();
  h.box.fetch = ok({token: 'secret-token-value', role: 'passenger', displayName: 'Mark Don'});
  await h.box.signIn('Mark.don', 'secret');
  assert.equal(h.store.writes.length, 0);
  assert.equal(h.store.values.size, 0);
  assert.equal(h.box.document.cookie, '');
});

test('empty fields are rejected before any request is sent', async () => {
  const h = harness();
  let calls = 0;
  h.box.fetch = async () => { calls++; };
  assert.equal(await h.box.signIn('   ', ''), false);
  assert.equal(calls, 0);
  assert.equal(h.state.error, 'Enter your username and password.');
  assert.equal(h.state.view, 'signin');
});

test('401 shows the incorrect-credentials message', async () => {
  const h = harness();
  h.box.fetch = fail(401);
  await h.box.signIn('user', 'pass');
  assert.equal(h.state.error, 'Username or password is incorrect.');
  assert.equal(h.state.view, 'signin');
});

test('429 shows the too-many-attempts message', async () => {
  const h = harness();
  h.box.fetch = fail(429);
  await h.box.signIn('user', 'pass');
  assert.equal(h.state.error, 'Too many attempts. Try again in a few minutes.');
});

test('503 shows the sign-in-unavailable message', async () => {
  const h = harness();
  h.box.fetch = fail(503);
  await h.box.signIn('user', 'pass');
  assert.equal(h.state.error, "Sign-in isn't available right now.");
});

test('a later 401 ends the session and returns to sign-in', async () => {
  const h = harness();
  h.box.fetch = ok({token: 'tok', role: 'passenger', displayName: 'Mark Don'});
  await h.box.signIn('Mark.don', 'secret');
  h.box.fetch = fail(401, 'Your sign-in has expired. Sign in again.');
  await assert.rejects(() => h.box.api('/api/me'), /Your session has ended/);
  assert.equal(h.state.view, 'signin');
  assert.equal(h.state.error, 'Your session has ended. Sign in again.');
  assert.equal(h.token(), null);
});

test('sign out clears the session state and returns to the sign-in page', async () => {
  const h = harness();
  h.box.fetch = ok({token: 'tok', role: 'staff', displayName: 'Refunds team'});
  await h.box.signIn('admin', 'secret');
  h.box.signOut();
  assert.equal(h.state.view, 'signin');
  assert.equal(h.state.role, null);
  assert.equal(h.state.displayName, null);
  assert.equal(h.state.error, null);
  assert.equal(h.token(), null);
  assert.match(h.box.signInView(), /Kia ora, sign in/);
});

test('the login request sends JSON and later calls carry the bearer token', async () => {
  const h = harness();
  const calls = [];
  h.box.fetch = async (url, options) => {
    calls.push({url, options});
    return {ok: true, status: 200, json: async () => ({token: 'tok-123', role: 'passenger', displayName: 'Mark Don'})};
  };
  await h.box.signIn('Mark.don', 'secret');
  assert.equal(calls[0].url, '/api/auth/login');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.credentials, 'same-origin');
  assert.equal(calls[0].options.headers['Content-Type'], 'application/json');
  assert.equal(JSON.parse(calls[0].options.body).username, 'Mark.don');
  assert.equal(calls[0].options.headers.Authorization, undefined);
  h.box.fetch = async (url, options) => {
    calls.push({url, options});
    return {ok: true, status: 200, json: async () => ({ok: true})};
  };
  await h.box.api('/api/staff/requests');
  assert.equal(calls[1].options.headers.Authorization, 'Bearer tok-123');
});

test('displayed values are escaped', () => {
  const h = harness();
  h.state.displayName = '<img src=x onerror=alert(1)>';
  const header = h.box.accountMarkup();
  assert.doesNotMatch(header, /<img/);
  assert.match(header, /&lt;img/);
});

(async () => {
  for (const {name, fn} of tests) { await fn(); console.log(`PASS ${name}`); }
  console.log(`${tests.length} frontend regression checks passed.`);
})().catch(error => { console.error(error); process.exitCode = 1; });
