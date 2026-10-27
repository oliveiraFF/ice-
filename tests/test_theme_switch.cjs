/* Real local-app theme acceptance; all databases and browser storage are isolated. */
const assert=require('node:assert/strict');
const fs=require('node:fs/promises');
const path=require('node:path');
const os=require('node:os');
const net=require('node:net');
const {spawn}=require('node:child_process');
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const repo=path.resolve(process.argv[2]||process.cwd());
const routes=(process.env.UI_THEME_ROUTES||'/dashboard,/advice,/,/draft,/research,/media-review,/script,/feedback,/strategy,/market,/tools,/creative,/ops-wallboard,/browser-import').split(',');
const out=process.env.UI_ACCEPTANCE_DIR;
const results={pages:[],errors:[],external:[],writes:[]};
let server,context;
async function start(data){
  const socket=net.createServer();await new Promise(resolve=>socket.listen(0,'127.0.0.1',resolve));const port=socket.address().port;await new Promise(resolve=>socket.close(resolve));
  server=spawn(process.env.UI_PYTHON,['app.py','--port',String(port),'--data-dir',data],{cwd:repo,windowsHide:true,stdio:'ignore',env:{...process.env,TIKHUB_API_KEY:'',LLM_ALLOW_PAID:'0'}});
  for(let i=0;i<100;i++){try{if((await fetch('http://127.0.0.1:'+port+'/api/state?mode=live')).ok)return 'http://127.0.0.1:'+port;}catch{}await new Promise(resolve=>setTimeout(resolve,100));}throw Error('Local app failed to start');
}
async function stop(){if(!server)return;const child=server;server=null;await new Promise(resolve=>{child.once('exit',resolve);child.kill();setTimeout(resolve,2000).unref();});}
async function launch(profile){return chromium.launchPersistentContext(profile,{headless:true,executablePath:process.env.CHROME_PATH||'C:/Program Files/Google/Chrome/Application/chrome.exe',viewport:{width:1280,height:900}});}
async function open(page,url){await page.goto(url);await page.waitForLoadState('networkidle');}
async function shot(page,name){if(out){await fs.mkdir(out,{recursive:true});await page.screenshot({path:path.join(out,name+'.png'),animations:'disabled'});}}
const rgb=value=>(value.match(/[\d.]+/g)||[]).slice(0,3).map(Number);
const brightness=value=>rgb(value).reduce((a,b)=>a+b,0)/3;
function contrast(a,b){const lum=color=>rgb(color).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((n,v,i)=>n+v*[.2126,.7152,.0722][i],0);const x=lum(a),y=lum(b);return(Math.max(x,y)+.05)/(Math.min(x,y)+.05);}
(async()=>{
 const temp=await fs.mkdtemp(path.join(os.tmpdir(),'ice-theme-'));
 try{
  let origin=await start(path.join(temp,'data'));
  context=await launch(path.join(temp,'browser'));let page=await context.newPage();
  page.on('pageerror',error=>results.errors.push(error.message));
  page.on('request',request=>{const url=new URL(request.url());if(/^https?:$/.test(url.protocol)&&!['127.0.0.1','localhost'].includes(url.hostname))results.external.push(url.hostname);if(request.method()!=='GET')results.writes.push(url.pathname);});
  await open(page,origin+'/dashboard');
  assert.equal(await page.locator('#themeToggle').count(),1,'one shared theme toggle is available');
  assert.equal(await page.locator('html').getAttribute('data-theme'),'light','first launch opens in light mode');
  for(const mode of ['light','dark']){
   const beforeSwitchWrites=results.writes.length;
   if(await page.locator('html').getAttribute('data-theme')!==mode)await page.locator('#themeToggle').click();
   await page.waitForLoadState('networkidle');
   assert.equal(results.writes.length,beforeSwitchWrites,'theme switch itself does not send API requests');
   assert.equal(await page.locator('#themeToggle').getAttribute('aria-checked'),String(mode==='dark'));
   for(const route of routes){
    await open(page,origin+route);
    assert.equal(await page.locator('html').getAttribute('data-theme'),mode,route+' keeps the selected mode');
    const palette=await page.evaluate(()=>{const style=e=>{const s=getComputedStyle(e);return{background:s.backgroundColor,color:s.color};};const surface=document.querySelector('.wb-panel,.script-card,.script-form,.creative-source,.api-card,.feature-tool,.wb-panel,.wallboard-card,.capture-row');return{body:style(document.body),nav:style(document.querySelector('.site-nav')),input:style(document.querySelector('#siteSearchInput')),header:style(document.querySelector('.site-header')),surface:surface?style(surface):null,width:innerWidth,scroll:document.documentElement.scrollWidth,navCount:document.querySelectorAll('#siteNav a:not(.site-brand)').length};});
    assert.equal(palette.navCount,11);
    assert(mode==='dark'?brightness(palette.body.background)<65:brightness(palette.body.background)>220,route+' page palette switches');
    assert(mode==='dark'?brightness(palette.nav.background)<65:brightness(palette.nav.background)>220,route+' rail palette switches');
    assert(contrast(palette.body.color,palette.body.background)>=4.5,route+' body text is readable');
    assert(palette.scroll<=palette.width,route+' fits desktop');
    if(mode==='dark'){
      const lightSurfaces=await page.evaluate(()=>[...document.querySelectorAll('main :is(article,section,aside,form,details,[class*=panel],[class*=card],[class*=stage])')].filter(el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el),n=(s.backgroundColor.match(/[\d.]+/g)||[]).map(Number);return r.width*r.height>2000&&n.length>=3&&(n.length<4||n[3]>.9)&&(n[0]+n[1]+n[2])/3>190;}).map(el=>({tag:el.tagName,id:el.id,class:el.className})).slice(0,10));
      assert.equal(lightSurfaces.length,0,route+' has unthemed light surfaces: '+JSON.stringify(lightSurfaces));
    }
    for(const selector of ['.ice-stage','.draft-empty-state','.draft-step-rail span:not(.active)']){
      if(await page.locator(selector).count()){
        const style=await page.locator(selector).first().evaluate(el=>({background:getComputedStyle(el).backgroundColor,color:getComputedStyle(el).color}));
        assert(mode==='dark'?brightness(style.background)<70:brightness(style.background)>200,route+' '+selector+' follows the theme');
        assert(contrast(style.color,style.background)>=4.5,route+' '+selector+' retains readable text');
      }
    }
    results.pages.push({mode,route,...palette});
    if(['/dashboard','/creative','/draft','/market','/ops-wallboard'].includes(route))await shot(page,mode+'-'+(route.slice(1)||'discovery')+'-1280');
   }
   for(const width of [320,375,390,414,768]){
    await page.setViewportSize({width,height:900});
    for(const route of routes){await open(page,origin+route);const overflow=await page.evaluate(()=>({bad:document.documentElement.scrollWidth>innerWidth||document.body.scrollWidth>innerWidth,nodes:[...document.querySelectorAll('main *,.site-header *')].filter(el=>{const r=el.getBoundingClientRect();return r.width>0&&r.right>innerWidth+1;}).slice(0,12).map(el=>({tag:el.tagName,id:el.id,class:el.className,right:el.getBoundingClientRect().right}))}));if(overflow.bad)await shot(page,'overflow-'+mode+'-'+route.slice(1)+'-'+width);assert(!overflow.bad,mode+route+' overflows at '+width+': '+JSON.stringify(overflow.nodes));assert(await page.locator('#themeToggle').isVisible());}
    if(width===390)await shot(page,mode+'-mobile-390');
   }
   await page.setViewportSize({width:1280,height:900});await open(page,origin+'/dashboard');
   await page.locator('#siteSettings').click();
   const dialogStyle=await page.locator('dialog[open]').evaluate(el=>({background:getComputedStyle(el).backgroundColor,color:getComputedStyle(el).color}));
   assert(contrast(dialogStyle.color,dialogStyle.background)>=4.5,'settings dialog text remains readable');
   await shot(page,mode+'-settings-1280');await page.keyboard.press('Escape');
  }
  await page.locator('#themeToggle').click();assert.equal(await page.locator('html').getAttribute('data-theme'),'light');
  await page.reload();assert.equal(await page.locator('html').getAttribute('data-theme'),'light','refresh remembers preference');
  await context.close();context=null;await stop();origin=await start(path.join(temp,'data'));
  context=await launch(path.join(temp,'browser'));page=await context.newPage();await open(page,origin+'/dashboard');
  assert.equal(await page.locator('html').getAttribute('data-theme'),'light','browser restart with changed desktop port restores preference');
  results.restart={newPort:true,restored:'light'};
  await page.locator('#themeToggle').focus();await page.keyboard.press('Enter');
  assert.equal(await page.locator('html').getAttribute('data-theme'),'dark','keyboard can operate the switch');
  const unavailable=await context.browser().newContext();
  await unavailable.addInitScript(()=>{Object.defineProperty(window,'localStorage',{get(){throw Error('storage unavailable');}});Object.defineProperty(document,'cookie',{get(){throw Error('cookies unavailable');},set(){throw Error('cookies unavailable');}});});
  const fallback=await unavailable.newPage();await open(fallback,origin+'/dashboard');await fallback.locator('#themeToggle').click();
  assert.equal(await fallback.locator('html').getAttribute('data-theme'),'dark','unavailable storage does not break the current page (light default, one click to dark)');await unavailable.close();
  assert.equal(results.errors.length,0,JSON.stringify(results.errors));assert.equal(results.external.length,0);
  assert(!results.writes.some(route=>/generate|transcrib|\/connect|\/collect/.test(route)),'no generation, credential changes or collection calls: '+JSON.stringify(results.writes));
  if(out)await fs.writeFile(path.join(out,'theme-results.json'),JSON.stringify(results,null,2));
  console.log('PASS '+routes.length+' pages, 2 themes, 6 widths, accessible toggle, refresh and browser/server restart on new port, no external or paid requests; theme switch sends no API requests');
 }finally{if(context)await context.close();await stop();await fs.rm(temp,{recursive:true,force:true});}
})().catch(error=>{console.error(error);process.exitCode=1;});
