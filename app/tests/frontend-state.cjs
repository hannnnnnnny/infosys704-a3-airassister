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

function trip(overrides = {}) {
  return {
    booking: {reference: 'NZ7K2H', paymentMethod: {type: 'card', brand: 'Visa', last4: '4242'}},
    flight: flight(),
    refundable: true,
    request: null,
    paymentMethod: {type: 'card', brand: 'Visa', last4: '4242'},
    quote: {sapDocument: '60000073', amount: 175.5, currency: 'USD', processStatus: 'A', fetchedAt: '2026-10-14T00:00:00Z'},
    quoteError: null,
    ...overrides,
  };
}

function me(overrides = {}) {
  const {displayName = 'Mark Don', trips, ...tripOverrides} = overrides;
  if (trips) return {displayName, trips};
  return {displayName, trips: [trip(tripOverrides)]};
}

function request(overrides = {}) {
  return {
    reference: 'AF-DEMO000002', bookingReference: 'NZ7K2H', passengerName: 'Mark Don',
    email: 'mark@example.com', phone: '', contact: {phone: '', email: 'mark@example.com'},
    paymentMethod: {type: 'card', brand: 'Visa', last4: '4242'},
    amount: 175.5, currency: 'USD', status: 'pending',
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
  assert.match(h.box.passengerView(), /My trips/);
  assert.match(h.box.passengerView(), /Kia ora, Mark/);
  h.box.openTrip('NZ7K2H');
  assert.match(h.box.passengerView(), /Kia ora, Mark/);
});

test('signing in routes staff to the staff area', async () => {
  const h = harness();
  h.box.fetch = ok({token: 'tok-staff', role: 'staff', displayName: 'Refunds team'});
  assert.equal(await h.box.signIn('admin', 'secret'), true);
  assert.equal(h.state.view, 'staff');
  assert.equal(h.state.role, 'staff');
  assert.match(h.box.staffView(), /Refund requests/);
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
  h.box.openTrip('NZ7K2H');
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
      return json(meCalls <= 2
        ? me({quote: null, quoteError: {code: 'SAP_UNAVAILABLE', message: 'SAP is unavailable.'}})
        : me());
    }
    throw new Error('Unexpected network call: ' + url);
  };
  await h.box.signIn('Mark.don', 'secret');
  await h.box.openTrip('NZ7K2H');
  let html = h.box.passengerView();
  assert.match(html, /We couldn't load your refund amount\. Try again\./);
  assert.match(html, /id="retry-quote"/);
  assert.doesNotMatch(html, /Request full refund/);
  assert.doesNotMatch(html, /refund-form/);
  await h.box.retryMe();
  assert.ok(meCalls >= 3);
  await h.box.openTrip('NZ7K2H');
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
  h.box.openTrip('NZ7K2H');
  h.state.phone = '';
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
  h.box.openTrip('NZ7K2H');
  const key = h.state.requestKey;
  assert.equal(key, REQUEST_KEY);
  h.state.phone = '';
  h.state.email = 'mark@example.com';
  h.state.confirm = true;
  await h.box.submitRefund();
  const post = calls.find(call => call.url === '/api/refund-requests');
  const body = JSON.parse(post.options.body);
  assert.equal(body.contact.email, 'mark@example.com');
  assert.equal(body.bookingReference, 'NZ7K2H');
  assert.equal(body.confirmed, true);
  assert.equal(body.requestKey, key);
  assert.equal(h.box.selectedTrip().request.reference, 'AF-DEMO000002');
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
  h.box.openTrip('NZ7K2H');
  h.state.phone = '';
  h.state.email = 'mark@example.com';
  h.state.confirm = true;
  await h.box.submitRefund();
  assert.equal(h.box.selectedTrip().request, null);
  assert.equal(h.state.requestKey, REQUEST_KEY);
  h.state.phone = '';
  h.state.email = 'mark@example.com';
  h.state.confirm = true;
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
  h.box.openTrip('NZ7K2H');
  h.state.phone = '';
  h.state.email = 'mark@example.com';
  h.state.confirm = true;
  await h.box.submitRefund();
  assert.equal(h.state.error, null);
  assert.equal(h.box.selectedTrip().request.reference, 'AF-DEMO000002');
  assert.match(h.box.passengerView(), /Request sent/);
});

