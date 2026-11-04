/* Real local server/exe and real Chrome; synthetic history, no provider requests. */
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),net=require('node:net');
const {spawn,spawnSync}=require('node:child_process'),{chromium}=require(process.env.PLAYWRIGHT_MODULE);
const out=path.resolve(process.env.ICE_ACCEPTANCE_DIR),data=path.join(out,'app-data'),exe=process.env.ICE_EXE;
const failed='GET /api/v1/douyin/app/v1/fetch_hashtag_search_result',share='GET /api/v1/douyin/app/v3/fetch_one_video_by_share_url';
const errors=[],external=[],posts=[],resourceFailures=[],consoleErrors=[];let child,browser,origin;const sleep=ms=>new Promise(r=>setTimeout(r,ms));
function python(code){const r=spawnSync(process.env.UI_PYTHON,['-c',code,data],{encoding:'utf8',windowsHide:true});assert.equal(r.status,0,r.stderr);return r.stdout;}
function snapshot(){return JSON.parse(python(`import sqlite3,json,sys
with sqlite3.connect(sys.argv[1]+'/radar.sqlite3') as db:
 print(json.dumps([db.execute('SELECT * FROM tools WHERE id=?',('${failed}',)).fetchone(),db.execute('SELECT * FROM api_requests').fetchall()]))`));}
async function api(route,body){const options={};if(body){const {token}=await(await fetch(origin+'/api/state?mode=live')).json();Object.assign(options,{method:'POST',headers:{Origin:origin,'X-Radar-Token':token,'Content-Type':'application/json'},body:JSON.stringify(body)});}const r=await fetch(origin+route,options);return {status:r.status,value:await r.json()};}
async function start(){const env={...process.env,TIKHUB_API_KEY:'',SHORT_VIDEO_OPS_WORKSPACE:'',LLM_ALLOW_PAID:'0',ICE_AGENT_LOOP_TEST:''};
 if(exe)child=spawn(exe,['--data-dir',data],{env,windowsHide:true,stdio:'ignore'});
 else{const n=net.createServer();await new Promise(r=>n.listen(0,'127.0.0.1',r));const port=n.address().port;await new Promise(r=>n.close(r));origin='http://127.0.0.1:'+port;child=spawn(process.env.UI_PYTHON,['app.py','--port',String(port),'--data-dir',data],{env,windowsHide:true,stdio:'ignore'});}
 for(let i=0;i<200;i++){assert.equal(child.exitCode,null,'application exited');try{if(exe){const s=JSON.parse(await fs.readFile(path.join(data,'desktop-session.json'),'utf8'));if(s.pid===child.pid)origin='http://127.0.0.1:'+s.port;}if(origin&&(await fetch(origin+'/api/catalog')).ok)return;}catch{}await sleep(250);}throw Error('readiness timeout');}
