/* Real local service and Chrome, no mocked catalog and no provider execution. */
const assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),net=require('node:net');
const {spawn,spawnSync}=require('node:child_process'),{chromium}=require(process.env.PLAYWRIGHT_MODULE);
const out=path.resolve(process.env.ICE_ACCEPTANCE_DIR),data=path.join(out,'app-data'),exe=process.env.ICE_EXE;
const SHARE='GET /api/v1/douyin/app/v3/fetch_one_video_by_share_url',YOUTUBE='GET /api/v1/youtube/web/search_video';
let child,browser,origin;const errors=[],external=[],writes=[],sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function start(){
  const env={...process.env,PYTHONUTF8:'1',TIKHUB_API_KEY:'',LLM_ALLOW_PAID:'0',SHORT_VIDEO_OPS_WORKSPACE:'',ICE_AGENT_LOOP_TEST:''};
  if(exe)child=spawn(exe,['--data-dir',data],{env,windowsHide:true,stdio:'ignore'});
  else{
    const probe=net.createServer();await new Promise(resolve=>probe.listen(0,'127.0.0.1',resolve));
    const port=probe.address().port;await new Promise(resolve=>probe.close(resolve));origin='http://127.0.0.1:'+port;
    child=spawn(process.env.UI_PYTHON,['app.py','--port',String(port),'--data-dir',data],{env,windowsHide:true,stdio:'ignore'});
  }
  for(let i=0;i<200;i++){
    assert.equal(child.exitCode,null,'application exited');
    try{
      if(exe){const state=JSON.parse(await fs.readFile(path.join(data,'desktop-session.json'),'utf8'));if(state.pid===child.pid)origin='http://127.0.0.1:'+state.port;}
      if(origin&&(await fetch(origin+'/api/catalog')).ok)return;
    }catch{}
    await sleep(250);
  }
  throw Error('application readiness timeout');
}
async function stop(){
  if(!child)return;const process=child,done=new Promise(resolve=>process.once('exit',resolve));
  if(exe){
    const state=await(await fetch(origin+'/api/state?mode=live')).json();
    const response=await fetch(origin+'/api/desktop/exit',{method:'POST',headers:{Origin:origin,'X-Radar-Token':state.token,'Content-Type':'application/json'},body:'{"confirm":true}'});
    assert.equal(response.status,200);await done;assert.equal(process.exitCode,0);
  }else{process.kill();await done;}
  child=null;
}
async function open(){
  browser=await chromium.launchPersistentContext(path.join(out,'chrome-profile'),{headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',viewport:{width:1280,height:900}});
  const page=await browser.newPage();
  page.on('pageerror',error=>errors.push(error.message));
  page.on('request',request=>{
    const url=new URL(request.url());
    if(/^https?:$/.test(url.protocol)&&url.hostname!=='127.0.0.1')external.push(url.hostname);
    if(request.method()==='POST'&&/^\/api\/(tools(?:\/run)?|connect|access|credit)$/.test(url.pathname))writes.push(url.pathname);
  });
  await page.goto(origin+'/');await page.waitForFunction(()=>document.getElementById('keywordSearchStatus').textContent.startsWith('已读取'));
  return page;
}
async function screenshots(page,name,dialog=false){
  for(const theme of ['light','dark']){
    await page.evaluate(value=>document.documentElement.dataset.theme=value,theme);
    for(const width of [390,1280]){
      await page.setViewportSize({width,height:900});
      if(dialog)await page.locator('#captureQueue').scrollIntoViewIfNeeded();
      else await page.locator('.source-tools').evaluate(node=>node.scrollIntoView({block:'start'}));
      assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1),name+' page overflow '+width);
      if(dialog)assert(await page.locator('#apiDialog').evaluate(node=>node.scrollWidth<=node.clientWidth+1));
      else assert(await page.locator('.capture-choice').first().evaluate(row=>{
        const box=row.querySelector('input').getBoundingClientRect(),content=row.querySelector('.capture-choice-content').getBoundingClientRect(),bounds=row.getBoundingClientRect();
        return box.width<=22&&content.left-box.right<=18&&content.right<=bounds.right+1;
      }),'interface checkbox must not stretch or clip content');
      if(!dialog)assert(await page.locator('#captureEndpointList').evaluate(node=>node.scrollWidth<=node.clientWidth+1),'interface list must not clip wide text');
      await page.screenshot({path:path.join(out,`${name}-${theme}-${width}.png`),animations:'disabled'});
    }
  }
  await page.setViewportSize({width:1280,height:900});
}
function ledgerCount(){
  const result=spawnSync(process.env.UI_PYTHON,['-c','import sqlite3,sys; db=sqlite3.connect(sys.argv[1]); print(db.execute("SELECT count(*) FROM api_requests").fetchone()[0])',path.join(data,'radar.sqlite3')],{encoding:'utf8',windowsHide:true});
  assert.equal(result.status,0,result.stderr);return Number(result.stdout.trim());
}
(async()=>{
  await fs.mkdir(out,{recursive:false});
  try{
    await start();let page=await open();
    assert.equal(await page.locator('#captureRegion').inputValue(),'domestic');
    assert.equal(await page.locator('#searchKeywordInput').getAttribute('required'),null);
    await page.locator('#captureRegion').focus();
    assert(await page.locator('#captureRegion').evaluate(node=>{const style=getComputedStyle(node);return style.outlineStyle!=='none'&&parseFloat(style.outlineWidth)>=2;}),'keyboard focus must be visible');
    await screenshots(page,'initial');
    await page.locator('#capturePlatform').selectOption('douyin');
    await page.locator('#captureQuery').fill('fetch_one_video_by_share_url');
    await page.locator(`[data-capture-id="${SHARE}"]`).check();
    await page.locator('#captureRegion').selectOption('overseas');
    await page.locator('#capturePlatform').selectOption('youtube');
    await page.locator('#captureQuery').fill('search_video');
    await page.locator(`[data-capture-id="${YOUTUBE}"]`).check();
    assert.equal(await page.locator('#captureSelectedList li').count(),2);
    await page.locator('#captureRegion').selectOption('other');
    assert(await page.locator('#capturePlatform option[value="tikhub"]').count());
    await page.locator('#captureRegion').selectOption('domestic');
    await page.locator('#capturePlatform').selectOption('bilibili');
    await page.locator('#captureQuery').fill('does-not-exist-acceptance');
    await page.locator('.capture-empty').getByText('没有匹配接口',{exact:false}).waitFor();
    await page.locator('#captureQuery').fill('');
    await page.reload();await page.waitForFunction(()=>document.getElementById('captureSelectedList').children.length===2);
    assert.equal(await page.locator('#capturePlatform').inputValue(),'bilibili');
    await browser.setOffline(true);await page.locator('#refreshKeywordEndpoints').click();
    await page.waitForFunction(()=>document.getElementById('keywordSearchStatus').textContent.startsWith('目录读取失败'));
    assert(await page.locator('#keywordSearchSubmit').isDisabled());
    await page.screenshot({path:path.join(out,'offline-error.png')});
    await browser.setOffline(false);await page.locator('#refreshKeywordEndpoints').click();
    await page.waitForFunction(()=>document.getElementById('keywordSearchStatus').textContent.startsWith('已读取'));
    assert.equal(await page.locator('#captureSelectedList li').count(),2);
    await screenshots(page,'selected');
    await page.locator('.capture-keyword-tools summary').click();await page.locator('#searchKeywordInput').fill('本地验收主题');
    await page.locator('#keywordSearchSubmit').click();await page.waitForURL('**/market?**');
    await page.locator('#apiDialog').waitFor({state:'visible'});
    assert((await page.locator('#detailPath').textContent()).endsWith('/api/v1/douyin/app/v3/fetch_one_video_by_share_url'));
    assert(await page.locator('#collectResult').isChecked());
    assert.match(await page.locator('#captureQueueStatus').textContent(),/1 \/ 2/);
    const link='https://v.douyin.com/LocalAcceptanceOnly/';
    await page.getByLabel('参数 share_url',{exact:true}).fill(link);
    await page.locator('#captureNext').click();
    await page.waitForFunction(()=>document.getElementById('detailPath').textContent.endsWith('/api/v1/youtube/web/search_video'));
    assert(await page.locator('#collectionOptions').isHidden());assert.equal(await page.locator('#collectResult').isChecked(),false);
    assert.match(await page.locator('#captureCapability').textContent(),/收录待接入/);
    assert(await page.locator('#runTool').isDisabled());
    await screenshots(page,'youtube-parameters',true);
    await page.locator('#capturePrevious').click();
    await page.waitForFunction(()=>document.getElementById('detailPath').textContent.endsWith('/api/v1/douyin/app/v3/fetch_one_video_by_share_url'));
    assert.equal(await page.getByLabel('参数 share_url',{exact:true}).inputValue(),link);
    assert.equal(new URL(page.url()).searchParams.get('id'),SHARE);
    await browser.close();browser=null;assert.equal(ledgerCount(),0);await stop();
    // The app uses a fresh port on restart. Preferences are local to that origin;
    // reload persistence was tested above, while a new origin starts unselected.
    await start();page=await open();assert.equal(await page.locator('#captureSelectedList li').count(),0);
    assert.deepEqual(writes,[]);assert.deepEqual(external,[]);assert.deepEqual(errors,[]);assert.equal(ledgerCount(),0);
    await browser.close();browser=null;await stop();
    const result={passed:true,source_or_exe:exe||'source',real_local_service:true,real_chrome:true,regions_and_platforms:true,cross_platform_multiselect:true,empty_filter:true,offline_recovery:true,manual_parameters_only:true,draft_preserved:true,reload_selection:true,new_origin_starts_unselected:true,application_restart:true,unsupported_collection_hidden:true,interface_executions:0,provider_calls:0,api_ledger_rows:0,errors,external,writes};
    await fs.writeFile(path.join(out,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
  }finally{if(browser)await browser.close();await stop();}
})().catch(error=>{console.error(error);process.exitCode=1;});
