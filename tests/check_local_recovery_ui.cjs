/* Real archived-response UI acceptance; never submits another generation. */
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const net=require('node:net');
const {spawn}=require('node:child_process');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const out=path.resolve(process.env.ICE_ACCEPTANCE_DIR),data=path.resolve(process.env.ICE_DATA_DIR);
const taskId=process.env.ICE_TASK_ID,exe=process.env.ICE_EXE;
const writes=[],external=[],errors=[];
let child,context;
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function start(){
 let origin;
 if(exe){child=spawn(exe,['--data-dir',data],{windowsHide:true,stdio:'ignore',env:{...process.env,TIKHUB_API_KEY:'',LLM_ALLOW_PAID:'0'}});}
 else{
  const probe=net.createServer();await new Promise(resolve=>probe.listen(0,'127.0.0.1',resolve));const port=probe.address().port;await new Promise(resolve=>probe.close(resolve));
  origin='http://127.0.0.1:'+port;
  child=spawn(process.env.UI_PYTHON,['app.py','--port',String(port),'--data-dir',data],{windowsHide:true,stdio:'ignore',env:{...process.env,TIKHUB_API_KEY:'',LLM_ALLOW_PAID:'0'}});
 }
 for(let i=0;i<160;i++){
  if(child.exitCode!==null)throw Error('App exited before readiness');
  try{
   if(exe){const s=JSON.parse(await fs.readFile(path.join(data,'desktop-session.json'),'utf8'));if(s.pid===child.pid)origin='http://127.0.0.1:'+s.port;}
   if(origin&&(await fetch(origin+'/api/agent/tasks')).ok)return origin;
  }catch{}
  await sleep(250);
 }
 throw Error('App readiness timeout');
}
async function close(origin){
 const process=child,done=new Promise(resolve=>process.once('exit',resolve));
 if(exe){const {token}=await(await fetch(origin+'/api/state?mode=live')).json();await fetch(origin+'/api/desktop/exit',{method:'POST',headers:{Origin:origin,'X-Radar-Token':token,'Content-Type':'application/json'},body:JSON.stringify({confirm:true})});assert.equal(await done,0);}
 else{process.kill();await done;}
 child=null;
}
async function open(origin,version){
 context=await chromium.launchPersistentContext(path.join(out,'browser-profile'),{headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',viewport:{width:1280,height:900}});
 const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
 page.on('request',r=>{const u=new URL(r.url());if(/^https?:$/.test(u.protocol)&&u.hostname!=='127.0.0.1')external.push(u.hostname);if(r.method()!=='GET')writes.push(u.pathname);});
 await page.goto(origin+'/creative?task='+taskId+(version?'&version='+version:''));await page.waitForLoadState('networkidle');return page;
}
const get=(origin,version)=>fetch(origin+'/api/agent/task?id='+taskId+(version?'&version='+version:'')).then(r=>r.json());
(async()=>{
 await fs.mkdir(out,{recursive:false});let origin;
 try{
  origin=await start();const before=await get(origin);assert.equal(before.version,1);assert.equal(before.result,null);
  let page=await open(origin);await page.locator('#recoverCreativeTask').waitFor({state:'visible'});
  const response=page.waitForResponse(r=>r.url().endsWith('/api/agent/task/recover'));
  await page.locator('#recoverCreativeTask').click();assert.equal((await response).status(),200);
  await page.locator('#exportCreative').waitFor({state:'visible'});await page.waitForFunction(()=>!document.querySelector('#saveCreativeTask').disabled);
  const recovered=await get(origin);assert.equal(recovered.version,2);assert.equal(recovered.attempts.length,1);assert.equal(recovered.attempts[0].status,'validation_failed');
  assert.equal(recovered.result.validation.recovery.network_requests,0);assert.deepEqual(Object.keys(recovered.result.report.deliverables),['shooting','video_prompt']);
  assert.equal(await page.locator('#creativeText-shooting').inputValue(),recovered.result.report.deliverables.shooting);
  assert.match(await page.locator('#iceTaskState').innerText(),/已本地恢复/);
  for(const theme of ['dark','light']){
   if(await page.locator('html').getAttribute('data-theme')!==theme)await page.locator('#themeToggle').click();
   await page.locator('.creative-analysis-details').evaluateAll(items=>items.forEach(item=>{item.open=true;}));
   for(const selector of ['.ice-quality','.creative-evaluation']){
    const palette=await page.locator(selector).first().evaluate(el=>({background:getComputedStyle(el).backgroundColor,color:getComputedStyle(el).color}));
    const rgb=value=>(value.match(/[\d.]+/g)||[]).slice(0,3).map(Number),brightness=rgb(palette.background).reduce((a,b)=>a+b,0)/3;
    assert(theme==='dark'?brightness<70:brightness>200,selector+' follows '+theme+' palette');
    const lum=color=>rgb(color).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((n,v,i)=>n+v*[.2126,.7152,.0722][i],0);
    const a=lum(palette.background),b=lum(palette.color);assert((Math.max(a,b)+.05)/(Math.min(a,b)+.05)>=4.5,selector+' text contrast');
   }
   for(const width of [390,1280]){await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
   await page.locator('#creativeResults').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,theme+'-recovered.png'),animations:'disabled'});
  }
  const note='\n\n〔本地验收备注：尚未人工评分〕',edited=recovered.result.report.deliverables.shooting+note;
  await page.locator('#creativeText-shooting').fill(edited);
  const saved=page.waitForResponse(r=>r.url().endsWith('/api/agent/task/save'));await page.locator('#saveCreativeTask').click();assert.equal((await saved).status(),200);
  await page.waitForFunction(()=>document.querySelector('#creativeTaskStatus').textContent.includes('v3'));
  const downloadPromise=page.waitForEvent('download');await page.locator('#exportCreative').click();const download=await downloadPromise;const exportPath=path.join(out,'actual-ui-export.md');await download.saveAs(exportPath);
  const text=await fs.readFile(exportPath,'utf8');assert(text.includes(edited));assert(text.includes('validation_failed'));assert(text.includes('remove_unselected_deliverables:writing_prompt'));assert(!text.includes('data:image/jpeg;base64'));assert(!text.includes('## 视频写稿提示词'));
  await context.close();context=null;await close(origin);
  origin=await start();page=await open(origin);assert.equal(await page.locator('html').getAttribute('data-theme'),'light');
  const reopened=await get(origin);assert.equal(reopened.version,3);assert.equal(reopened.result.report.deliverables.shooting,edited);
  assert.deepEqual((await get(origin,2)).result,recovered.result);assert.equal((await get(origin,1)).result,null);
  assert.equal(reopened.attempts.length,1);assert.equal(reopened.attempts[0].status,'validation_failed');
  await page.locator('#creativeTaskVersion').selectOption('1');await page.waitForFunction(()=>document.querySelector('#creativeTaskStatus').textContent.includes('历史版本只读'));
  assert(await page.locator('#creativeResults').isHidden());assert(await page.locator('#creativeRecovery').isHidden());
  await context.close();context=null;await close(origin);
  assert.equal(errors.length,0);assert.equal(external.length,0);assert(!writes.some(p=>/generate|transcribe|tools\/run/.test(p)));
  const result={packaged:Boolean(exe),task_uid:taskId,recovery_requests:writes.filter(p=>p.endsWith('/recover')).length,model_calls:0,attempt_count:1,original_failed_attempt_retained:true,versions:[1,2,3],actual_ui_export:true,exit_restart:true,theme_persistence:true,widths:[390,1280],errors,external,writes};
  await fs.writeFile(path.join(out,'recovery-results.json'),JSON.stringify(result,null,2));console.log('PASS real archived response -> UI local recovery -> edit/save -> actual download -> app exit/restart -> immutable versions; zero new model calls');
 }finally{if(context)await context.close();if(child&&child.exitCode===null){try{await close(origin);}catch{child.kill();}}}
})().catch(e=>{console.error(e);process.exitCode=1;});
