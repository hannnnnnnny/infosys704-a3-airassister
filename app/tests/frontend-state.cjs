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

const REQUEST_KEY = '11111111-1111-4111-8111-111111111111';

function fakeElement(tag) {
  return {
    tagName: tag, href: '', download: '', clicked: 0,
    click() { this.clicked++; }, remove() {}, setAttribute() {}, removeAttribute() {},
    addEventListener() {}, appendChild() {}
  };
}

function harness(store = storage()) {
  const nodes = new Map();
  const body = {children: [], appendChild(node) { this.children.push(node); }};
  const main = {contains: () => false, focus() {}, innerHTML: ''};
  const document = {
    body, activeElement: body, title: '', cookie: '',
    createElement: tag => fakeElement(tag),
    querySelector: s => (s === 'main' ? main : nodes.get(s) || null),
    querySelectorAll: () => [],
    addEventListener() {}
  };
  const box = {
    document, history: {}, location: {search: ''},
    sessionStorage: store, localStorage: store,
    URLSearchParams, Date, console, setTimeout, clearTimeout,
    crypto: {randomUUID: () => REQUEST_KEY},
    URL: {createObjectURL: () => 'blob:mock', revokeObjectURL() {}},
    window: {scrollTo() {}, addEventListener() {}},
    fetch: async () => { throw new Error('Unexpected network call'); }
  };
  vm.createContext(box);
  vm.runInContext(source, box);
  return {box, store, nodes, state: vm.runInContext('state', box), token: () => vm.runInContext('token', box)};
}

function json(payload, status = 200) { return {ok: status < 400, status, json: async () => payload}; }
function ok(payload) { return async () => json(payload); }
function fail(status, message = 'server text') {
  return async () => ({ok: false, status, json: async () => ({error: {code: 'X', message}})});
}

function routes(map) {
  return async (url, options) => {
    if (Object.prototype.hasOwnProperty.call(map, url)) {
      const value = map[url];
      return typeof value === 'function' ? value(url, options) : value;
    }
    throw new Error('Unexpected network call: ' + url);
  };
}

function flight() {
  return {flight: 'NZ6', fromCode: 'AKL', fromCity: 'Auckland',
    toCode: 'LAX', toCity: 'Los Angeles', date: '2026-10-28', cabin: 'Economy', flightStatus: 'cancelled'};
}

function me(overrides = {}) {
  return {
    displayName: 'Mark Don', booking: {reference: 'NZ7K2H'}, flight: flight(),
    quote: {sapDocument: '60000073', amount: 175.5, currency: 'USD', processStatus: 'A', fetchedAt: '2026-10-14T00:00:00Z'},
    quoteError: null, request: null, ...overrides,
  };
}

function request(overrides = {}) {
  return {
    reference: 'AF-DEMO000002', bookingReference: 'NZ7K2H', passengerName: 'Mark Don',
    email: 'mark@example.com', amount: 175.5, currency: 'USD', status: 'pending',
    decisionNote: '', version: 1, flight: flight(), ...overrides,
  };
}

function passengerSession(meResponse = me()) {
  return routes({
    '/api/auth/login': json({token: 'tok-passenger', role: 'passenger', displayName: 'Mark Don'}),
    '/api/me': json(meResponse),
  });
}

const tests = [];
const test = (name, fn) => tests.push({name, fn});

test('signing in routes a passenger to the request screen', async () => {
  const h = harness();
  h.box.fetch = passengerSession();
  assert.equal(await h.box.signIn('Mark.don', 'secret'), true);
  assert.equal(h.state.view, 'passenger');
  assert.equal(h.state.displayName, 'Mark Don');
  assert.equal(h.token(), 'tok-passenger');
  assert.match(h.box.passengerView(), /Kia ora, Mark/);
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
  h.box.fetch = passengerSession();
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
  h.box.fetch = passengerSession();
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
  h.box.fetch = passengerSession();
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
    if (url === '/api/auth/login') return json({token: 'tok-123', role: 'passenger', displayName: 'Mark Don'});
    return json(me());
  };
  await h.box.signIn('Mark.don', 'secret');
  const login = calls.find(call => call.url === '/api/auth/login');
  assert.equal(login.options.method, 'POST');
  assert.equal(login.options.credentials, 'same-origin');
  assert.equal(login.options.headers['Content-Type'], 'application/json');
  assert.equal(JSON.parse(login.options.body).username, 'Mark.don');
  assert.equal(login.options.headers.Authorization, undefined);
  const meCall = calls.find(call => call.url === '/api/me');
  assert.equal(meCall.options.headers.Authorization, 'Bearer tok-123');
  await h.box.api('/api/staff/requests');
  const staff = calls.find(call => call.url === '/api/staff/requests');
  assert.equal(staff.options.headers.Authorization, 'Bearer tok-123');
});

