/* Opt-in real-browser acceptance. Isolated fixture directory must already exist. */
const {chromium}=require(process.env.PLAYWRIGHT_MODULE);
const fs=require('node:fs/promises'),path=require('node:path'),assert=require('node:assert/strict');
const {spawn,execFileSync}=require('node:child_process');
const root=path.resolve(process.argv[2]),python=process.env.UI_PYTHON;
const fixture=require(path.join(root,'fixture.json')),origin='http://127.0.0.1:8772';
let server,browser;const results={navigation:[],viewports:[],states:[],errors:[],requests:[]};
const pause=ms=>new Promise(r=>setTimeout(r,ms));
function sql(statement){execFileSync(python,['-c','import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute(sys.argv[2]); c.commit();c.close()',path.join(root,'data/radar.sqlite3'),statement]);}
async function start(){server=spawn(python,['app.py','--port','8772','--data-dir',path.join(root,'data')],{cwd:process.cwd(),windowsHide:true,stdio:'ignore'});for(let i=0;i<80;i++){try{if((await fetch(origin+'/api/agent/tasks')).ok)return;}catch{}await pause(100);}throw Error('local service failed to start');}
async function stop(){if(server){server.kill();await new Promise(r=>server.once('exit',r));server=null;}}
async function open(page,url){await page.goto(origin+url);await page.waitForLoadState('networkidle');}
async function shot(page,name){await page.screenshot({path:path.join(root,name+'.png'),fullPage:false,animations:'disabled'});}
async function task(page,id){await open(page,'/creative?task='+id);await page.locator('#creativeTaskStatus').filter({hasText:'任务 '+id}).waitFor();}
(async()=>{try{
 await start();sql("UPDATE agent_task_attempt SET status='processing' WHERE task_uid='"+fixture.ids.processing+"'");
 browser=await chromium.launch({executablePath:'C:/Program Files/Google/Chrome/Application/chrome.exe',headless:true});
 const context=await browser.newContext({viewport:{width:1280,height:900},deviceScaleFactor:1,acceptDownloads:true});
 const page=await context.newPage();page.on('pageerror',e=>results.errors.push(e.message));page.on('request',r=>{const u=new URL(r.url());if(u.protocol==='http:'||u.protocol==='https:')results.requests.push({path:u.pathname,method:r.method(),host:u.host});});
 for(const width of [1280,390,320,375,414,768]){
  await page.setViewportSize({width,height:900});
  for(const route of ['/dashboard','/creative?task=7a4b5d86524e','/market']){
   await open(page,route);const measurement=await page.evaluate(()=>({width:innerWidth,height:innerHeight,scroll:document.documentElement.scrollWidth}));assert(measurement.scroll<=width,route+' overflow');results.viewports.push({route,...measurement});
   if([1280,390].includes(width)){
    await shot(page,route.split('?')[0].slice(1)+'-'+width);
    if(route.startsWith('/creative')){await page.evaluate(()=>window.scrollTo(0,document.querySelector('.ice-task-layout').getBoundingClientRect().top+scrollY-90));await shot(page,'task-columns-'+width);await page.getByRole('button',{name:'2 台词',exact:true}).click();await shot(page,'transcript-'+width);await page.getByRole('button',{name:'4 分镜',exact:true}).click();await shot(page,'shooting-'+width);}
   }
  }
 }
 await page.setViewportSize({width:1280,height:900});await open(page,'/dashboard');
 const links=await page.locator('#siteNav a:not(.site-brand)').evaluateAll(xs=>xs.map(x=>({name:x.textContent.trim(),href:x.getAttribute('href')})));assert.equal(links.length,11);
 for(const item of links){await page.getByRole('navigation',{name:'主导航'}).getByRole('link',{name:item.name,exact:true}).click();await page.waitForLoadState('networkidle');assert.equal(new URL(page.url()).pathname,item.href);results.navigation.push(item);}
 for(const [status,id] of Object.entries(fixture.ids)){await task(page,id);results.states.push({status,label:await page.locator('#iceTaskState').innerText()});assert.equal(await page.getByRole('button',{name:'下一步',exact:true}).isEnabled(),false);await page.locator('.ice-task-layout').scrollIntoViewIfNeeded();await shot(page,'state-'+status);}
 await open(page,'/creative');results.states.push({status:'empty',label:await page.locator('#iceTaskState').innerText()});await shot(page,'empty');
 await task(page,'7a4b5d86524e');results.states.push({status:'success',label:await page.locator('#iceTaskState').innerText()});
 const area=page.getByRole('textbox',{name:'真人拍摄改编稿',exact:true});await area.fill((await area.inputValue())+'\n\n真实浏览器验收：保存后重开。');await page.getByRole('button',{name:'另存为新版本',exact:true}).click();await page.locator('#creativeTaskStatus').filter({hasText:'v3'}).waitFor();
 const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'导出全部 Markdown',exact:true}).click();await(await downloadPromise).saveAs(path.join(root,'browser-export-v3.md'));
 await stop();await start();await task(page,'7a4b5d86524e');assert((await area.inputValue()).includes('真实浏览器验收'));assert.equal(await page.locator('#creativeTaskVersion option').count(),3);results.reopen={version:3,versions:3,editRetained:true};
 await page.getByRole('combobox',{name:'选择任务版本'}).selectOption('2');await page.getByRole('button',{name:'打开任务',exact:true}).click();await page.getByText('正在查看已保存的历史版本。',{exact:true}).waitFor();assert.equal(await area.getAttribute('readonly'),'');assert.equal(await page.getByRole('button',{name:'另存为新版本',exact:true}).isEnabled(),false);await shot(page,'history-readonly');
 // Remove the actual external file: retained database media must still play.
 await fs.unlink(path.join(root,'original-video.mp4'));await task(page,'7a4b5d86524e');await page.waitForFunction(()=>document.querySelector('#creativeVideo').readyState>=2);results.deletedOriginalStillPlayable=true;
 // Delete stored bytes only in the disposable fixture database, leaving the media identity.
 sql("UPDATE agent_media SET data=X'' WHERE media_id='"+fixture.media_id+"'");await page.reload();await page.locator('#iceMissingMedia').waitFor({state:'visible'});await page.locator('#iceMissingMedia').scrollIntoViewIfNeeded();await shot(page,'stored-media-deleted');results.deletedStoredBytesDetected=true;
 const chooser=page.waitForEvent('filechooser');await page.locator('#iceRelink').click();await(await chooser).setFiles(path.join(root,'relink-video.mp4'));await page.locator('#creativeBriefDialog').waitFor({state:'visible'});await page.getByRole('button',{name:'仅保存输入',exact:true}).click();await page.locator('#creativeTaskStatus').filter({hasText:'v4'}).waitFor();await page.reload();await page.waitForFunction(()=>document.querySelector('#creativeVideo').readyState>=2);assert.equal(await page.locator('#iceMissingMedia').isVisible(),false);results.relinkedVersion=4;await shot(page,'relinked-v4');
 await open(page,'/market');await page.getByRole('button',{name:'管理密钥',exact:true}).click();await page.locator('#marketSettings').waitFor({state:'visible'});assert.equal(await page.locator('#marketApiKey').inputValue(),'');assert.equal(await page.locator('#marketApiKey').getAttribute('type'),'password');await shot(page,'key-dialog');
 assert.equal(results.errors.length,0,JSON.stringify(results.errors));assert(results.requests.every(r=>r.host==='127.0.0.1:8772'));assert(!results.requests.some(r=>/generate|tools\/run|transcri/.test(r.path)));results.noPaidRequests=true;
 await fs.writeFile(path.join(root,'browser-results.json'),JSON.stringify(results,null,2));console.log('PASS real browser, 6 widths, 11 nav, states, save/reopen/export, actual stored-media deletion/relink');
 }finally{if(browser)await browser.close();await stop();await fs.writeFile(path.join(root,'browser-progress.json'),JSON.stringify(results,null,2));}})().catch(e=>{console.error(e);process.exitCode=1;});
