const assert=require('node:assert/strict');
const {sameMedia}=require('../static/creative.js');
const task={media:{media_id:'original-video'}};
assert.equal(sameMedia(task,{media_id:'replacement-with-identical-frames'}),false);
assert.equal(sameMedia(task,null),false);
assert.equal(sameMedia(task,{media_id:'original-video'}),true);
console.log('media replacement identity checks passed');
