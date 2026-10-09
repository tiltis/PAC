// node --test station/tests/test_reason_presentation.cjs
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../web/index.html'), 'utf8');
const code = html.split('// PAC_REASON_PRESENTATION_START')[1].split('// PAC_REASON_PRESENTATION_END')[0];
const context = vm.createContext({});
vm.runInContext(code, context);
const {describeInspection, summarizeRun, reasonLabel, describeChecks} = context.PacReasons;
const inspected = overrides => ({
  face:'B', attempt:0, status:'ok', verdict:'suspect', reasons:['tape_missing_count_1'],
  features:{defect_inspected:true, tape_expected:3, tape_present_count:2, tape_missing_count:1}, ...overrides
});

test('all inline browser scripts parse', () => {
  for (const match of html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/g)) new vm.Script(match[1]);
});
test('idle null run and missing inspection records are accepted', () => {
  assert.equal(summarizeRun(null).title, '검사 진행 중');
  assert.equal(summarizeRun({inspections:[null]}).faces.length, 0);
});
test('real field contract: one tape missing, remaining face skipped', () => {
  const report = summarizeRun({final_verdict:'suspect', bin:'human', inspections:[inspected()], skipped_faces:['C']});
  assert.equal(report.kind, 'defect');
  assert.equal(report.title, '빨강 분류 이유');
  assert.equal(report.lines[0], '테이프 1개 누락');
  assert.match(report.lines[1], /일부 검사 미완료/);
});
test('bottom failure reason is explicit but retains uncertainty', () => {
  const report = describeInspection(inspected({face:'C', reasons:['bottom_open'], features:{defect_inspected:true, bottom_open:true}}));
  assert.equal(report.title, '아랫면 결함(벌어짐 의심)');
});
test('unvalidated count/bottom features do not become defects', () => {
  const report = describeInspection(inspected({verdict:'review', reasons:['defect_rules_unvalidated'],
    features:{defect_inspected:false, tape_expected:3, tape_present_count:2, tape_missing_count:1, bottom_open:true}}));
  assert.equal(report.kind, 'review');
  assert.match(report.title, /검사 기준값 미검증/);
  assert.doesNotMatch(report.title, /누락|아랫면 결함/);
  assert.match(report.details.join(' '), /미확정/);
});
test('malformed suspect without evidence stays confirmation-needed', () => {
  const report = describeInspection(inspected({features:{tape_missing_count:1, bottom_open:true}}));
  assert.equal(report.kind, 'review');
  assert.doesNotMatch(report.title, /테이프 1개 누락|아랫면 결함/);
});
test('missing measurement and extra blobs are not a missing-tape verdict', () => {
  for (const reason of ['tape_threshold_missing_count', 'tape_extra_blobs', 'bottom_box_not_found']) {
    const report = describeInspection(inspected({verdict:'review', reasons:[reason],
      features:{defect_inspected:true, tape_expected:3, tape_present_count:null, tape_missing_count:null}}));
    assert.equal(report.kind, 'review'); assert.doesNotMatch(report.title, /\d개 누락|아랫면 결함/);
    assert.match(report.details[0], /개수 확인 불가/);
  }
});
test('reinspection supersedes earlier failed view', () => {
  const report = summarizeRun({final_verdict:'no_anomaly', bin:'ok', inspections:[
    inspected({attempt:1, verdict:'no_anomaly', reasons:[], features:{defect_inspected:true}}),
    inspected({attempt:0})
  ]});
  assert.equal(report.faces.length, 1); assert.equal(report.kind, 'ok');
  assert.doesNotMatch(report.lines.join(' '), /누락/);
});
test('wrapping tape seen on two faces is never summed', () => {
  const report = summarizeRun({final_verdict:'suspect', bin:'human', inspections:[inspected({face:'A'}), inspected()]});
  assert.equal(report.lines.length, 1);
  assert.equal(report.lines[0], '테이프 1개 누락');
  assert.doesNotMatch(report.title + report.lines.join(' '), /테이프 2개 누락/);
});
test('fixed tape identifiers count actual reasons without counting thresholds', () => {
  const report = describeInspection(inspected({reasons:['tape_missing_T1','tape_missing_T2','tape_missing_T1'],
    features:{defect_inspected:true, tape_expected:3, tape_present_count:1}}));
  assert.equal(report.title, '테이프 2개 누락');
  assert.equal(report.details[0], '누락 위치: T1, T2');
  assert.equal(reasonLabel('tape_missing_count_1'), '테이프 1개 누락');
});
test('multiple existing defect reasons are retained', () => {
  const report = describeInspection(inspected({reasons:['tape_missing_count_1','bottom_open','coolant_absent']}));
  assert.match(report.title, /테이프 1개 누락/); assert.match(report.title, /아랫면 결함/);
  assert.match(report.title, /냉매 누락 의심/);
});
test('measurement failure and simulation remain separate from confirmed defect', () => {
  const bad = describeInspection(inspected({status:'error', error:'camera disconnected'}));
  assert.equal(bad.kind, 'error'); assert.equal(bad.title, '검사 실패');
  const simulated = describeInspection(inspected({sensor_data:{simulated:true}}));
  assert.equal(simulated.kind, 'review'); assert.doesNotMatch(simulated.title, /테이프 1개 누락/);
});
test('stopped run with no decision reports incomplete rather than a red classification', () => {
  const report = summarizeRun({state:'error', final_verdict:null, error:'sensor disconnected', inspections:[]});
  assert.equal(report.kind, 'error'); assert.equal(report.title, '검사 중단·분류 미완료');
  assert.doesNotMatch(report.title, /빨강/);
});
test('unknown reason text is retained for diagnosis and prototype keys stay strings', () => {
  assert.equal(reasonLabel('constructor'), '추가 확인: constructor');
  assert.equal(reasonLabel('<img src=x onerror=alert(1)>'), '추가 확인: <img src=x onerror=alert(1)>');
  assert.match(html, /el\.querySelector\('\.reasons'\)\.textContent = check\.title/);
});

