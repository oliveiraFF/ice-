/* Explicit opt-in real-provider UI test. Each paid stage is durable and never retried. */
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),net=require('node:net');
const {spawn}=require('node:child_process'),{chromium}=require(process.env.PLAYWRIGHT_MODULE);
const out=path.resolve(process.env.ICE_ACCEPTANCE_DIR),data=path.join(out,'data');
let child,browser,origin;
const errors=[],calls=[],sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function api(route,body){let options={};if(body){const s=await(await fetch(origin+'/api/state?mode=live')).json();options={method:'POST',headers:{Origin:origin,'Content-Type':'application/json','X-Radar-Token':s.token},body:JSON.stringify(body)};}const response=await fetch(origin+route,options),value=await response.json();if(!response.ok||value.error)throw Error(value.error||route);return value;}
async function start(){
 const env={...process.env,ICE_AGENT_LOOP_TEST:'1',TIKHUB_API_KEY:'',LLM_ALLOW_PAID:'0',SHORT_VIDEO_OPS_WORKSPACE:''};
 if(process.env.ICE_EXE)child=spawn(process.env.ICE_EXE,['--data-dir',data],{windowsHide:true,stdio:'ignore',env});
 else{const probe=net.createServer();await new Promise(r=>probe.listen(0,'127.0.0.1',r));const port=probe.address().port;await new Promise(r=>probe.close(r));origin='http://127.0.0.1:'+port;child=spawn(process.env.UI_PYTHON,['app.py','--port',String(port),'--data-dir',data],{windowsHide:true,stdio:'ignore',env});}
 for(let i=0;i<200;i++){if(child.exitCode!==null)throw Error('app startup exited');try{if(process.env.ICE_EXE){const s=JSON.parse(await fs.readFile(path.join(data,'desktop-session.json'),'utf8'));if(s.pid===child.pid)origin='http://127.0.0.1:'+s.port;}if(origin&&(await fetch(origin+'/api/agent/loop')).ok)return;}catch{}await sleep(250);}throw Error('readiness timeout');
}
async function stop(){if(!child)return;const p=child,done=new Promise(r=>p.once('exit',r));if(process.env.ICE_EXE){await api('/api/desktop/exit',{confirm:true});assert.equal(await done,0);}else{p.kill();await done;}child=null;}
async function open(){browser=await chromium.launch({headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe'});const page=await browser.newPage({viewport:{width:1280,height:900},acceptDownloads:true});page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')calls.push(new URL(r.url()).pathname);});await page.goto(origin+'/ops-wallboard');await page.locator('#agentLoop').waitFor({state:'visible'});await page.waitForFunction(()=>!document.getElementById('loopNew').disabled);return page;}
async function step(page,action){const b=page.locator(`[data-loop-action="${action}"]`);assert(await b.isEnabled(),action+' should be enabled');await b.click();await page.waitForFunction(()=>!document.getElementById('loopNew').disabled,{},{timeout:150000});const run=JSON.parse(await page.locator('#loopEvidence').textContent());if(run.status.includes('failed'))throw Error(action+' returned '+run.status);return run;}
async function visual(page,prefix){for(const theme of ['light','dark']){await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);for(const width of [320,390,640,768,1024,1280,1600]){await page.setViewportSize({width,height:900});assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`overflow ${theme}/${width}`);if(width===390||width===1280)await page.screenshot({path:path.join(out,`${prefix}-${theme}-${width}.png`),fullPage:true});}}await page.setViewportSize({width:1280,height:900});}
(async()=>{try{
 await start();let page=await open();
 if(process.env.ICE_RUN_PAID==='1'){
  assert.equal((await api('/api/agent/loop')).runs.length,0,'Existing run found; refusing a paid rerun');
  const dir='C:/Users/25370/Desktop/密钥';
  const tk=(await fs.readFile(path.join(dir,'tihub密钥.txt'),'utf8')).replace(/^\uFEFF/,'').trim();
  assert(/^[A-Za-z0-9_./+=-]{24,500}$/.test(tk),'TikHub full-key format');
  const ds=(await fs.readFile(path.join(dir,'deepseek测试key.txt'),'utf8')).match(/sk-[A-Za-z0-9_-]{16,}/g);assert(ds?.length===1,'DeepSeek key format');
  await api('/api/connect',{key:tk});await api('/api/ai/config',{endpoint:'https://api.deepseek.com',model:'deepseek-flash',key:ds[0]});
  await page.locator('#loopNew').click();await page.waitForFunction(()=>document.getElementById('loopEvidence').textContent.includes('run_uid')&&!document.getElementById('loopNew').disabled);
  for(const action of ['diagnose','select','fetch','reference','creation','handoff','feedback'])await step(page,action);
  await page.locator('#loopSynthetic').click();await page.waitForFunction(()=>!document.getElementById('loopNew').disabled);
  const run=await step(page,'review');assert.equal(run.review.actual.status,'insufficient');assert.equal(run.review.simulation.simulated,true);
  await fs.writeFile(path.join(out,'paid-source-run.json'),JSON.stringify(run,null,2));
  await api('/api/ai/config',{endpoint:'https://api.deepseek.com',model:'deepseek-flash',clear_key:true});
 }
 const rows=(await api('/api/agent/loop')).runs;assert(rows.length>0);const run=rows[0];assert.equal(run.status,'test_loop_complete');
 await page.reload();await page.waitForFunction(()=>document.getElementById('loopStatus').textContent.includes('test_loop_complete')||document.getElementById('loopStatus').textContent.includes('技术流程已完成'));
 await visual(page,process.env.ICE_EXE?'exe':'source');
 const download=page.waitForEvent('download');await page.locator('#loopExport').click();const item=await download;await item.saveAs(path.join(out,(process.env.ICE_EXE?'exe':'source')+'-ui-export.json'));
 await page.locator('#loopVersions').locator('xpath=ancestor::details[1]/summary').click();
 await page.locator('#loopVersions').selectOption('1');await page.waitForFunction(()=>JSON.parse(document.getElementById('loopEvidence').textContent).version===1);assert(await page.locator('[data-loop-action="diagnose"]').isDisabled());
 await page.locator('#loopVersions').selectOption(String(run.version));await page.waitForFunction(()=>JSON.parse(document.getElementById('loopEvidence').textContent).status==='test_loop_complete');
 await page.locator('#loopResult a').click();await page.waitForURL('**/script?task=*');await page.waitForFunction(()=>document.getElementById('taskStatus')?.textContent.includes('已打开'));await page.screenshot({path:path.join(out,(process.env.ICE_EXE?'exe':'source')+'-native-task.png'),fullPage:true});
 const mdDownload=page.waitForEvent('download');await page.locator('#exportSaved').click();const md=await mdDownload,mdPath=path.join(out,(process.env.ICE_EXE?'exe':'source')+'-saved-script.md');await md.saveAs(mdPath);const markdown=await fs.readFile(mdPath,'utf8');assert(markdown.includes(run.creation.video_prompt));for(const b of run.creation.beats)assert(markdown.includes(b.shot));
 await browser.close();browser=null;await stop();await start();page=await open();const reopened=(await api('/api/agent/loop')).runs[0];assert.deepEqual(reopened,run);assert.equal((await api('/api/ai/config')).connected,false);await browser.close();browser=null;await stop();
 assert.deepEqual(errors,[]);await fs.writeFile(path.join(out,(process.env.ICE_EXE?'exe':'source')+'-ui-result.json'),JSON.stringify({passed:true,run_uid:run.run_uid,version:run.version,content_task:run.content_task,real_browser:true,restart:true,history:true,download:true,errors,calls},null,2));console.log(JSON.stringify({passed:true,run_uid:run.run_uid,version:run.version}));
}catch(error){console.error(error.message);process.exitCode=1;}finally{if(browser)await browser.close();await stop();}})();