test('a pending request shows the awaiting-approval status', async () => {
  const h = harness();
  h.box.fetch = passengerSession(me({request: request()}));
  await h.box.signIn('Mark.don', 'secret');
  h.box.openTrip('NZ7K2H');
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
  h.box.openTrip('NZ7K2H');
  const html = h.box.passengerView();
  assert.match(html, /Refund approved/);
  assert.match(html, /USD 175\.50 will go back to your original payment\./);
  assert.match(html, /pill-approved">Approved/);
});

test('a declined request shows the decline note', async () => {
  const h = harness();
  h.box.fetch = passengerSession(me({request: request({status: 'declined', decisionNote: 'This fare is not refundable.'})}));
  await h.box.signIn('Mark.don', 'secret');
  h.box.openTrip('NZ7K2H');
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
    if (url === '/api/refund-requests/receipt?booking=NZ7K2H') return {ok: true, status: 200, blob: async () => ({})};
    throw new Error('Unexpected network call: ' + url);
  };
  await h.box.signIn('Mark.don', 'secret');
  h.box.openTrip('NZ7K2H');
  await h.box.downloadReceipt();
  const receipt = calls.find(call => call.url === '/api/refund-requests/receipt?booking=NZ7K2H');
  assert.equal(receipt.options.headers.Authorization, 'Bearer tok-123');
  assert.equal(receipt.options.credentials, 'same-origin');
  assert.equal(h.state.receiptError, null);
});

test('the passenger screens contain no inline styles or scripts', async () => {
  const h = harness();
  h.box.fetch = passengerSession();
  await h.box.signIn('Mark.don', 'secret');
  assert.doesNotMatch(h.box.passengerView(), /style=|onclick=/);
  h.box.openTrip('NZ7K2H');
  assert.doesNotMatch(h.box.passengerView(), /style=|onclick=/);
  h.box.fetch = passengerSession(me({request: request()}));
  await h.box.signIn('Mark.don', 'secret');
  h.box.openTrip('NZ7K2H');
  assert.doesNotMatch(h.box.passengerView(), /style=|onclick=/);
});

// --- staff refund screens -------------------------------------------------------------------

function staffRequest(overrides = {}) {
  return {
    reference: 'AF-AAAA1111', bookingReference: 'NZ7K2H', passengerName: 'Mark Don',
    email: 'mark@example.com', phone: '+64 21 555 0100', contact: {phone: '+64 21 555 0100', email: 'mark@example.com'},
    paymentMethod: {type: 'card', brand: 'Visa', last4: '4242'},
    reason: 'flight_disruption', refundType: 'full',
    amount: 175.5, currency: 'USD', sapDocument: '60000073', sapStatus: 'A',
    route: 'fast_track', status: 'pending', decisionNote: '', version: 1,
    createdAt: '2026-10-14T00:00:00Z', updatedAt: '2026-10-14T00:00:00Z',
    flight: flight(), ...overrides,
  };
}

async function staffSuccessfulSignIn(requests = [
  staffRequest({reference: 'AF-DEMO000002'}),
  staffRequest({reference: 'AF-DEMO000003', passengerName: 'Minh Nguyen', status: 'approved', amount: 400, route: 'specialist'}),
]) {
  const h = harness();
  h.box.fetch = routes({
    '/api/auth/login': json({token: 'tok-staff', role: 'staff', displayName: 'Refunds team'}),
    '/api/staff/requests': json({requests}),
  });
  await h.box.signIn('admin', 'secret');
  return h;
}

