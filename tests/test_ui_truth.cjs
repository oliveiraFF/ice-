const assert=require('node:assert/strict');
const {taskPresentation}=require('../static/creative.js');
assert.equal(taskPresentation(null).state,'未开始');
for(const [status,label] of Object.entries({processing:'处理中',failed:'失败',validation_failed:'失败',result_unconfirmed:'结果未确认',success:'成功'})){
 const p=taskPresentation({version:1,input:{},attempts:[{input_version:1,status}],result:status==='success'?{report:{}}:null});
 assert.equal(p.state,label);assert.equal(p.qualityUnlocked,false);assert(p.checks.some(c=>c[1]==='未测'));
}
assert.equal(taskPresentation({version:1,input:{},attempts:[]}).state,'待补资料');
assert.equal(taskPresentation({version:3,input:{},attempts:[{input_version:1,status:'success'}],result:null}).state,'待补资料');
assert.equal(taskPresentation({version:2,input:{},attempts:[{input_version:1,status:'success'}],result:{report:{}}},true).checks[0][1],'需重跑');
console.log('UI truth gates passed: six states; no unmeasured quality score');
