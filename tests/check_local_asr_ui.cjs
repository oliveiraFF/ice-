/* Real local ASR UI acceptance; no remote recognition or generation. */
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
  origin=await start();const original=await get(origin);let page=await open(origin);await page.locator('#localAsrPanel').waitFor({state:'visible'});
  assert(await page.locator('#extractLocalAsr').isDisabled());
  await page.locator('#localAsrSettings').evaluate(el=>{el.open=true;});
  for(const [id,value] of [['localAsrFfmpeg',process.env.ASR_FFMPEG],['localAsrWhisper',process.env.ASR_WHISPER],['localAsrModel',process.env.ASR_MODEL]])await page.locator('#'+id).fill(value);
  const configSaved=page.waitForResponse(r=>r.url().endsWith('/api/agent/asr-config')&&r.request().method()==='POST');await page.locator('#saveLocalAsrConfig').click();assert.equal((await configSaved).status(),200);
  await page.waitForFunction(()=>!document.querySelector('#extractLocalAsr').disabled);
  const transcribed=page.waitForResponse(r=>r.url().endsWith('/api/agent/transcribe-local'),{timeout:360000});
  await page.locator('#extractLocalAsr').click();assert(await page.locator('#extractLocalAsr').isDisabled());assert.equal(await page.locator('#localAsrPanel').getAttribute('aria-busy'),'true');
  const response=await transcribed;if(response.status()!==200)throw Error(JSON.stringify(await response.json()));const asr=await response.json();assert(asr.segments.length>0);
  await page.waitForFunction(()=>!document.querySelector('#downloadLocalSrt').disabled);
  assert.match(await page.locator('#localAsrStatus').innerText(),/未经人工校对/);
  const downloaded=page.waitForEvent('download');await page.locator('#downloadLocalSrt').click();const download=await downloaded;await download.saveAs(path.join(out,'actual-local-subtitles.srt'));
  const subtitle=await fs.readFile(path.join(out,'actual-local-subtitles.srt'),'utf8');assert.match(subtitle,/00:00:00,000 -->/);
  const saved=page.waitForResponse(r=>r.url().endsWith('/api/agent/task/save'));await page.locator('#saveCreativeTask').click();assert.equal((await saved).status(),200);
  const frozen=await get(origin);const asrVersion=frozen.version;assert.equal(frozen.input.transcript_source,'local_asr');assert.deepEqual(frozen.input.transcript_segments,asr.segments);assert.equal(frozen.result,null);
  for(const theme of ['dark','light']){
   if(await page.locator('html').getAttribute('data-theme')!==theme)await page.locator('#themeToggle').click();
   for(const width of [320,375,390,414,768,1280]){await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));}
   await page.locator('#localAsrTitle').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,theme+'-local-asr.png'),animations:'disabled'});
  }
  await context.close();context=null;await close(origin);origin=await start();page=await open(origin);
  assert.equal((await get(origin)).input.transcript_source,'local_asr');assert.equal(await page.locator('#localAsrModel').inputValue(),process.env.ASR_MODEL);assert(!await page.locator('#downloadLocalSrt').isDisabled());
  const again=page.waitForEvent('download');await page.locator('#downloadLocalSrt').click();await(await again).saveAs(path.join(out,'reopened-subtitles.srt'));assert.equal(await fs.readFile(path.join(out,'reopened-subtitles.srt'),'utf8'),subtitle);
  await page.locator('#openCreativeBrief').click();await page.locator('#creativeBriefDialog details summary').click();await page.locator('#creativeTranscript').fill(asr.text+' 【技术验收模拟编辑，未做内容校对】');
  const manualSaved=page.waitForResponse(r=>r.url().endsWith('/api/agent/task/save'));await page.locator('#saveCreativeInput').click();assert.equal((await manualSaved).status(),200);
  const manual=await get(origin);assert.equal(manual.input.transcript_source,'manual');assert(!manual.input.transcript_segments);assert(await page.locator('#downloadLocalSrt').isDisabled());assert.deepEqual((await get(origin,asrVersion)).input.transcript_segments,asr.segments);
  assert.deepEqual((await get(origin,original.version)).result,original.result);
  await context.close();context=null;await close(origin);
  assert.equal(errors.length,0);assert.equal(external.length,0);assert(!writes.some(p=>/generate|tools\/run|\/video\/transcribe$/.test(p)));
  const result={packaged:Boolean(exe),task_uid:taskId,local_recognitions:writes.filter(p=>p.endsWith('/transcribe-local')).length,provider_calls:0,segments:asr.segments.length,duration:asr.metadata.duration,asr_version:asrVersion,manual_version:manual.version,manual_reviewed:false,actual_srt_download:true,restart_restores_config_and_subtitles:true,manual_edit_drops_current_time_axis:true,historical_asr_retained:true,original_results_retained:true,themes:['dark','light'],widths:[320,375,390,414,768,1280],errors,external,writes};
  await fs.writeFile(path.join(out,'local-asr-results.json'),JSON.stringify(result,null,2));console.log('PASS actual offline ASR, timed SRT download, task save, app/browser restart, historical subtitles and manual edit separation; no provider calls');
 }finally{if(context)await context.close();if(child&&child.exitCode===null){try{await close(origin);}catch{child.kill();}}}
})().catch(e=>{console.error(e);process.exitCode=1;});
