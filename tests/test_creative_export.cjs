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
