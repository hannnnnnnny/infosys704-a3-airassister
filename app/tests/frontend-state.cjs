'use strict';
// Runs the actual browser functions in an isolated VM. No network or database.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const publicDir = path.join(__dirname, '..', 'public');
const helpers = fs.readFileSync(path.join(publicDir, 'workflow-state.js'), 'utf8');
const fullApp = fs.readFileSync(path.join(publicDir, 'app.js'), 'utf8');
const app = fullApp.slice(0, fullApp.lastIndexOf("document.addEventListener('click',"));
function storage() {
  const values = new Map();
  return {getItem:k=>values.get(k)||null,setItem:(k,v)=>values.set(k,String(v)),removeItem:k=>values.delete(k)};
}
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes,no)=>{resolve=yes;reject=no});
  return {promise,resolve,reject};
}
function harness(store=storage(), view='journey') {
  const nodes = new Map();
  const body = {};
  const main = {contains:()=>false,focus(){},innerHTML:''};
  const document = {body,activeElement:body,querySelector:s=>s==='main'?main:nodes.get(s)||null,querySelectorAll:()=>[],addEventListener(){}};
  const box = {document,history:{},location:{search:`?view=${view}`},sessionStorage:store,crypto:webcrypto,URLSearchParams,AbortController,Blob,URL,Intl,Date,console,setTimeout,clearTimeout,requestAnimationFrame(){},window:{scrollTo(){}}};
  vm.createContext(box);
  vm.runInContext(helpers,box);
  vm.runInContext(app,box);
  const state = vm.runInContext('state',box);
  const renders=[],focus=[];
  box.render=()=>renders.push({view:box.location.search,booking:state.booking?.reference,track:state.trackRecord?.publicReference,sap:state.sapRecord?.id});
  box.focusResult=s=>focus.push(s);
  box.persist=()=>{};
  return {box,state,store,nodes,renders,focus};
}
function sampleCase(version=1, ref='AF-123456789ABC', email='review@example.com') {
  return {request:{publicReference:ref,bookingReference:'NZ7K2H',email,lastName:'Taylor',reason:'flight_cancelled',details:'',createdAt:'2026-10-08T01:00:00Z',updatedAt:'2026-10-08T01:00:00Z',status:'submitted',statusLabel:'Received - awaiting local review'},booking:{traveller:'Alex Taylor',fromCode:'AKL',toCode:'WLG',flight:'NZ423',date:'2026-10-15',flightStatus:'cancelled',channel:'direct',ticketValue:248,currency:'NZD',source:{label:'Sample journey'}},version,checks:{paymentEvidenceReviewed:false,refundRulesReviewed:false,supportingDetailsReviewed:false},paymentReference:'',specialistRequired:false,reviewNote:'',reviewState:'not_started',checklist:[],triage:{route:'information_needed',label:'Needs information',queue:'Information follow-up',ownerRole:'Local reviewer',reasons:['Payment review missing'],readyForHandoff:false,ruleVersion:'prototype-v1'},events:[],financialReference:null};
}
function queueCase(ref,email,state='not_started',queue='Standard review') {
  return {publicReference:ref,email,reason:'flight_cancelled',reviewState:state,version:0,createdAt:'2026-10-08T01:00:00Z',updatedAt:'2026-10-09T02:00:00Z',triage:{route:'standard',routeLabel:'Standard review',queue}};
}
function select(h,c=sampleCase()) {h.state.caseData=c;h.state.caseLookup={reference:c.request.publicReference,email:c.request.email};h.box.restoreReviewDraft(c);return c;}
const tests=[];
const test=(name,fn)=>tests.push({name,fn});
test('booking out-of-order response never replaces newer booking; inputs lock',async()=>{
  const h=harness(), old=deferred(), recent=deferred();const calls=[];
  h.box.api=(url,opts)=>{calls.push({url,opts});return calls.length===1?old.promise:recent.promise};
  h.state.lookup={reference:'NZ7K2H',lastName:'Taylor'};const first=h.box.loadBooking();
  assert.match(h.box.bookingForm(),/value="NZ7K2H" disabled/);
  h.state.lookup={reference:'NZ8T3H',lastName:'Taylor'};const second=h.box.loadBooking();
  assert.equal(calls[0].opts.signal.aborted,true);assert.match(calls[0].url,/reference=NZ7K2H/);
  recent.resolve({booking:{reference:'NZ8T3H'}});await second;const count=h.renders.length;
  old.resolve({booking:{reference:'NZ7K2H'}});await first;
  assert.equal(h.state.booking.reference,'NZ8T3H');assert.equal(h.renders.length,count);
});
test('tracking captures the correct owner and disables saved-request shortcut',async()=>{
  const h=harness(storage(),'track'), a=deferred(), b=deferred();let n=0;const calls=[];
  h.box.api=(url,opts)=>{calls.push({url,opts});return ++n===1?a.promise:b.promise};
  h.state.lastRequest={reference:'AF-OLD',email:'old@example.com'};h.state.track={...h.state.lastRequest};const first=h.box.lookupRequest();
  assert.match(h.box.track(),/id="use-saved-request" type="button" disabled/);
  h.state.track={reference:'AF-NEW',email:'new@example.com'};const second=h.box.lookupRequest();
  assert.match(calls[0].url,/email=old%40example.com/);assert.equal(calls[0].opts.signal.aborted,true);
  b.resolve({request:{publicReference:'AF-NEW',email:'new@example.com'}});await second;
  a.resolve({request:{publicReference:'AF-OLD',email:'old@example.com'}});await first;
  assert.equal(h.state.trackRecord.email,'new@example.com');assert.equal(h.state.lastRequest.reference,'AF-NEW');
});
test('financial query rejects delayed old errors after a newer success',async()=>{
  const h=harness(storage(),'financial'), a=deferred(), b=deferred();let n=0;h.state.staffUnlocked=true;
  h.box.api=()=>++n===1?a.promise:b.promise;h.state.sapId='60000002';const first=h.box.lookupFinancialDocument();
  assert.match(h.box.financial(),/value="60000002" disabled/);
  h.state.sapId='60000003';const second=h.box.lookupFinancialDocument();
  b.resolve({record:{id:'60000003'}});await second;
  a.reject(new Error('Old query error'));await first;
  assert.equal(h.state.sapRecord.id,'60000003');assert.equal(h.state.sapError,null);
});
test('navigation cancels pending reads without rendering old results',async()=>{
  for(const [view,fn,input,key,result] of [['journey','loadBooking','lookup','booking',{booking:{reference:'OLD'}}],['track','lookupRequest','track','trackRecord',{request:{publicReference:'OLD',email:'old@example.com'}}],['financial','lookupFinancialDocument','sapId','sapRecord',{record:{id:'OLD'}}]]){
    const h=harness(storage(),view), wait=deferred();let signal;
    h.box.api=(url,opts)=>{signal=opts.signal;return wait.promise};
    h.state[input]=input==='sapId'?'60000002':input==='lookup'?{reference:'NZ7K2H',lastName:'Taylor'}:{reference:'AF-OLD',email:'old@example.com'};
    const pending=h.box[fn]();h.box.cancelReadViews('help');h.box.location.search='?view=help';const count=h.renders.length;
    wait.resolve(result);await pending;assert.equal(signal.aborted,true);assert.equal(h.state[key],null);assert.equal(h.renders.length,count);
  }
});
test('editing query input clears stale data and error feedback',()=>{
  const h=harness();
  for(const name of ['booking','track','financial'])h.nodes.set(`#${name}-response`,{setAttribute(k){this[k]=true}});
  h.state.booking={reference:'OLD'};h.state.bookingError=new Error('Old booking error');
  h.state.trackRecord={publicReference:'OLD'};h.state.trackError=new Error('Old owner error');
  h.state.sapRecord={id:'OLD'};h.state.sapError=new Error('Old SAP error');
  for(const name of ['booking','track','financial'])h.box.clearReadInput(name);
  for(const key of ['booking','bookingError','trackRecord','trackError','sapRecord','sapError'])assert.equal(h.state[key],null);
  for(const name of ['booking','track','financial'])assert.equal(h.nodes.get(`#${name}-response`).hidden,true);
});
test('review note/check/reference draft survives VM reload without a POST',()=>{
  const store=storage(), h=harness(store,'staff'), c=select(h);h.state.caseDraft.checks.paymentEvidenceReviewed=true;h.state.caseDraft.paymentReference='LOCAL-12';h.state.caseDraft.specialistRequired=true;h.state.caseDraft.note='Unsaved check note.';h.box.retainReviewDraft();
  const reloaded=harness(store,'staff');let calls=0;reloaded.box.api=()=>{calls++;throw new Error('Unexpected write')};select(reloaded,c);
  assert.equal(reloaded.state.caseDraft.note,'Unsaved check note.');assert.equal(reloaded.state.caseDraft.paymentReference,'LOCAL-12');assert.equal(reloaded.state.caseDraft.checks.paymentEvidenceReviewed,true);assert.equal(reloaded.state.caseDraft.specialistRequired,true);assert.equal(reloaded.state.caseDraftRetained,true);assert.equal(calls,0);
});
test('review drafts cannot cross owner or case reference',()=>{
  const store=storage(), h=harness(store,'staff');select(h);h.state.caseDraft.note='Private draft';h.box.retainReviewDraft();
  const other=harness(store,'staff');select(other,sampleCase(1,'AF-123456789ABC','other@example.com'));assert.equal(other.state.caseDraft.note,'');
  select(other,sampleCase(1,'AF-987654321ABC','review@example.com'));assert.equal(other.state.caseDraft.note,'');
});
test('older-version recovered draft blocks save and handoff until explicitly reviewed',async()=>{
  const store=storage(), h=harness(store,'staff');select(h);h.state.caseDraft.note='Draft at version one';h.state.caseDraft.checks.refundRulesReviewed=true;h.box.retainReviewDraft();
  const reloaded=harness(store,'staff');select(reloaded,sampleCase(2));let calls=0;reloaded.box.api=()=>{calls++;throw new Error('Must not write')};
  assert.equal(reloaded.state.caseDraft.version,1);assert.equal(reloaded.state.caseDraftGuard,true);
  await reloaded.box.submitCaseAction('save_review');await reloaded.box.submitCaseAction('handoff');assert.equal(calls,0);
  assert.match(reloaded.box.caseReviewForm(reloaded.state.caseData),/Keep and review these entries/);
});
test('keeping an old draft adopts current version but still requires a fresh save before handoff',async()=>{
  const store=storage(), h=harness(store,'staff');select(h);h.state.caseDraft.note='Held note';h.box.retainReviewDraft();select(h,sampleCase(2));h.box.keepReviewDraft();
  assert.equal(h.state.caseDraft.version,2);assert.equal(h.state.caseDraftGuard,false);assert.equal(h.state.caseDraftMustSave,true);
  let calls=0;h.box.api=()=>{calls++};await h.box.submitCaseAction('handoff');assert.equal(calls,0);
});
test('discard draft restores server checks and does not write to the backend',()=>{
  const store=storage(), h=harness(store,'staff'), c=select(h);h.state.caseDraft.note='Discard me';h.state.caseDraft.checks.paymentEvidenceReviewed=true;h.box.retainReviewDraft();let calls=0;h.box.api=()=>{calls++};h.box.discardReviewDraft();
  assert.equal(h.state.caseDraft.note,'');assert.equal(h.state.caseDraft.checks.paymentEvidenceReviewed,false);assert.equal(h.state.caseDraftRetained,false);assert.equal(calls,0);assert.equal(vm.runInContext('reviewDrafts.restore(state.caseData)',h.box),null);
});
test('successful explicit save removes session draft and records server version',async()=>{
  const store=storage(), h=harness(store,'staff'), c=select(h);h.state.caseDraft.note='Save this note';h.box.retainReviewDraft();const saved={...c,version:2,reviewState:'prepared'};
  h.box.api=async(url,opts)=>{assert.equal(opts.body.note,'Save this note');assert.equal(opts.body.version,1);return {case:saved}};
  await h.box.submitCaseAction('save_review');assert.equal(h.state.caseData.version,2);assert.equal(h.state.caseDraft.note,'');assert.equal(h.state.caseDraftMustSave,false);assert.equal(vm.runInContext('reviewDrafts.restore(state.caseData)',h.box),null);
});
test('saved-review handoff is an independent button using the saved note and current version',async()=>{
  const h=harness(storage(),'staff'), c=select(h);h.state.caseDraft.note='Evidence checked and ready.';h.state.caseDraft.checks.paymentEvidenceReviewed=true;h.state.caseDraft.checks.refundRulesReviewed=true;h.state.caseDraft.paymentReference='LOCAL-12';h.box.retainReviewDraft();const calls=[];
  const ready={...c,version:2,note:'Evidence checked and ready.',checks:{paymentEvidenceReviewed:true,refundRulesReviewed:true,supportingDetailsReviewed:false},paymentReference:'LOCAL-12',reviewState:'prepared',triage:{...c.triage,route:'standard',readyForHandoff:true}};
  h.box.api=async(url,opts)=>{calls.push(opts.body);return {case:opts.body.action==='save_review'?ready:{...ready,version:3,reviewState:'queued'}}};
  await h.box.submitCaseAction('save_review');assert.equal(h.state.caseDraft.note,'');assert.equal(h.state.caseDraftMustSave,false);
  assert.match(h.box.caseReviewForm(h.state.caseData),/data-case-action="handoff" type="button"/);
  let click;h.nodes.set('.case-handoff-button',{addEventListener:(event,callback)=>{if(event==='click')click=callback}});h.box.bindCaseForms();assert.equal(typeof click,'function');await click();
  assert.equal(calls.length,2);assert.equal(calls[0].action,'save_review');assert.equal(calls[1].action,'handoff');assert.equal(calls[1].version,2);assert.equal(calls[1].note,'Evidence checked and ready.');assert.equal(h.state.caseData.reviewState,'queued');
});
test('saved-review handoff stays blocked by a new unsaved note or evidence edit',async()=>{
  const h=harness(storage(),'staff'), c=sampleCase(2);c.note='Authoritative saved review note';c.reviewState='prepared';c.triage.readyForHandoff=true;select(h,c);let calls=0;h.box.api=()=>{calls++};
  h.state.caseDraft.note='An unsaved new note';h.box.retainReviewDraft();await h.box.submitCaseAction('handoff');assert.equal(calls,0);
  h.box.discardReviewDraft();h.state.caseDraft.checks.paymentEvidenceReviewed=true;h.box.retainReviewDraft();await h.box.submitCaseAction('handoff');assert.equal(calls,0);
});
test('server conflict refresh retains old version and requires explicit review; no automatic retry',async()=>{
  const h=harness(storage(),'staff'), c=select(h);h.state.caseDraft.note='Unsaved concurrent edit';h.state.caseDraft.paymentReference='LOCAL-DRAFT';h.box.retainReviewDraft();const calls=[];
  h.box.api=async(url,opts)=>{calls.push({url,opts});if(opts?.method==='POST')throw Object.assign(new Error('Changed'),{status:409,code:'REVIEW_VERSION_CONFLICT'});return {case:{...c,version:2}}};
  await h.box.submitCaseAction('save_review');assert.equal(calls.length,2);assert.equal(h.state.caseData.version,2);assert.equal(h.state.caseDraft.version,1);assert.equal(h.state.caseDraft.note,'Unsaved concurrent edit');assert.equal(h.state.caseDraft.paymentReference,'LOCAL-DRAFT');assert.equal(h.state.caseDraftGuard,true);
});
test('SAP capture is blocked by unsaved review draft',async()=>{
  const h=harness(storage(),'staff');select(h);h.state.caseDraft.note='Do not lose this';h.box.retainReviewDraft();let calls=0;h.box.api=()=>{calls++};h.state.caseFinancialNote='SAP capture';await h.box.captureCaseFinancialReference();assert.equal(calls,0);assert.equal(h.state.caseDraft.note,'Do not lose this');
});
test('successful SAP capture retains true source and does not check review evidence',async()=>{
  const h=harness(storage(),'staff'), c=select(h);h.state.caseFinancialNote='Reference demonstration';const snapshot={documentId:'60000002',record:{id:'60000002',totalNetAmount:1000,currency:'USD',referenceDocument:'90000003',processStatusCode:'C',approvalStatusCode:''},source:{label:'SAP public sandbox - read-only GET',fetchedAt:'2026-10-08T01:00:00Z'},capturedAt:'2026-10-08T01:00:00Z',context:'demonstration_only',bookingMatch:'not_verified',paymentVerification:'not_performed',refundEligibility:'not_assessed'};
  h.box.api=async(url,opts)=>{assert.equal(url,'/api/review-cases/financial-reference');assert.equal(opts.body.documentId,'60000002');assert.equal(opts.body.version,1);return {case:{...c,version:2,financialReference:snapshot}}};await h.box.captureCaseFinancialReference();
  assert.equal(h.state.caseData.checks.paymentEvidenceReviewed,false);assert.equal(h.state.caseData.triage.route,'information_needed');assert.equal(h.state.caseData.reviewState,'not_started');const html=h.box.caseFinancialReference(h.state.caseData);assert.match(html,/USD/);assert.match(html,/Not verified/);assert.match(html,/Not performed/);assert.match(html,/Refund eligibility not assessed/);
});
test('SAP error creates no fallback snapshot and retains capture input',async()=>{
  const h=harness(storage(),'staff'), c=select(h);h.state.caseFinancialNote='Keep capture note';h.box.api=async()=>{throw Object.assign(new Error('SAP unavailable'),{status:503,code:'SAP_UNAVAILABLE'})};await h.box.captureCaseFinancialReference();assert.equal(h.state.caseData,c);assert.equal(h.state.caseData.financialReference,null);assert.equal(h.state.caseData.events.length,0);assert.equal(h.state.caseFinancialNote,'Keep capture note');assert.equal(h.state.caseFinancialError.message,'SAP unavailable');
});
test('new case lookup clears the prior case financial note/error even after input cleared selection',async()=>{
  const h=harness(storage(),'staff');select(h);h.state.caseFinancialId='60000099';h.state.caseFinancialNote='Failed capture note for case A';h.box.api=async()=>{throw Object.assign(new Error('Case A SAP error'),{status:503,code:'SAP_UNAVAILABLE'})};await h.box.captureCaseFinancialReference();assert.equal(h.state.caseFinancialError.message,'Case A SAP error');
  h.state.caseData=null;h.state.caseDraft=null;const other=sampleCase(1,'AF-999999999999','other@example.com');h.state.caseLookup={reference:other.request.publicReference,email:other.request.email};h.box.api=async()=>({case:other});await h.box.loadCase();
  assert.equal(h.state.caseData,other);assert.equal(h.state.caseFinancialId,'60000002');assert.equal(h.state.caseFinancialNote,'');assert.equal(h.state.caseFinancialError,null);
});
test('same-case lookup retry keeps the intentional capture note and document input',async()=>{
  const h=harness(storage(),'staff'), c=select(h);h.state.caseFinancialId='60000099';h.state.caseFinancialNote='Intentional retry note';h.box.api=async()=>{throw Object.assign(new Error('Temporary SAP error'),{status:503,code:'SAP_UNAVAILABLE'})};await h.box.captureCaseFinancialReference();
  h.state.caseData=null;h.state.caseDraft=null;h.box.api=async()=>({case:{...c,version:2}});await h.box.loadCase();
  assert.equal(h.state.caseFinancialId,'60000099');assert.equal(h.state.caseFinancialNote,'Intentional retry note');assert.equal(h.state.caseFinancialError.message,'Temporary SAP error');
});
test('late review mutation cannot overwrite a different selected case or draft',async()=>{
  const h=harness(storage(),'staff'), original=select(h), wait=deferred();h.state.caseDraft.note='Original review note';h.box.api=()=>wait.promise;const pending=h.box.submitCaseAction('save_review');const other=sampleCase(1,'AF-999999999999','other@example.com');select(h,other);h.state.caseDraft.note='New case unsaved note';const count=h.focus.length;wait.resolve({case:{...original,version:2}});await pending;assert.equal(h.state.caseData,other);assert.equal(h.state.caseDraft.note,'New case unsaved note');assert.equal(h.focus.length,count);
});
test('late capture mutation cannot overwrite a different selected case or capture note',async()=>{
  const h=harness(storage(),'staff'), original=select(h), wait=deferred();h.state.caseFinancialNote='Original capture';h.box.api=()=>wait.promise;const pending=h.box.captureCaseFinancialReference();const other=sampleCase(1,'AF-999999999999','other@example.com');select(h,other);h.state.caseFinancialNote='New case capture note';const count=h.focus.length;wait.resolve({case:{...original,version:2}});await pending;assert.equal(h.state.caseData,other);assert.equal(h.state.caseFinancialNote,'New case capture note');assert.equal(h.focus.length,count);
});
test('mutation can complete after navigation without forcing focus or routing back',async()=>{
  const h=harness(storage(),'staff'), original=select(h), wait=deferred();h.state.caseDraft.note='Save local review';h.box.api=()=>wait.promise;const pending=h.box.submitCaseAction('save_review');h.box.location.search='?view=journey';const count=h.focus.length;wait.resolve({case:{...original,version:2}});await pending;assert.equal(h.state.caseData.version,2);assert.equal(h.box.location.search,'?view=journey');assert.equal(h.focus.length,count);
});
test('missing financial amount or currency is never rendered as zero',()=>{
  const h=harness();assert.equal(h.box.money(null,'USD'),'Not supplied');assert.equal(h.box.money(1000,null),'Not supplied');assert.match(h.box.money(0,'USD'),/0\.00/);
});
test('optional SAP context is collapsed until requested, but a failure reveals recovery and retains the boundary',()=>{
  const h=harness(storage(),'staff'),c=select(h);
  let html=h.box.caseFinancialReference(c);
  assert.doesNotMatch(html,/data-case-panel="financial" open/);
  assert.match(html,/<\/details><p class="case-financial-limit">Generic SAP sample only/);
  h.state.caseFinancialError=Object.assign(new Error('SAP unavailable'),{status:503,code:'SAP_UNAVAILABLE'});
  html=h.box.caseFinancialReference(c);
  assert.match(html,/data-case-panel="financial" open/);
  assert.match(html,/SAP unavailable/);
  assert.match(html,/id="case-financial-form"/);
  assert.match(html,/Booking match, payment and refund eligibility are not verified/);
});
test('panel choices survive same-case refresh and cannot leak into a different case',()=>{
  const h=harness(storage(),'staff'),c=select(h);
  h.state.casePanels.financial=true;h.state.casePanels.history=true;
  h.box.restoreReviewDraft({...c,version:2});
  assert.equal(h.state.casePanels.financial,true);assert.equal(h.state.casePanels.history,true);
  h.box.restoreReviewDraft(sampleCase(1,'AF-999999999999','other@example.com'));
  assert.deepEqual(Object.keys(h.state.casePanels),[]);
});
test('native disclosure toggle records the users choice without any case write',()=>{
  const h=harness(storage(),'staff');select(h);let toggle,posts=0;
  const panel={dataset:{casePanel:'financial'},open:true,addEventListener:(event,callback)=>{if(event==='toggle')toggle=callback}};
  h.box.document.querySelectorAll=selector=>selector==='[data-case-panel]'?[panel]:[];
  h.box.api=()=>posts++;h.box.bindCaseForms();assert.equal(typeof toggle,'function');toggle();
  assert.equal(h.state.casePanels.financial,true);panel.open=false;toggle();assert.equal(h.state.casePanels.financial,false);assert.equal(posts,0);
});
test('review action rail submits the named review form and queued cases expose only reopening',()=>{
  const h=harness(storage(),'staff'),c=select(h);let html=h.box.caseReviewForm(c);
  assert.match(html,/<\/form><div class="case-action-row case-action-rail"/);
  assert.match(html,/form="case-review-form" data-case-action="save_review" type="submit"/);
  assert.match(html,/data-case-action="handoff" type="button" disabled/);
  c.reviewState='queued';html=h.box.caseReviewForm(c);
  assert.match(html,/form="case-review-form" data-case-action="reopen" type="submit"/);
  assert.doesNotMatch(html,/data-case-action="handoff"/);
});
test('editing a review updates visible action status while the saved routing remains authoritative',()=>{
  const h=harness(storage(),'staff'),c=select(h);const status={},message={};
  h.nodes.set('#case-action-status',status);h.nodes.set('#case-action-message',message);
  h.state.caseDraft.note='Manual check note';h.box.retainReviewDraft();
  assert.equal(status.textContent,'Unsaved changes');assert.match(message.textContent,/Save changes before sending/);
  assert.equal(c.triage.readyForHandoff,false);assert.equal(c.reviewState,'not_started');
  h.state.caseDraftGuard=true;h.box.updateReviewDraftUI();assert.equal(status.textContent,'Review retained draft');assert.match(message.textContent,/Keep or discard/);
});
test('locked staff view hides review tools until a code is verified',()=>{
  const s=harness(storage(),'staff');const staffHtml=s.box.staff();
  assert.match(staffHtml,/Staff access code/);assert.match(staffHtml,/type="password"/);assert.match(staffHtml,/Unlock staff tools/);assert.match(staffHtml,/Shown in the server terminal at startup/);
  assert.doesNotMatch(staffHtml,/id="case-lookup"/);assert.doesNotMatch(staffHtml,/id="case-review-form"/);assert.doesNotMatch(staffHtml,/id="case-queue"/);
  const f=harness(storage(),'financial');const financialHtml=f.box.financial();
  assert.match(financialHtml,/Unlock staff tools/);assert.doesNotMatch(financialHtml,/id="document-form"/);assert.doesNotMatch(financialHtml,/id="financial-response"/);
});
test('wrong staff code stays locked and stores nothing',async()=>{
  const h=harness(storage(),'staff');let sent=null;
  h.box.api=async(url,opts)=>{sent=opts.headers['X-Staff-Code'];throw Object.assign(new Error('Unauthorized'),{status:401,code:'STAFF_UNAUTHORIZED'})};
  h.state.staffCode='wrong-code';await h.box.requestQueue({verifying:true});
  assert.equal(sent,'wrong-code');assert.equal(h.state.staffUnlocked,false);assert.equal(h.state.staffCode,'');assert.equal(h.store.getItem('airassist-staff-code-v1'),null);
  assert.match(h.box.staff(),/was not accepted/);assert.doesNotMatch(h.box.staff(),/id="case-lookup"/);
});
test('correct staff code unlocks, stores the code and loads the queue',async()=>{
  const h=harness(storage(),'staff');let url=null;
  h.box.api=async(target,opts)=>{url=target;assert.equal(opts.headers['X-Staff-Code'],'good-code');return {cases:[queueCase('AF-123456789ABC','review@example.com')]}};
  h.state.staffCode='good-code';await h.box.requestQueue({verifying:true});
  assert.equal(h.state.staffUnlocked,true);assert.equal(h.store.getItem('airassist-staff-code-v1'),'good-code');
  assert.match(url,/^\/api\/staff\/queue$/);assert.equal(h.state.queue.length,1);
  const html=h.box.staff();assert.match(html,/id="case-lookup"/);assert.match(html,/AF-123456789ABC/);
  h.box.lockStaff();
  assert.equal(h.state.staffUnlocked,false);assert.equal(h.store.getItem('airassist-staff-code-v1'),null);
  assert.doesNotMatch(h.box.staff(),/id="case-lookup"/);assert.match(h.box.staff(),/Unlock staff tools/);
});
test('selecting a queue row fills caseLookup and opens that case',async()=>{
  const h=harness(storage(),'staff');h.state.staffUnlocked=true;
  const ref='AF-123456789ABC',email='review@example.com';h.state.queue=[queueCase(ref,email)];
  let url=null;h.box.api=async target=>{url=target;return {case:sampleCase(1,ref,email)}};
  await h.box.openQueueCase(ref);
  assert.equal(url,'/api/review-cases?'+new URLSearchParams({reference:ref,email}).toString());
  assert.equal(h.state.caseLookup.reference,ref);assert.equal(h.state.caseLookup.email,email);
  assert.equal(h.state.caseData.request.publicReference,ref);assert.equal(h.state.caseData.request.email,email);
});
test('opening a queue case scrolls the case sheet into view and focuses its heading',async()=>{
  const h=harness(storage(),'staff');h.state.staffUnlocked=true;
  const ref='AF-123456789ABC',email='review@example.com';h.state.queue=[queueCase(ref,email)];
  let scrolled=null;h.nodes.set('#case-results',{scrollIntoView:options=>{scrolled=options}});
  h.box.api=async()=>({case:sampleCase(1,ref,email)});
  await h.box.openQueueCase(ref);
  assert.equal(h.focus.join(),'.case-head');assert.equal(scrolled.block,'start');
  let scrolledFailed=null;h.nodes.set('#case-results',{scrollIntoView:options=>{scrolledFailed=options}});
  h.box.api=async()=>{throw Object.assign(new Error('Not found'),{status:404,code:'CASE_NOT_FOUND'})};
  await h.box.openQueueCase(ref);
  assert.equal(scrolledFailed,null);assert.equal(h.focus.join(),'.case-head');
});
(async()=>{for(const {name,fn} of tests){await fn();console.log(`PASS ${name}`)}console.log(`${tests.length} frontend regression checks passed.`)})().catch(error=>{console.error(error);process.exitCode=1});
