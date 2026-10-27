/* Actual packaged server + Chrome acceptance. This is not native-window capture. */
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const {spawn}=require('node:child_process');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const out=path.resolve(process.env.ICE_ACCEPTANCE_DIR);
const exe=path.resolve(process.env.ICE_EXE);
let child,context;
const errors=[],external=[];
const sleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function start(){
  child=spawn(exe,['--data-dir',path.join(out,'app-data')],{windowsHide:true,stdio:'ignore',env:{...process.env,TIKHUB_API_KEY:'',LLM_ALLOW_PAID:'0'}});
  for(let i=0;i<160;i++){
    if(child.exitCode!==null)throw Error('Packaged EXE exited before readiness');
    try{const session=JSON.parse(await fs.readFile(path.join(out,'app-data','desktop-session.json'),'utf8'));
      if(session.pid===child.pid){const origin='http://127.0.0.1:'+session.port;if((await fetch(origin+'/api/state?mode=live')).ok)return origin;}
    }catch{}
    await sleep(250);
  }
  throw Error('Packaged EXE did not become ready');
}
async function close(origin){
  const {token}=await(await fetch(origin+'/api/state?mode=live')).json();
  const done=new Promise(resolve=>child.once('exit',resolve));
  const response=await fetch(origin+'/api/desktop/exit',{method:'POST',headers:{Origin:origin,'X-Radar-Token':token,'Content-Type':'application/json'},body:JSON.stringify({confirm:true})});
  assert.equal(response.status,200);assert.equal(await done,0);
  await assert.rejects(fs.access(path.join(out,'app-data','desktop-session.json')));child=null;
}
async function browser(){
  context=await chromium.launchPersistentContext(path.join(out,'browser-profile'),{headless:true,executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',viewport:{width:1280,height:900}});
  const page=await context.newPage();
  page.on('pageerror',e=>errors.push(e.message));
  page.on('request',r=>{const u=new URL(r.url());if(/^https?:$/.test(u.protocol)&&u.hostname!=='127.0.0.1')external.push(u.hostname);});
  return page;
}
(async()=>{
 await fs.mkdir(out,{recursive:false});
 let origin;
 try{
  origin=await start();let page=await browser();
  await page.goto(origin+'/dashboard');await page.waitForLoadState('networkidle');
  assert.equal(await page.locator('html').getAttribute('data-theme'),'dark');
  for(const theme of ['dark','light']){
    if(await page.locator('html').getAttribute('data-theme')!==theme)await page.locator('#themeToggle').click();
    for(const route of ['/dashboard','/creative']){
      await page.goto(origin+route);await page.waitForLoadState('networkidle');
      assert.equal(await page.locator('html').getAttribute('data-theme'),theme);
      assert.equal(await page.locator('#siteNav a:not(.site-brand)').count(),11);
      for(const width of [320,375,390,414,768,1280]){
        await page.setViewportSize({width,height:900});
        assert(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
      }
      await page.screenshot({path:path.join(out,theme+route.replace('/','-')+'.png'),animations:'disabled'});
    }
  }
  await context.close();context=null;await close(origin);
  origin=await start();page=await browser();
  await page.goto(origin+'/dashboard');await page.waitForLoadState('networkidle');
  assert.equal(await page.locator('html').getAttribute('data-theme'),'light');
  const result={exe,normal_exits:2,pages:['/dashboard','/creative'],themes:['dark','light'],widths:[320,375,390,414,768,1280],navigation:11,persistent_after_exe_restart:true,errors,external,native_visual_capture:'not tested; actual EXE server rendered through independent Chrome'};
  assert.equal(errors.length,0);assert.equal(external.length,0);
  await context.close();context=null;await close(origin);
  await fs.writeFile(path.join(out,'packaged-theme-results.json'),JSON.stringify(result,null,2));
  console.log('PASS actual EXE start/exit/restart, theme persistence, real Chrome UI, two pages/two themes/six widths/11 navigation');
 }finally{if(context)await context.close();if(child&&child.exitCode===null){try{await close(origin);}catch{child.kill();}}}
})().catch(error=>{console.error(error);process.exitCode=1;});
