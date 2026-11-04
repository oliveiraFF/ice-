/* Real local service/EXE and Chrome. Optional read-only replay of a retained response;
 * synthetic image notes are separate from the real video-note evidence. No provider calls. */
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),net=require('node:net');
const {spawn,spawnSync}=require('node:child_process'),{chromium}=require(process.env.PLAYWRIGHT_MODULE);
const out=path.resolve(process.env.ICE_ACCEPTANCE_DIR),data=path.join(out,'app-data'),exe=process.env.ICE_EXE;
const errors=[],providerRequests=[],writes=[];let child,browser,origin;
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function python(code,args=[]){const result=spawnSync(process.env.UI_PYTHON,['-c',code,...args],{encoding:'utf8',windowsHide:true});assert.equal(result.status,0,result.stderr);return result.stdout;}
async function start(){
  const env={...process.env,PYTHONUTF8:'1',TIKHUB_API_KEY:'',LLM_ALLOW_PAID:'0',SHORT_VIDEO_OPS_WORKSPACE:'',ICE_AGENT_LOOP_TEST:''};
  if(exe)child=spawn(exe,['--data-dir',data],{env,windowsHide:true,stdio:'ignore'});
  else{const probe=net.createServer();await new Promise(resolve=>probe.listen(0,'127.0.0.1',resolve));const port=probe.address().port;await new Promise(resolve=>probe.close(resolve));origin='http://127.0.0.1:'+port;child=spawn(process.env.UI_PYTHON,['app.py','--port',String(port),'--data-dir',data],{env,windowsHide:true,stdio:'ignore'});}
  for(let i=0;i<200;i++){assert.equal(child.exitCode,null,'application exited');try{if(exe){const state=JSON.parse(await fs.readFile(path.join(data,'desktop-session.json'),'utf8'));if(state.pid===child.pid)origin='http://127.0.0.1:'+state.port;}if(origin&&(await fetch(origin+'/api/catalog')).ok)return;}catch{}await sleep(250);}
  throw Error('application readiness timeout');
}
async function stop(){
  if(!child)return;const proc=child,done=new Promise(resolve=>proc.once('exit',resolve));
  if(exe){const state=await(await fetch(origin+'/api/state?mode=live')).json();const response=await fetch(origin+'/api/desktop/exit',{method:'POST',headers:{Origin:origin,'X-Radar-Token':state.token,'Content-Type':'application/json'},body:'{"confirm":true}'});assert.equal(response.status,200);await done;assert.equal(proc.exitCode,0);}else{proc.kill();await done;}child=null;
}
async function open(){
  browser=await chromium.launchPersistentContext(path.join(out,'chrome-profile'),{headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',viewport:{width:1280,height:900},javaScriptEnabled:true});
  const page=await browser.newPage();page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{const url=new URL(request.url());if(/(?:api\.tikhub\.io|api\.deepseek\.com)$/.test(url.hostname))providerRequests.push(url.hostname);if(request.method()==='POST')writes.push(url.pathname);});
  await page.goto(origin+'/');await page.locator('#grid .content-card').first().waitFor();return page;
}
async function shots(page,name){
  for(const theme of ['light','dark'])for(const width of [1280,390]){
    await page.evaluate(value=>document.documentElement.dataset.theme=value,theme);await page.setViewportSize({width,height:900});
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),'page overflow');
    assert(await page.locator('#detailDialog').evaluate(node=>node.scrollWidth<=node.clientWidth+1),'drawer overflow');
    await page.screenshot({path:path.join(out,`${name}-${theme}-${width}.png`)});
  }
  await page.setViewportSize({width:1280,height:900});
}
(async()=>{
  await fs.mkdir(out,{recursive:false});await fs.mkdir(data);
  const prepared=JSON.parse(python(`import sys,json,sqlite3,hashlib
from pathlib import Path
sys.path.insert(0,str(Path.cwd()/'tests'))
from test_xhs_note_collection import note_payload
from app import Store,extract_posts
store=Store(Path(sys.argv[1])/'radar.sqlite3')
keyword=store.add_keyword('图文漏收录补验（隔离技术测试）')
synthetic=extract_posts(note_payload(),'xhs');assert len(synthetic)==1
synthetic[0]['source']='合成图文技术验收，不代表真实经营资料'
store.put_posts(keyword,synthetic,'live')
real_id=None
if len(sys.argv)>2 and sys.argv[2]:
 with sqlite3.connect(Path(sys.argv[2]).resolve().as_uri()+'?mode=ro',uri=True) as db:
  db.execute('PRAGMA query_only=ON')
  ok,raw=db.execute('SELECT last_ok,last_result FROM tools WHERE id=?',('GET /api/v1/xiaohongshu/app_v2/get_image_note_detail',)).fetchone()
 assert ok==1
 real=extract_posts(json.loads(raw),'xhs');assert len(real)==1
 assert real[0]['content_type']=='video' and real[0]['description'] and real[0]['cover']
 real[0]['source']='既有真实供应商响应离线重放，不新增调用'
 store.put_posts(keyword,real,'live')
 real_id=next(p['id'] for p in store.state('live')['posts'] if p['external_id']==real[0]['external_id'])
print(json.dumps({'real_post_id':real_id,'count':len(store.state('live')['posts'])}))`,[data,process.env.ICE_XHS_RESPONSE_DB||'']));
  try{
    await start();let page=await open();let state=await(await fetch(origin+'/api/state?mode=live')).json();assert.equal(state.posts.length,prepared.count);
    const synthetic=state.posts.find(post=>post.external_id==='0123456789abcdef01234567');assert(synthetic);
    const card=page.locator('#post-'+synthetic.id);assert.match(await card.locator('.cover-labels').innerText(),/图文/);
    await card.locator('.card-title').click();await page.locator('#detailDialog').waitFor({state:'visible'});
    assert.equal(await page.locator('.note-text').textContent(),synthetic.description);assert.equal(await page.locator('.note-text script').count(),0);
    assert.equal(await page.locator('.note-images img').count(),2);assert.match(await page.locator('#detailContent .connection-info').innerText(),/图文没有视频音轨/);
    await shots(page,'synthetic-image');await page.locator('#detailContent [data-close]').click();
    let realCoverLoaded=null;
    if(prepared.real_post_id){
      const real=state.posts.find(post=>post.id===prepared.real_post_id);assert.equal(real.content_type,'video');assert.equal(real.video_url,null);
      await page.locator('#post-'+real.id+' .card-title').click();await page.locator('#detailDialog').waitFor({state:'visible'});
      assert.equal(await page.locator('.note-text').textContent(),real.description);assert.match(await page.locator('.detail-meta').innerText(),/视频/);
      assert.match(await page.locator('#detailContent .connection-info').innerText(),/尚无视频直链/);
      await page.locator('.drawer-cover img').evaluate(img=>img.complete?undefined:new Promise(resolve=>{img.addEventListener('load',resolve,{once:true});img.addEventListener('error',resolve,{once:true});setTimeout(resolve,10000);}));
      realCoverLoaded=await page.locator('.drawer-cover img').evaluate(img=>img.complete&&img.naturalWidth>0);
      await shots(page,'retained-real-video-note');
    }
    await browser.close();browser=null;await stop();await start();page=await open();
    state=await(await fetch(origin+'/api/state?mode=live')).json();assert.equal(state.posts.length,prepared.count);
    const reopened=state.posts.find(post=>post.id===synthetic.id);assert.equal(reopened.description,synthetic.description);assert.deepEqual(reopened.images,synthetic.images);
    await page.locator('#post-'+synthetic.id+' .card-title').click();await page.locator('.note-images img').first().waitFor();assert.equal(await page.locator('.note-images img').count(),2);
    if(prepared.real_post_id){await page.locator('#detailContent [data-close]').click();await page.locator('#post-'+prepared.real_post_id+' .card-title').click();assert.match(await page.locator('#detailContent .connection-info').innerText(),/尚无视频直链/);}
    await browser.close();browser=null;await stop();
    const ledger=Number(python('import sqlite3,sys; print(sqlite3.connect(sys.argv[1]).execute("SELECT COUNT(*) FROM api_requests").fetchone()[0])',[path.join(data,'radar.sqlite3')]).trim());
    assert.equal(ledger,0);assert.deepEqual(errors,[]);assert.deepEqual(providerRequests,[]);
    // Existing direction classification reads its local cache with POST; it does not generate.
    assert.deepEqual(writes.filter(route=>route!=='/api/ai/cache'),[]);
    const result={passed:true,source_or_exe:exe||'source',real_service:true,real_chrome:true,synthetic_image_note:true,retained_real_response_replayed:Boolean(prepared.real_post_id),real_response_type:'video',real_cover_loaded:realCoverLoaded,body_escaped_and_newlines_preserved:true,image_gallery:true,light_dark_390_1280:true,restart_preserves_notes:true,provider_calls:0,api_ledger_rows:ledger,errors};
    await fs.writeFile(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
  }finally{if(browser)await browser.close();await stop();}
})().catch(error=>{console.error(error);process.exitCode=1;});
