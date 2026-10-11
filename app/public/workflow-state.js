/* Browser-only query tickets and unsaved review drafts. No server writes. */
(function (root) {
  'use strict';
  function createQueries() {
    const active = new Map();
    let sequence = 0;
    function cancel(name) {
      const old = active.get(name);
      if (old) { active.delete(name); old.controller.abort(); }
    }
    return {
      start(name, query) {
        cancel(name);
        const controller = new AbortController();
        const ticket = {
          id: ++sequence,
          query: Object.freeze({...query}),
          signal: controller.signal,
          controller,
          current() { return active.get(name) === ticket && !controller.signal.aborted; },
          finish() { if (active.get(name) === ticket) active.delete(name); }
        };
        active.set(name, ticket);
        return ticket;
      },
      cancel
    };
  }
  function createDrafts(storage, namespace) {
    const pair = c => [String(c.request.publicReference).toUpperCase(), String(c.request.email).trim().toLowerCase()];
    const key = (c, version = c.version) => JSON.stringify([...pair(c), version]);
    function read() {
      try { const value = JSON.parse(storage.getItem(namespace) || '{}'); return value && typeof value === 'object' && !Array.isArray(value) ? value : {}; }
      catch { return {}; }
    }
    function write(value) { try { storage.setItem(namespace, JSON.stringify(value)); } catch { /* Review saves never depend on storage. */ } }
    function valid(value) {
      return value && Number.isInteger(value.version) && value.version >= 0 && value.checks && typeof value.note === 'string' && typeof value.paymentReference === 'string';
    }
    function copy(value) {
      return {version:value.version, checks:{paymentEvidenceReviewed:value.checks.paymentEvidenceReviewed === true,refundRulesReviewed:value.checks.refundRulesReviewed === true,supportingDetailsReviewed:value.checks.supportingDetailsReviewed === true}, paymentReference:value.paymentReference.slice(0,80),specialistRequired:value.specialistRequired === true,note:value.note.slice(0,1000)};
    }
    return {
      save(c, draft) { if (!valid(draft)) return; const all=read(); all[key(c,draft.version)]={pair:pair(c),draft:copy(draft),retainedAt:Date.now()}; write(all); },
      restore(c) {
        const all=read(); const samePair=pair(c);
        const entries=Object.values(all).filter(v=>Array.isArray(v?.pair)&&v.pair[0]===samePair[0]&&v.pair[1]===samePair[1]&&valid(v.draft)).sort((a,b)=>Number(b.retainedAt)-Number(a.retainedAt));
        const entry=all[key(c)]&&valid(all[key(c)].draft)?all[key(c)]:entries[0];
        return entry?{draft:copy(entry.draft),versionMismatch:entry.draft.version!==c.version}:null;
      },
      discard(c) { const all=read(), samePair=pair(c); for(const [id,value] of Object.entries(all))if(value?.pair?.[0]===samePair[0]&&value?.pair?.[1]===samePair[1])delete all[id]; write(all); }
    };
  }
  root.AirAssistState = Object.freeze({createQueries,createDrafts});
})(globalThis);
