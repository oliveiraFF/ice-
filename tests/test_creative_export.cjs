const assert=require('node:assert/strict');
const {provenance}=require('../static/creative.js');
const task={task_uid:'test-task',version:2,account:{account_uid:'immutable-account',identity_state:'identity_pending'},
  strategy:{version:3,confirmed:1,data:{goal:'合成目标'}},rules:{version:'rules-v1',sha256:'rule-hash'},
  media:{media_id:'media-hash',filename:'demo.webm'},source:'user_saved',
  input:{product:'合成收纳盒',transcript:'人工台词',transcript_source:'manual',frames:[{at:0,image:'PRIVATE_BASE64'}]},
  attempts:[{raw_response:'PRIVATE_RAW'}]};
const saved=provenance(task,false),draft=provenance(task,true);
assert.match(saved,/immutable-account/);
assert.match(saved,/media-hash/);
assert.match(saved,/人工台词/);
assert.match(saved,/rule-hash/);
assert.match(draft,/未保存/);
assert.doesNotMatch(saved,/PRIVATE_BASE64|PRIVATE_RAW/);
assert.equal(provenance(null,false),'');
console.log('creative export provenance checks passed');
const {taskPresentation}=require('../static/creative.js');
task.attempts=[{attempt_uid:'archived-attempt',input_version:1,status:'validation_failed',raw_response:'PRIVATE_RAW',validation:{error:'original failure'}}];
task.result={report:{deliverables:{shooting:'original selected text'}},validation:{repairs:['remove_unselected_deliverables:writing_prompt'],recovery:{attempt_uid:'archived-attempt',network_requests:0}}};
const recovered=taskPresentation(task);
assert.equal(recovered.state,'已本地恢复');
assert.equal(recovered.qualityUnlocked,false);
const exportText=provenance(task,false);
assert.match(exportText,/validation_failed/);
assert.match(exportText,/remove_unselected_deliverables/);
assert.doesNotMatch(exportText,/PRIVATE_RAW|PRIVATE_BASE64/);
const {toSrt}=require('../static/creative.js');
assert.equal(toSrt({transcript_source:'local_asr',transcript_segments:[{start:0,end:1.25,text:'本地测试'}]}),'1\n00:00:00,000 --> 00:00:01,250\n本地测试\n');
assert.throws(()=>toSrt({transcript_source:'manual'}));
