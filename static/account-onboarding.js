/* finesse component · existing Liquid Glass tokens · account setup with three required inputs */
(() => {
  'use strict';
  let state=null,busy=false,requestId=crypto.randomUUID().replaceAll('-','');
  const home=['/','/dashboard'].includes(location.pathname);
  const dialog=document.createElement('dialog');dialog.id='accountSetupDialog';dialog.className='account-setup-dialog';
  dialog.innerHTML='<button type="button" id="accountSetupClose" class="secondary">关闭</button><div id="accountDialogBody"></div>';
  const panel=document.createElement('section');panel.id='accountSetupPanel';panel.className='account-setup-panel';panel.setAttribute('aria-labelledby','accountSetupTitle');
  panel.innerHTML=`<div class="account-setup-heading"><div><p class="account-setup-eyebrow">开始你的内容工作</p><h2 id="accountSetupTitle">创建你的账号资料</h2><p>填好三项信息，软件会自动整理和保存资料。之后可随时完善。</p></div><span id="accountSetupBadge">本机保存</span></div>
    <form id="accountSetupForm"><label>账号名称<input name="name" id="accountSetupName" maxlength="100" autocomplete="off" placeholder="例如：我的创作账号" required></label><label>主要做什么内容<textarea name="direction" id="accountSetupDirection" maxlength="300" rows="2" placeholder="写下想持续分享的内容方向" required></textarea></label><label>主要给谁看<textarea name="audience" id="accountSetupAudience" maxlength="300" rows="2" placeholder="描述你希望帮助或吸引的人" required></textarea></label>
    <details><summary>补充资料（选填）</summary><label>平台<input id="accountSetupPlatform" maxlength="60" placeholder="例如：抖音；还没决定可以留空"></label><label>制作条件 / 真实资源<textarea id="accountSetupResources" maxlength="500" rows="2" placeholder="例如：可以录屏配音，有本人制作过程素材"></textarea></label><label>阶段目标<textarea id="accountSetupGoal" maxlength="300" rows="2" placeholder="例如：先积累作品，或验证一个内容方向"></textarea></label></details>
    <p class="account-setup-note">填写内容先保存为草稿；创建不会发起收费调用。正式策略需你另行确认。</p><button id="accountSetupCreate" class="primary" type="submit">创建账号并继续</button></form>
    <p id="accountSetupMessage" role="status" aria-live="polite"></p><button id="accountSetupRetry" class="secondary" type="button" hidden>重新读取</button>
    <div id="accountSetupReady" hidden><h3 id="accountSetupNameSaved"></h3><p id="accountSetupSummary"></p><div class="account-setup-next"><a class="primary" id="accountSetupImport" href="/creative">导入本地视频</a><a class="secondary" href="/strategy">完善账号策略</a></div><details id="accountSetupFiles"><summary>资料管理</summary><p id="accountSetupLocation"></p><p>备份此账号资料目录用于归档，不包含整个软件数据库。</p><div class="account-setup-next"><button id="accountSetupOpenFolder" class="secondary" type="button">打开资料文件夹</button><button id="accountSetupBackup" class="secondary" type="button">备份账号资料</button></div></details></div>`;
  document.body.append(dialog);dialog.querySelector('#accountDialogBody').append(panel);
  const el=id=>document.getElementById(id),fields={name:'Name',direction:'Direction',audience:'Audience',platform:'Platform',resources:'Resources',goal:'Goal'};
  const host=document.createElement('div');host.id='accountSetupHost';
  if(home)document.querySelector('main')?.prepend(host);
  async function api(path,body){
    const options={};
    if(body){const response=await fetch('/api/state?mode=live');const local=await response.json();options.method='POST';options.headers={'Content-Type':'application/json','X-Radar-Token':local.token};options.body=JSON.stringify(body);}
    const response=await fetch(path,options);
    if(!response.ok){const error=await response.json();throw Error(error.error||'本机操作未完成');}
    return response;
  }
  function message(text,error=false){el('accountSetupMessage').textContent=text;el('accountSetupMessage').dataset.error=String(error);}
  function controls(){
    el('accountSetupCreate').disabled=busy;el('accountSetupCreate').textContent=busy?'正在创建…':state?.kind==='pending'?'继续上次创建':'创建账号并继续';
    el('accountSetupForm').setAttribute('aria-busy',String(busy));
    Object.values(fields).forEach(suffix=>el('accountSetup'+suffix).disabled=busy||state?.kind==='pending');
    el('accountSetupBackup').disabled=busy;el('accountSetupOpenFolder').disabled=busy;
  }
  function render(){
    const managed=state.kind==='managed',existing=['legacy','external'].includes(state.kind);
    el('accountSetupForm').hidden=!state.can_create;el('accountSetupReady').hidden=state.can_create;
    el('accountSetupTitle').textContent=managed?'账号资料已准备好':existing?'继续使用已有资料':'创建你的账号资料';
    el('accountSetupBadge').textContent=managed?(state.strategy_confirmed?'策略已确认':'资料草稿'):existing?'原资料保留':'本机保存';
    if(managed){el('accountSetupNameSaved').textContent=state.account.name;el('accountSetupSummary').textContent=state.account.direction+' · 面向：'+state.account.audience;el('accountSetupLocation').textContent=state.workspace_path;message(state.sync_error||'资料已自动创建并连接。可以先导入一条本地视频；正式策略确认前保持草稿。',!!state.sync_error);}
    if(existing){el('accountSetupNameSaved').textContent='已有账号资料';el('accountSetupSummary').textContent=state.message;el('accountSetupFiles').hidden=true;message('原资料保持不变，可继续完善策略或在高级设置查看连接。');}
    if(state.kind==='new')message('账号资料由软件自动保存，无需准备文件夹。');
    if(state.kind==='pending'){requestId=state.request_id;Object.entries(fields).forEach(([key,suffix])=>el('accountSetup'+suffix).value=state.input[key]||'');message('上次创建尚未完成，点击继续可恢复原请求，不会重复建立账号。');}
    if(home&&!dialog.open){if(existing)dialog.querySelector('#accountDialogBody').append(panel);else host.append(panel);}
    controls();
  }
  async function refresh(){try{state=await(await api('/api/agent/onboarding')).json();el('accountSetupRetry').hidden=true;render();}catch(error){message(error.message,true);el('accountSetupRetry').hidden=false;}}
  el('accountSetupForm').addEventListener('submit',async event=>{
    event.preventDefault();if(busy)return;busy=true;controls();message('正在准备账号资料，请稍候…');
    try{const body={request_id:requestId};Object.entries(fields).forEach(([key,suffix])=>body[key]=el('accountSetup'+suffix).value);state=await(await api('/api/agent/onboarding/create',body)).json();render();document.dispatchEvent(new Event('agent-workspace-config-changed'));}
    catch(error){message(error.message+'；资料不会被覆盖，可重试原请求。',true);}
    finally{busy=false;controls();}
  });
  el('accountSetupRetry').onclick=refresh;
  el('accountSetupClose').onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>{if(home&&!['legacy','external'].includes(state?.kind))host.append(panel);});
  document.addEventListener('ice-open-account-setup',()=>{dialog.querySelector('#accountDialogBody').append(panel);if(!dialog.open)dialog.showModal();refresh();});
  document.addEventListener('agent-workspace-config-changed',refresh);
  el('accountSetupOpenFolder').onclick=async()=>{try{await api('/api/agent/onboarding/open',{});message('已打开本机资料文件夹。');}catch(error){message(error.message,true);}};
  el('accountSetupBackup').onclick=async()=>{if(busy)return;busy=true;controls();try{const response=await api('/api/agent/onboarding/backup',{});const url=URL.createObjectURL(await response.blob());const link=document.createElement('a');link.href=url;link.download='ICE-account-'+state.account_uid+'.zip';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);message('备份已生成，请保存到安全位置；其中包含你的账号资料。');}catch(error){message(error.message,true);}finally{busy=false;controls();}};
  fetch('/api/state?mode=live').then(r=>r.json()).then(local=>{if(local.agent_tasks_enabled)refresh();}).catch(()=>{});
})();