test('the staff list renders newest first with names, amounts and the pending count', async () => {
  const h = await staffSuccessfulSignIn();
  const html = h.box.staffView();
  assert.match(html, /Refund requests/);
  assert.match(html, /1 to process/);
  assert.match(html, /Mark Don/);
  assert.match(html, /Flight disruption · USD 175\.50/);
  assert.match(html, /Minh Nguyen/);
  assert.match(html, /pill-approved">Approved/);
  assert.equal(h.state.staff.requests.length, 2);
  assert.equal(h.state.staff.pendingCount, 1);
});

test('a newly created request shows a New pill and pending rows show a chevron', async () => {
  const h = await staffSuccessfulSignIn([staffRequest({createdAt: new Date().toISOString(), amount: 175.5})]);
  const html = h.box.staffView();
  assert.match(html, /staff-pill-new">New/);
  assert.match(html, /staff-chevron/);
  assert.match(html, /aria-expanded="false"/);
});

test('expanding a pending row shows flight, route, SAP line and the decision buttons', async () => {
  const h = await staffSuccessfulSignIn();
  h.state.staff.expanded = 'AF-DEMO000002';
  const html = h.box.staffView();
  assert.match(html, /aria-expanded="true"/);
  assert.match(html, /aria-controls="staff-row-AF-DEMO000002"/);
  assert.match(html, /role="region"/);
  assert.match(html, /NZ6 AKL → LAX, 28 October 2026 · cancelled · full refund/);
  assert.match(html, /staff-route-fast">Fast track/);
  assert.match(html, /SAP credit memo 60000073 · USD 175\.50/);
  assert.match(html, /data-action="start-approve"/);
  assert.match(html, /data-action="start-decline"/);
  assert.doesNotMatch(html, /<button[^>]*>[^<]*<button/);
});

test('only one row is open at a time', async () => {
  const h = await staffSuccessfulSignIn([
    staffRequest({reference: 'AF-AAAA000001'}),
    staffRequest({reference: 'AF-DEMO000002', passengerName: 'Minh Nguyen'}),
  ]);
  h.state.staff.expanded = 'AF-DEMO000002';
  let html = h.box.staffView();
  assert.equal((html.match(/aria-expanded="true"/g) || []).length, 1);
  h.state.staff.expanded = 'AF-AAAA000001';
  html = h.box.staffView();
  const openRows = html.match(/aria-expanded="true"/g) || [];
  assert.equal(openRows.length, 1);
  assert.match(html, /aria-expanded="true"[^>]*id="staff-row-AF-AAAA000001-btn"/);
  assert.match(html, /aria-expanded="false"[^>]*id="staff-row-AF-DEMO000002-btn"/);
});

test('approving requires the inline confirmation before anything is sent', async () => {
  const h = await staffSuccessfulSignIn();
  const calls = [];
  h.box.fetch = async (url, options) => { calls.push({url, options}); throw new Error('Unexpected network call: ' + url); };
  h.state.staff.expanded = 'AF-DEMO000002';
  h.state.staff.deciding = {reference: 'AF-DEMO000002', decision: 'approve'};
  const html = h.box.staffView();
  assert.match(html, /Approve USD 175\.50 for Mark Don\?/);
  assert.match(html, /data-action="approve-confirm"/);
  assert.match(html, /data-action="cancel-decision"/);
  assert.equal(calls.length, 0);
});

test('declining with an empty reason shows an inline error and sends nothing', async () => {
  const h = await staffSuccessfulSignIn();
  const calls = [];
  h.box.fetch = async (url, options) => { calls.push({url, options}); throw new Error('Unexpected network call: ' + url); };
  h.state.staff.expanded = 'AF-DEMO000002';
  h.state.staff.deciding = {reference: 'AF-DEMO000002', decision: 'decline'};
  await h.box.handleStaffDecision('AF-DEMO000002', 'decline', '   ');
  assert.equal(calls.length, 0);
  assert.equal(h.state.staff.decisionError['AF-DEMO000002'], 'Reason is required.');
  const html = h.box.staffView();
  assert.match(html, /Reason \(shown to the passenger\)/);
  assert.match(html, /maxlength="500"/);
  assert.match(html, /Reason is required\./);
});

test('a successful decision updates the row and the pending count without reloading', async () => {
  const h = await staffSuccessfulSignIn();
  const calls = [];
  h.box.fetch = async (url, options) => {
    calls.push({url, options});
    if (url === '/api/staff/requests/AF-DEMO000002/decision') {
      return json({request: staffRequest({reference: 'AF-DEMO000002', status: 'approved', version: 2})});
    }
    throw new Error('Unexpected network call: ' + url);
  };
  h.state.staff.expanded = 'AF-DEMO000002';
  h.state.staff.deciding = {reference: 'AF-DEMO000002', decision: 'approve'};
  await h.box.handleStaffDecision('AF-DEMO000002', 'approve', '');
  assert.equal(calls.length, 1);
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(JSON.parse(calls[0].options.body).version, 1);
  assert.equal(h.state.staff.pendingCount, 0);
  assert.equal(h.state.staff.expanded, null);
  const html = h.box.staffView();
  assert.match(html, /0 to process/);
  assert.match(html, /pill-approved">Approved/);
});

test('a 409 decision reloads the list and shows the refresh message', async () => {
  const h = await staffSuccessfulSignIn();
  const calls = [];
  h.box.fetch = async (url, options) => {
    calls.push({url, options});
    if (url === '/api/staff/requests/AF-DEMO000002/decision') {
      return json({error: {code: 'REQUEST_ALREADY_DECIDED', message: 'This request has already been decided.'}}, 409);
    }
    if (url === '/api/staff/requests') {
      return json({requests: [staffRequest({reference: 'AF-DEMO000002', status: 'declined', decisionNote: 'Not refundable', version: 2})]});
    }
    throw new Error('Unexpected network call: ' + url);
  };
  h.state.staff.expanded = 'AF-DEMO000002';
  await h.box.handleStaffDecision('AF-DEMO000002', 'approve', '');
  assert.equal(calls.filter(call => call.url === '/api/staff/requests').length, 1);
  assert.equal(h.state.staff.notice, 'This request was already updated. The list has been refreshed.');
  assert.equal(h.state.staff.pendingCount, 0);
  const html = h.box.staffView();
  assert.match(html, /This request was already updated\. The list has been refreshed\./);
  assert.match(html, /pill-declined">Declined/);
});

test('an empty staff list shows the empty state', async () => {
  const h = await staffSuccessfulSignIn([]);
  const html = h.box.staffView();
  assert.match(html, /No refund requests yet/);
  assert.match(html, /0 to process/);
});

test('a failed staff load shows an error state with Retry that reloads the list', async () => {
  const h = harness();
  let attempt = 0;
  h.box.fetch = async url => {
    if (url === '/api/auth/login') return json({token: 'tok-staff', role: 'staff', displayName: 'Refunds team'});
    if (url === '/api/staff/requests') {
      attempt += 1;
      if (attempt === 1) throw new Error('offline');
      return json({requests: [staffRequest()]});
    }
    throw new Error('Unexpected network call: ' + url);
  };
  await h.box.signIn('admin', 'secret');
  let html = h.box.staffView();
  assert.match(html, /id="staff-retry"/);
  assert.match(html, /Retry/);
  await h.box.retryStaffRequests();
  assert.equal(attempt, 2);
  html = h.box.staffView();
  assert.match(html, /Mark Don/);
  assert.match(html, /1 to process/);
});

test('the staff screen contains no inline styles or scripts and nests no controls in the toggle', async () => {
  const h = await staffSuccessfulSignIn();
  h.state.staff.expanded = 'AF-DEMO000002';
  const html = h.box.staffView();
  assert.doesNotMatch(html, /style=|onclick=/);
  const header = /<button[^>]*class="staff-row-header[^"]*"[^>]*>([\s\S]*?)<\/button>/.exec(html);
  assert.ok(header, 'the pending row has a toggle button');
  assert.doesNotMatch(header[1], /<(button|input|textarea|select)\b/);
  assert.match(html, /data-action="start-approve"/);
});

test('a collapsed pending row keeps its panel hidden until it is expanded', async () => {
  const h = await staffSuccessfulSignIn([staffRequest({reference: 'AF-DEMO000002'})]);
  let html = h.box.staffView();
  assert.match(html, /aria-expanded="false"/);
  const panel = /<div class="staff-row-panel"[^>]*>/.exec(html);
  assert.ok(panel, 'the pending row has a panel');
  assert.match(panel[0], / hidden>/);
  h.state.staff.expanded = 'AF-DEMO000002';
  html = h.box.staffView();
  assert.match(html, /aria-expanded="true"/);
  assert.doesNotMatch(html, /<div class="staff-row-panel"[^>]* hidden>/);
});

test('only the expanded pending row exposes visible decision controls', async () => {
  const h = await staffSuccessfulSignIn([
    staffRequest({reference: 'AF-DEMO000002'}),
    staffRequest({reference: 'AF-DEMO000004', passengerName: 'Ana Torres'}),
  ]);
  let html = h.box.staffView();
  const allPanels = html.match(/<div class="staff-row-panel"[^>]*>/g) || [];
  assert.equal(allPanels.length, 2);
  allPanels.forEach(tag => assert.match(tag, / hidden>/));
  h.state.staff.expanded = 'AF-DEMO000004';
  html = h.box.staffView();
  const openPanels = (html.match(/<div class="staff-row-panel"[^>]*>/g) || []).filter(tag => !/ hidden>/.test(tag));
  assert.equal(openPanels.length, 1);
  assert.match(openPanels[0], /id="staff-row-AF-DEMO000004"/);
  const openPanel = new RegExp('id="staff-row-AF-DEMO000004"[\\s\\S]*?<\\/div>\\s*<\\/div>').exec(html);
  assert.ok(openPanel, 'the expanded panel is found');
  assert.match(openPanel[0], /data-action="start-approve"/);
  assert.match(openPanel[0], /data-action="start-decline"/);
});

test('processed rows render no panel and no approve or decline controls', async () => {
  const h = await staffSuccessfulSignIn([
    staffRequest({reference: 'AF-DEMO000003', status: 'approved', amount: 400}),
    staffRequest({reference: 'AF-DEMO000005', passengerName: 'Ana Torres', status: 'declined', decisionNote: 'Not refundable'}),
  ]);
  const html = h.box.staffView();
  assert.match(html, /0 to process/);
  assert.match(html, /pill-approved">Approved/);
  assert.match(html, /pill-declined">Declined/);
  assert.doesNotMatch(html, /staff-row-panel/);
  assert.doesNotMatch(html, /data-action="start-approve"/);
  assert.doesNotMatch(html, /data-action="start-decline"/);
  assert.doesNotMatch(html, /<button[^>]*>\s*(Approve|Decline)\s*<\/button>/);
});

test('a mixed list only offers decision controls on its pending rows', async () => {
  const h = await staffSuccessfulSignIn();
  const html = h.box.staffView();
  assert.equal((html.match(/data-action="start-approve"/g) || []).length, 1);
  assert.equal((html.match(/data-action="start-decline"/g) || []).length, 1);
  assert.equal((html.match(/staff-row-panel/g) || []).length, 1);
  assert.match(html, /1 to process/);
});

test('values containing an ampersand are escaped exactly once', async () => {
  const h = await staffSuccessfulSignIn([
    staffRequest({reference: 'AF-DEMO000002', passengerName: 'A & B', sapDocument: '600&073'}),
  ]);
  h.state.staff.expanded = 'AF-DEMO000002';
  h.state.staff.deciding = {reference: 'AF-DEMO000002', decision: 'approve'};
  const html = h.box.staffView();
  assert.doesNotMatch(html, /&amp;amp;/);
  assert.match(html, /A &amp; B/);
  assert.match(html, /Approve USD 175\.50 for A &amp; B\?/);
  assert.match(html, /SAP credit memo 600&amp;073 · USD 175\.50/);
});

// --- staff demo reset ------------------------------------------------------------------------

// Runs the real staff click handler by giving the VM a panel that captures its listener.
function clickStaffAction(h, action, ref) {
  const listeners = [];
  h.nodes.set('.staff-panel', {addEventListener: (type, fn) => { if (type === 'click') listeners.push(fn); }});
  h.box.HTMLElement = h.box.HTMLElement || class HTMLElement {};
  h.box.render();
  const button = {dataset: ref ? {action, ref} : {action}};
  const target = Object.create(h.box.HTMLElement.prototype);
  target.closest = selector => (selector === 'button[data-action]' ? button : null);
  const event = {target, preventDefault() {}};
  for (const listener of listeners.slice()) listener(event);
}

test('the reset button asks for confirmation before anything is sent', async () => {
  const h = await staffSuccessfulSignIn();
  let calls = 0;
  h.box.fetch = async () => { calls += 1; throw new Error('Unexpected network call'); };
  let html = h.box.staffView();
  assert.match(html, /id="staff-reset-btn"/);
  assert.match(html, /data-action="reset-start"/);
  assert.match(html, /Reset demo data/);
  assert.doesNotMatch(html, /data-action="reset-confirm"/);
  clickStaffAction(h, 'reset-start');
  assert.equal(h.state.staff.resetConfirm, true);
  html = h.box.staffView();
  assert.match(html, /This deletes all refund requests and restores the starting demo data\./);
  assert.match(html, /data-action="reset-confirm"/);
  assert.match(html, /Yes, reset/);
  assert.match(html, /data-action="reset-cancel"/);
  assert.match(html, /Cancel/);
  assert.doesNotMatch(html, /id="staff-reset-btn"/);
  assert.equal(calls, 0);
});

test('cancelling the reset closes the confirmation without calling the API', async () => {
  const h = await staffSuccessfulSignIn();
  const calls = [];
  h.box.fetch = async (url, options) => { calls.push({url, options}); throw new Error('Unexpected network call: ' + url); };
  clickStaffAction(h, 'reset-start');
  assert.equal(h.state.staff.resetConfirm, true);
  clickStaffAction(h, 'reset-cancel');
  assert.equal(h.state.staff.resetConfirm, false);
  const html = h.box.staffView();
  assert.equal(calls.length, 0);
  assert.match(html, /id="staff-reset-btn"/);
  assert.doesNotMatch(html, /data-action="reset-confirm"/);
});

test('confirming the reset posts to the demo reset endpoint and shows the new list', async () => {
  const h = await staffSuccessfulSignIn();
  const calls = [];
  h.box.fetch = async (url, options) => {
    calls.push({url, options});
    if (url === '/api/staff/demo-reset') {
      return json({requests: [staffRequest({reference: 'AF-DEMO000001', passengerName: 'Minh Nguyen', amount: 400, route: 'specialist'})]});
    }
    throw new Error('Unexpected network call: ' + url);
  };
  h.state.staff.expanded = 'AF-DEMO000002';
  h.state.staff.deciding = {reference: 'AF-DEMO000002', decision: 'approve'};
  clickStaffAction(h, 'reset-start');
  clickStaffAction(h, 'reset-confirm');
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/staff/demo-reset');
  assert.equal(calls[0].options.method, 'POST');
  assert.equal(calls[0].options.headers.Authorization, 'Bearer tok-staff');
  assert.equal(h.state.staff.notice, 'Demo data reset.');
  assert.equal(h.state.staff.resetConfirm, false);
  assert.equal(h.state.staff.expanded, null);
  assert.equal(h.state.staff.deciding, null);
  assert.equal(h.state.staff.requests.length, 1);
  assert.equal(h.state.staff.pendingCount, 1);
  const html = h.box.staffView();
  assert.match(html, /Demo data reset\./);
  assert.match(html, /Minh Nguyen/);
  assert.doesNotMatch(html, /Mark Don/);
});

test('a failed reset is reported in plain words', async () => {
  const h = await staffSuccessfulSignIn();
  h.box.fetch = fail(500, 'Demo data could not be reset. Please try again.');
  clickStaffAction(h, 'reset-start');
  clickStaffAction(h, 'reset-confirm');
  await new Promise(resolve => setTimeout(resolve, 0));
  assert.equal(h.state.staff.resetting, false);
  assert.equal(h.state.staff.notice, 'Demo data could not be reset. Please try again.');
  const html = h.box.staffView();
  assert.match(html, /Demo data could not be reset\. Please try again\./);
});

// --- task 5b: My trips home and contact screens ------------------------------------------

function tripsResponse() {
  return {
    displayName: 'Mark Don',
    trips: [
      trip({booking: {reference: 'NZ2W6B', paymentMethod: {type: 'card', brand: 'Mastercard', last4: '5555'}},
        flight: {flight: 'NZ5', fromCode: 'LAX', fromCity: 'Los Angeles', toCode: 'AKL', toCity: 'Auckland', date: '2026-10-09', cabin: 'Economy', flightStatus: 'cancelled'},
        refundable: true, request: request({reference: 'AF-DEMO000003', bookingReference: 'NZ2W6B', status: 'approved', amount: 60, currency: 'USD'}),
        paymentMethod: {type: 'card', brand: 'Mastercard', last4: '5555'},
        quote: null, quoteError: null}),
      trip({}),
      trip({booking: {reference: 'NZ5R8M', paymentMethod: {type: 'card', brand: 'Amex', last4: '1005'}},
        flight: {flight: 'NZ8', fromCode: 'AKL', fromCity: 'Auckland', toCode: 'SFO', toCity: 'San Francisco', date: '2026-11-02', cabin: 'Economy', flightStatus: 'cancelled'},
        refundable: true, request: request({reference: 'AF-DEMO000002', bookingReference: 'NZ5R8M', status: 'pending'}),
        paymentMethod: {type: 'card', brand: 'Amex', last4: '1005'},
        quote: null, quoteError: null}),
      trip({booking: {reference: 'NZ3Q1T', paymentMethod: {type: 'card', brand: 'Visa', last4: '9876'}},
        flight: {flight: 'NZ103', fromCode: 'AKL', fromCity: 'Auckland', toCode: 'SYD', toCity: 'Sydney', date: '2026-11-15', cabin: 'Economy', flightStatus: 'on time'},
        refundable: false, request: null,
        paymentMethod: {type: 'card', brand: 'Visa', last4: '9876'},
        quote: null, quoteError: null}),
    ],
  };
}

test('My trips home shows greeting, subtitle, tiles and ordered cards', async () => {
  const h = harness();
  h.box.fetch = passengerSession(tripsResponse());
  await h.box.signIn('Mark.don', 'secret');
  const html = h.box.passengerView();
  assert.match(html, /My trips/);
  assert.match(html, /Kia ora, Mark/);
  assert.match(html, /Your trips and refunds in one place\./);
  assert.match(html, /Need action/);
  assert.match(html, /In review/);
  assert.match(html, /Refunded/);
  const order = [...html.matchAll(/data-booking="(.*?)"/g)].map(m => m[1]);
  assert.deepEqual(order, ['NZ2W6B', 'NZ7K2H', 'NZ5R8M', 'NZ3Q1T']);
  assert.match(html, /LAX → AKL/);
  assert.match(html, /9 October 2026 · NZ5 · NZ2W6B · cancelled/);
  assert.match(html, /pill-approved">Refunded/);
  assert.match(html, /pill-available">Refund available/);
  assert.match(html, /pill-pending">Awaiting approval/);
  assert.match(html, /pill-ontime">On time/);
  assert.match(html, /USD 60\.00/);
  assert.match(html, /class="trip-card"/);
});

test('each trip card opens the right view', async () => {
  const h = harness();
  h.box.fetch = passengerSession(tripsResponse());
  await h.box.signIn('Mark.don', 'secret');
  await h.box.openTrip('NZ7K2H');
  assert.match(h.box.passengerView(), /Request full refund/);
  await h.box.openTrip('NZ5R8M');
  assert.match(h.box.passengerView(), /Request sent/);
  await h.box.openTrip('NZ2W6B');
  assert.match(h.box.passengerView(), /Refund approved/);
  await h.box.openTrip('NZ3Q1T');
  assert.match(h.box.passengerView(), /Your flight is on time\. Nothing to do here\./);
});

test('detail views have back navigation and the header links to My trips', async () => {
  const h = harness();
  const account = {innerHTML: ''};
  h.nodes.set('#account', account);
  h.box.fetch = passengerSession(tripsResponse());
  await h.box.signIn('Mark.don', 'secret');
  assert.match(account.innerHTML, /My trips/);
  await h.box.openTrip('NZ7K2H');
  assert.match(h.box.passengerView(), /← My trips/);
  assert.match(h.box.passengerView(), /id="back-trips"/);
  await h.box.goHome();
  assert.equal(h.state.selectedBooking, null);
  assert.match(h.box.passengerView(), /My trips/);
});

test('contact validation requires at least one valid detail', async () => {
  const h = harness();
  const calls = [];
  h.box.fetch = async (url, options) => {
    calls.push({url, options});
    if (url === '/api/auth/login') return json({token: 'tok', role: 'passenger', displayName: 'Mark Don'});
    return json(me());
  };
  await h.box.signIn('Mark.don', 'secret');
  await h.box.openTrip('NZ7K2H');
  h.state.phone = '';
  h.state.email = '';
  h.state.confirm = true;
  await h.box.submitRefund();
  assert.equal(calls.filter(c => c.url === '/api/refund-requests').length, 0);
  assert.match(h.box.passengerView(), /How can we reach you\?/);
  assert.match(h.box.passengerView(), /Enter at least one\./);
  h.state.phone = 'abc';
  h.state.email = '';
  h.state.confirm = true;
  await h.box.submitRefund();
  assert.match(h.box.passengerView(), /Enter a valid mobile number\./);
  h.state.phone = '+64 21 555 0100';
  h.state.email = '';
  h.state.confirm = true;
  assert.equal(h.box.validateRefund(), true);
});

test('the request screen shows the refund destination with no method choice', async () => {
  const h = harness();
  h.box.fetch = passengerSession();
  await h.box.signIn('Mark.don', 'secret');
  await h.box.openTrip('NZ7K2H');
  const html = h.box.passengerView();
  assert.match(html, /Refund to Visa •••• 4242/);
  assert.match(html, /The card you used to book this ticket\./);
  assert.doesNotMatch(html, /bank-transfer|<select|type="radio"/);
});

test('the status screen shows Refund to and declined contact line', async () => {
  const h = harness();
  const declined = request({status: 'declined', decisionNote: 'Fare rules apply.',
    phone: '+64 21 555 0100', contact: {phone: '+64 21 555 0100', email: 'mark@example.com'}});
  h.box.fetch = passengerSession(me({request: declined}));
  await h.box.signIn('Mark.don', 'secret');
  await h.box.openTrip('NZ7K2H');
  const html = h.box.passengerView();
  assert.match(html, /<dt>Refund to<\/dt><dd>Visa •••• 4242<\/dd>/);
  assert.doesNotMatch(html, /<dd>Refund to Visa/);
  assert.match(html, /Fare rules apply\./);
  assert.match(html, /Our customer service team will contact you at \+64 21 555 0100\./);
  const emailOnly = request({status: 'declined', decisionNote: 'Fare rules apply.',
    phone: '', contact: {phone: '', email: 'mark@example.com'}});
  const h2 = harness();
  h2.box.fetch = passengerSession(me({request: emailOnly}));
  await h2.box.signIn('Mark.don', 'secret');
  await h2.box.openTrip('NZ7K2H');
  assert.match(h2.box.passengerView(), /Our customer service team will contact you at mark@example\.com\./);
});

test('staff expanded rows show mobile, email and refund destination', async () => {
  const h = await staffSuccessfulSignIn();
  h.state.staff.expanded = 'AF-DEMO000002';
  const html = h.box.staffView();
  assert.match(html, /Mobile \+64 21 555 0100/);
  assert.match(html, /Email mark@example\.com/);
  assert.match(html, /Refund to Visa •••• 4242/);
});

test('opening a trip reloads the latest status from the service', async () => {
  const h = harness();
  let meCalls = 0;
  h.box.fetch = async url => {
    if (url === '/api/auth/login') return json({token: 'tok', role: 'passenger', displayName: 'Mark Don'});
    if (url === '/api/me') {
      meCalls += 1;
      return json(meCalls === 1 ? me() : me({request: request({status: 'approved'})}));
    }
    throw new Error('Unexpected network call: ' + url);
  };
  await h.box.signIn('Mark.don', 'secret');
  assert.match(h.box.passengerView(), /Refund available/);
  await h.box.openTrip('NZ7K2H');
  assert.ok(meCalls >= 2);
  assert.match(h.box.passengerView(), /Refund approved/);
  h.state.refreshing = true;
  assert.match(h.box.passengerView(), /Updating your trips/);
  h.state.refreshing = false;
});

test('going home reloads trips and a failed reload keeps the view with an error', async () => {
  const h = harness();
  let meCalls = 0;
  let failNext = false;
  h.box.fetch = async url => {
    if (url === '/api/auth/login') return json({token: 'tok', role: 'passenger', displayName: 'Mark Don'});
    if (url === '/api/me') {
      meCalls += 1;
      if (failNext) throw new Error('offline');
      return json(me());
    }
    throw new Error('Unexpected network call: ' + url);
  };
  await h.box.signIn('Mark.don', 'secret');
  const before = meCalls;
  await h.box.openTrip('NZ7K2H');
  assert.ok(meCalls > before);
  assert.match(h.box.passengerView(), /Request full refund/);
  failNext = true;
  await h.box.goHome();
  assert.equal(h.state.selectedBooking, null);
  assert.match(h.box.passengerView(), /My trips/);
  assert.match(h.box.passengerView(), /We could not reach the service/);
});

(async () => {
  for (const {name, fn} of tests) { await fn(); console.log(`PASS ${name}`); }
  console.log(`${tests.length} frontend regression checks passed.`);
})().catch(error => { console.error(error); process.exitCode = 1; });