test('one captured pose can populate tape and coolant cards independently', () => {
  const cards = describeChecks([inspected({reasons:['coolant_absent'], features:{defect_inspected:true,
    tape_expected:3, tape_present_count:3, coolant_present:false}})]);
  assert.equal(cards[0].title, '테이프 3개 확인');
  assert.equal(cards[0].kind, 'ok');
  assert.equal(cards[1].kind, 'waiting');
  assert.equal(cards[2].title, '냉매 누락 의심');
  assert.equal(cards[2].kind, 'defect');
  assert.doesNotMatch(cards.map(c => c.label+c.title).join(' '), /[ABC]면/);
});

test('unvalidated features stay confirmation-needed in semantic cards', () => {
  const cards = describeChecks([inspected({verdict:'review', reasons:['defect_rules_unvalidated'],
    features:{defect_inspected:false, tape_present_count:2, tape_expected:3, bottom_open:true, coolant_present:false}})]);
  assert.ok(cards.every(c => c.kind === 'review'));
  assert.doesNotMatch(cards.map(c => c.title).join(' '), /누락|결함/);
});

test('semantic cards use reinspection and never add wrapping-tape counts', () => {
  let cards = describeChecks([inspected({attempt:0}), inspected({attempt:1,verdict:'no_anomaly',reasons:[],
    features:{defect_inspected:true,tape_expected:3,tape_present_count:3}})]);
  assert.equal(cards[0].kind, 'ok');
  cards = describeChecks([inspected({face:'A'}),inspected()]);
  assert.equal(cards[0].title,'테이프 1개 누락');
});

test('routing policy missing evidence has a named confirmation reason', () => {
  const report = summarizeRun({final_verdict:'review',bin:'human',policy:{checks:{coolant:null,bottom:true,tape3:true}}});
  assert.equal(report.lines[0],'냉매 확인 필요');
  assert.doesNotMatch(report.lines.join(' '), /누락 의심|[ABC]면/);
});