test('displayed values are escaped', () => {
  const h = harness();
  h.state.displayName = '<img src=x onerror=alert(1)>';
  const header = h.box.accountMarkup();
  assert.doesNotMatch(header, /<img/);
  assert.match(header, /&lt;img/);
});

// --- passenger refund screens ---------------------------------------------------------------

test('the request screen shows the flight, route, refund amount and one button', async () => {
  const h = harness();
  h.box.fetch = passengerSession();
  await h.box.signIn('Mark.don', 'secret');
  const html = h.box.passengerView();
  assert.match(html, /Kia ora, Mark/);
  assert.match(html, /NZ6 on 28 October 2026 was cancelled\. Sorry about that\./);
  assert.match(html, /route-code">AKL/);
  assert.match(html, /route-code">LAX/);
  assert.match(html, /Auckland/);
  assert.match(html, /Los Angeles/);
  assert.match(html, /Full refund to your original payment/);
  assert.match(html, /USD 175\.50/);
  assert.match(html, /for="refund-email">Email/);
  assert.match(html, /I confirm my details are correct/);
  assert.match(html, /Request full refund/);
  assert.doesNotMatch(html, /60000073/);
  assert.doesNotMatch(html, /processStatus|sapDocument/);
});

test('a quote failure shows a retry and no submit button, and retry reloads the booking', async () => {
  const h = harness();
  let meCalls = 0;
  h.box.fetch = async url => {
    if (url === '/api/auth/login') return json({token: 'tok', role: 'passenger', displayName: 'Mark Don'});
    if (url === '/api/me') {
      meCalls += 1;
      return json(meCalls === 1
        ? me({quote: null, quoteError: {code: 'SAP_UNAVAILABLE', message: 'SAP is unavailable.'}})
        : me());
    }
    throw new Error('Unexpected network call: ' + url);
  };
  await h.box.signIn('Mark.don', 'secret');
  let html = h.box.passengerView();
  assert.match(html, /We couldn't load your refund amount\. Try again\./);
  assert.match(html, /id="retry-quote"/);
  assert.doesNotMatch(html, /Request full refund/);
  assert.doesNotMatch(html, /refund-form/);
  await h.box.retryMe();
  assert.equal(meCalls, 2);
  html = h.box.passengerView();
  assert.match(html, /Request full refund/);
});

test('submitting with a bad email and no confirmation shows inline errors and sends nothing', async () => {
  const h = harness();
  const calls = [];
  h.box.fetch = async (url, options) => {
    calls.push({url, options});
    if (url === '/api/auth/login') return json({token: 'tok', role: 'passenger', displayName: 'Mark Don'});
    return json(me());
  };
  await h.box.signIn('Mark.don', 'secret');
  h.state.email = 'not-an-email';
  h.state.confirm = false;
  await h.box.submitRefund();
  assert.equal(calls.filter(call => call.url === '/api/refund-requests').length, 0);
  const html = h.box.passengerView();
  assert.match(html, /Enter a valid email address\./);
  assert.match(html, /Tick the box to confirm your details are correct\./);
});

test('a successful submit switches to the status screen and clears the request key', async () => {
  const h = harness();
  const calls = [];
  h.box.fetch = async (url, options) => {
    calls.push({url, options});
    if (url === '/api/auth/login') return json({token: 'tok', role: 'passenger', displayName: 'Mark Don'});
    if (url === '/api/me') return json(me());
    if (url === '/api/refund-requests') return json({request: request(), created: true}, 201);
    throw new Error('Unexpected network call: ' + url);
  };
  await h.box.signIn('Mark.don', 'secret');
  const key = h.state.requestKey;
  assert.equal(key, REQUEST_KEY);
  h.state.email = 'mark@example.com';
  h.state.confirm = true;
  await h.box.submitRefund();
  const post = calls.find(call => call.url === '/api/refund-requests');
  const body = JSON.parse(post.options.body);
  assert.equal(body.email, 'mark@example.com');
  assert.equal(body.confirmed, true);
  assert.equal(body.requestKey, key);
  assert.equal(h.state.me.request.reference, 'AF-DEMO000002');
  assert.equal(h.state.requestKey, null);
  assert.match(h.box.passengerView(), /Request sent/);
});

test('the request key is created once and reused when a submission is retried', async () => {
  const h = harness();
  const keys = [];
  h.box.fetch = async (url, options) => {
    if (url === '/api/auth/login') return json({token: 'tok', role: 'passenger', displayName: 'Mark Don'});
    if (url === '/api/me') return json(me());
    if (url === '/api/refund-requests') {
      keys.push(JSON.parse(options.body).requestKey);
      if (keys.length === 1) throw new Error('offline');
      return json({request: request(), created: true}, 201);
    }
    throw new Error('Unexpected network call: ' + url);
  };
  await h.box.signIn('Mark.don', 'secret');
  h.state.email = 'mark@example.com';
  h.state.confirm = true;
  await h.box.submitRefund();
  assert.equal(h.state.me.request, null);
  assert.equal(h.state.requestKey, REQUEST_KEY);
  await h.box.submitRefund();
  assert.equal(keys.length, 2);
  assert.equal(keys[0], keys[1]);
  assert.match(h.box.passengerView(), /Request sent/);
});

test('a 409 response reloads the booking and shows the status screen', async () => {
  const h = harness();
  let submitted = false;
  h.box.fetch = async url => {
    if (url === '/api/auth/login') return json({token: 'tok', role: 'passenger', displayName: 'Mark Don'});
    if (url === '/api/me') return json(submitted ? me({request: request()}) : me());
    if (url === '/api/refund-requests') {
      submitted = true;
      return json({error: {code: 'IDEMPOTENCY_CONFLICT', message: 'This booking already has a refund request.'}}, 409);
    }
    throw new Error('Unexpected network call: ' + url);
  };
  await h.box.signIn('Mark.don', 'secret');
  h.state.email = 'mark@example.com';
  h.state.confirm = true;
  await h.box.submitRefund();
  assert.equal(h.state.error, null);
  assert.equal(h.state.me.request.reference, 'AF-DEMO000002');
  assert.match(h.box.passengerView(), /Request sent/);
});

test('a pending request shows the awaiting-approval status', async () => {
  const h = harness();
  h.box.fetch = passengerSession(me({request: request()}));
  await h.box.signIn('Mark.don', 'secret');
  const html = h.box.passengerView();
  assert.match(html, /Request sent/);
  assert.match(html, /Our refunds team will review it shortly\./);
  assert.match(html, /pill-pending">Awaiting approval/);
  assert.match(html, /USD 175\.50/);
  assert.match(html, /AF-DEMO000002/);
  assert.match(html, /Download receipt/);
});

test('an approved request shows the approved status and payout sentence', async () => {
  const h = harness();
  h.box.fetch = passengerSession(me({request: request({status: 'approved'})}));
  await h.box.signIn('Mark.don', 'secret');
  const html = h.box.passengerView();
  assert.match(html, /Refund approved/);
  assert.match(html, /USD 175\.50 will go back to your original payment\./);
  assert.match(html, /pill-approved">Approved/);
});

test('a declined request shows the decline note', async () => {
  const h = harness();
  h.box.fetch = passengerSession(me({request: request({status: 'declined', decisionNote: 'This fare is not refundable.'})}));
  await h.box.signIn('Mark.don', 'secret');
  const html = h.box.passengerView();
  assert.match(html, /Refund declined/);
  assert.match(html, /This fare is not refundable\./);
  assert.match(html, /pill-declined">Declined/);
});

test('downloading a receipt fetches with the bearer token', async () => {
  const h = harness();
  const calls = [];
  h.box.fetch = async (url, options) => {
    calls.push({url, options});
    if (url === '/api/auth/login') return json({token: 'tok-123', role: 'passenger', displayName: 'Mark Don'});
    if (url === '/api/me') return json(me({request: request()}));
    if (url === '/api/refund-requests/receipt') return {ok: true, status: 200, blob: async () => ({})};
    throw new Error('Unexpected network call: ' + url);
  };
  await h.box.signIn('Mark.don', 'secret');
  await h.box.downloadReceipt();
  const receipt = calls.find(call => call.url === '/api/refund-requests/receipt');
  assert.equal(receipt.options.headers.Authorization, 'Bearer tok-123');
  assert.equal(receipt.options.credentials, 'same-origin');
  assert.equal(h.state.receiptError, null);
});

test('the passenger screens contain no inline styles or scripts', async () => {
  const h = harness();
  h.box.fetch = passengerSession();
  await h.box.signIn('Mark.don', 'secret');
  assert.doesNotMatch(h.box.passengerView(), /style=|onclick=/);
  h.box.fetch = passengerSession(me({request: request()}));
  await h.box.signIn('Mark.don', 'secret');
  assert.doesNotMatch(h.box.passengerView(), /style=|onclick=/);
});

(async () => {
  for (const {name, fn} of tests) { await fn(); console.log(`PASS ${name}`); }
  console.log(`${tests.length} frontend regression checks passed.`);
})().catch(error => { console.error(error); process.exitCode = 1; });
