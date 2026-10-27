const assert = require('node:assert/strict');
const {operationsSummary} = require('../static/dashboard-data.js');
const base = {business_date: '2026-10-27', timezone: '+0800', tasks: {
  draft: [{task_uid:'a',version:1,product:'任务 A'}], pending_review: [], approved_unpublished: []
}, actions:[{target:'/script?task=a&version=1',reason:'补资料'}], published:{records:[]}};
const records = [
  {platform:'dy', platform_post_id:'1', published_at:'2026-10-26T17:00:00Z', registered_at:1},
  {platform:'dy', platform_post_id:'1', published_at:'2026-10-26T17:00:00Z', registered_at:2},
  {platform:'xhs', platform_post_id:'2', published_at:'2026-10-20T23:30:00Z'},
  {platform:'dy', platform_post_id:'3', published_at:'2026-09-30T23:30:00Z'},
  {platform:'dy', platform_post_id:'4', published_at:'invalid'},
  {platform:'dy', platform_post_id:'5', published_at:'2026-10-27T08:00:00+08:00', simulated:1}
];
const summary = operationsSummary({...base,published:{records}}, [{state:'todo'},{state:'done'}]);
assert.equal(summary.weekOutput,1,'published works dedupe by platform and ID; demo and invalid timestamps excluded');
assert.deepEqual(summary.week.map(day=>day.count),[1,0,0,0,0,0,1],'business timezone governs seven calendar days');
assert.equal(summary.focusCount,2,'action list and unfinished advice counted once each');
assert.equal(summary.projects.length,1);
assert.equal(summary.projects[0].label,'待补资料');
assert.equal(summary.contentTypesKnown,false,'missing content types cannot become invented pie slices');
assert.equal(operationsSummary(base,[]).weekOutput,0,'successful empty local records can report zero');
assert.equal(operationsSummary({...base,published:{records:[{platform:'dy',platform_post_id:'6',published_at:'invalid'}]}},[]).weekOutput,null,'unknown publish dates cannot report a fabricated zero');
console.log('PASS operation summary: identity dedupe, timezone, missing dates, demo exclusion, real followups');