async function stop(){if(!child)return;const p=child,done=new Promise(r=>p.once('exit',r));if(exe){assert.equal((await api('/api/desktop/exit',{confirm:true})).status,200);await done;assert.equal(p.exitCode,0);}else{p.kill();await done;}child=null;}
(async()=>{await fs.mkdir(out,{recursive:false});await fs.mkdir(data);try{
 python(`from app import Store
from catalog import Catalog
from pathlib import Path
import sqlite3,sys
db=Path(sys.argv[1])/'radar.sqlite3';Store(db);c=Catalog('catalog.json',db)
c.manage('${failed}','add');c.manage('${share}','add');c.configure_access(True,'1',allow_balance=True)
with sqlite3.connect(db) as conn:
 conn.execute('UPDATE tools SET enabled=1,last_at=123,last_ok=0,last_result=? WHERE id=?',('数据服务 HTTP 404：Not Found（合成复现记录）','${failed}'))
 conn.execute('UPDATE tools SET last_ok=1 WHERE id=?',('${share}',))
 conn.execute('INSERT INTO api_requests(tool_id,cost,at,outcome) VALUES(?,?,?,?)',('${failed}','0.001',123,'uncertain'))
 conn.commit()`);
 const before=snapshot();await start();
 const direct=await api('/api/tools/run',{id:failed,params:{keyword:'AI'},collect:true});assert.equal(direct.status,400);assert.match(direct.value.error,/404/);
 const enable=await api('/api/tools',{id:failed,action:'enable'});assert.equal(enable.status,400);assert.match(enable.value.error,/404/);assert.deepEqual(snapshot(),before);
 browser=await chromium.launchPersistentContext(path.join(out,'chrome-profile'),{headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',viewport:{width:1280,height:900},javaScriptEnabled:true});const page=await browser.newPage();
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(r.method()==='POST')posts.push(r.url());const u=new URL(r.url());if(/^https?:$/.test(u.protocol)&&u.hostname!=='127.0.0.1')external.push(u.hostname);});
 page.on('console',message=>{if(message.type()==='error')consoleErrors.push(message.text());});
 page.on('requestfailed',request=>resourceFailures.push({url:request.url(),error:request.failure()?.errorText}));
 page.on('response',response=>{if(response.status()>=400)resourceFailures.push({url:response.url(),status:response.status()});});
 await page.goto(origin+'/market');
 try{await page.locator('#apiGrid .api-card').first().waitFor();}
 catch(error){await fs.writeFile(path.join(out,'market-failure.json'),JSON.stringify({errors,consoleErrors,resourceFailures,scripts:await page.locator('script').evaluateAll(nodes=>nodes.map(node=>({src:node.src,type:node.type}))),url:page.url(),cards:await page.locator('#apiGrid .api-card').count(),status:await page.locator('#apiResultCount').textContent(),body:(await page.locator('body').innerText()).slice(0,1600)},null,2));await page.screenshot({path:path.join(out,'market-failure.png')});throw error;}
 await page.locator('#apiSearch').fill('/api/v1/douyin/app/v1/fetch_hashtag_search_result');
 const card=page.locator('#apiGrid .api-card');await card.filter({hasText:'不可用 · HTTP 404'}).waitFor();assert.equal(await card.count(),1);await card.locator('[data-detail]').click();await page.locator('#apiDialog').waitFor({state:'visible'});
 assert(await page.locator('#runTool').isDisabled());assert.match(await page.locator('#runEligibility').textContent(),/404/);assert.match(await page.locator('#toolResponse').textContent(),/合成复现记录/);
 const postCount=posts.length;await page.locator('#runTool').evaluate(b=>b.click());await page.waitForTimeout(200);assert.equal(posts.length,postCount);
 for(const theme of ['light','dark']){await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);for(const width of [390,1280]){await page.setViewportSize({width,height:900});await page.waitForTimeout(250);assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),'page overflow');assert(await page.locator('#apiDialog').evaluate(d=>d.scrollWidth<=d.clientWidth+1),'dialog overflow');if(theme==='dark')assert(await page.locator('.api-dialog-head').evaluate(d=>getComputedStyle(d).backgroundColor.match(/[\d.]+/g).slice(0,3).every(v=>Number(v)<150)),'dark header must use theme surface');if(width===390)assert.equal(await page.locator('.run-heading').evaluate(d=>getComputedStyle(d).flexDirection),'column');await page.locator('#runTool').scrollIntoViewIfNeeded();await page.screenshot({path:path.join(out,`blocked-${theme}-${width}.png`),animations:'disabled'});}}
 await page.locator('#closeDetail').click();await page.locator('#apiSearch').fill('/api/v1/douyin/app/v3/fetch_one_video_by_share_url');await page.locator('#apiGrid .api-card').filter({hasText:'已验证响应'}).waitFor();
 const detail=(await api('/api/catalog/detail?id='+encodeURIComponent(share))).value;assert.equal(detail.availability,'verified_response');assert.equal(detail.execution_reason,'');
 await page.locator('#apiGrid [data-detail]').click();await page.locator('#parameterFields [aria-label="参数 share_url"]').waitFor();
 const link=page.locator('#parameterFields [aria-label="参数 share_url"]');assert.equal(await link.inputValue(),'');assert.equal(await link.evaluate(n=>n.required&&!n.checkValidity()),true);
 assert.equal(await page.locator('#officialDocs').getAttribute('href'),'https://docs.tikhub.io/186826220e0');
 const video='POST /api/v1/douyin/search/fetch_video_search_v2',topic='POST /api/v1/douyin/search/fetch_challenge_search_v2';
 const beforeSwitch=posts.length;await page.locator(`[data-capture-target="${video}"]`).click();await page.waitForFunction(()=>document.getElementById('detailPath').textContent.includes('fetch_video_search_v2'));
 const keyword=page.locator('[aria-label="参数 keyword"]');assert.equal(await keyword.inputValue(),'');assert(await keyword.evaluate(n=>n.required&&!n.checkValidity()));
 assert(await page.locator('[aria-label="参数 cursor"]').isHidden());
 await keyword.fill('  ');assert.equal(await keyword.evaluate(n=>n.checkValidity()),false);await keyword.fill('AI工具');
 await page.locator('[aria-label="参数 sort_type"]').selectOption('2');await page.locator('[aria-label="参数 publish_time"]').selectOption('7');
 let payload=JSON.parse(await page.locator('#bodyInput').inputValue());assert.equal(payload.keyword,'AI工具');assert.equal(payload.cursor,0);assert.equal(payload.search_id,'');assert.equal(payload.backtrace,'');assert.equal(payload.sort_type,'2');assert.equal(payload.publish_time,'7');
 await page.locator('.parameter-advanced summary').click();await page.locator('[aria-label="参数 filter_duration"]').selectOption('1-5');payload=JSON.parse(await page.locator('#bodyInput').inputValue());assert.equal(payload.filter_duration,'1-5');
 await page.locator('.parameter-advanced summary').click();for(const theme of ['light','dark']){await page.evaluate(t=>document.documentElement.dataset.theme=t,theme);for(const width of [390,1280]){await page.setViewportSize({width,height:900});await page.locator('#parameterFields').evaluate(f=>{const d=document.getElementById('apiDialog'),h=d.querySelector('.api-dialog-head');d.scrollTop+=f.getBoundingClientRect().top-d.getBoundingClientRect().top-h.getBoundingClientRect().height-24;});assert(await page.locator('#apiDialog').evaluate(d=>d.scrollWidth<=d.clientWidth+1));await page.screenshot({path:path.join(out,`documented-form-${theme}-${width}.png`),animations:'disabled'});}}
 await page.locator(`[data-capture-target="${topic}"]`).click();await page.waitForFunction(()=>document.getElementById('detailPath').textContent.includes('fetch_challenge_search_v2'));
 assert(await page.locator('#collectionOptions').isHidden());assert.equal(await page.locator('#collectResult').isChecked(),false);assert.match(await page.locator('#capturePurpose').textContent(),/不返回视频/);
 assert.equal((await api('/api/tools/run',{id:topic,params:{},body:{keyword:'AI'},collect:true})).status,400);assert.deepEqual(snapshot(),before);assert.equal(posts.length,beforeSwitch,'switching documented forms must not run a paid request');
 await browser.close();browser=null;await stop();await start();const reopened=(await api('/api/catalog/detail?id='+encodeURIComponent(failed))).value;assert.equal(reopened.availability,'unavailable');assert.match(reopened.last_result,/合成复现记录/);assert.deepEqual(snapshot(),before);
 assert.deepEqual(errors,[]);assert.deepEqual(external,[]);await stop();await fs.writeFile(path.join(out,'result.json'),JSON.stringify({passed:true,source_or_exe:exe||'source',blocked_direct_request:true,blocked_reenable:true,disabled_button_no_post:true,ledger_and_history_unchanged:true,restart:true,share_entry_retained:true,documented_forms:true,typed_defaults:true,required_inputs:true,topics_not_collected:true,synthetic_history:true,errors,external,paid_calls:0},null,2));console.log(JSON.stringify({passed:true,source_or_exe:exe||'source'}));
 }finally{if(browser)await browser.close();await stop();}})().catch(e=>{console.error(e);process.exitCode=1;});
