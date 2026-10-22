/* Customer navigation and individual credential settings. No general API directory. */
const ClientUI=(()=>{
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pages=[['/','发现内容'],['/dashboard','数据大屏'],['/tools','工具管理']];
  document.body.classList.add('site-app');
  document.querySelector('.topbar').outerHTML=`<header class="site-header"><a href="/" class="site-brand"><span class="site-logo"><img src="/ice-avatar.jpg" alt="" width="40" height="40"></span>ice运营台<span class="site-edition">DESKTOP</span></a><form id="siteSearch" class="site-search" role="search"><input id="siteSearchInput" type="search" aria-label="搜索本地内容" placeholder="搜索已收录的内容" maxlength="100"><button type="submit" aria-label="搜索">${RadarIcons.svg('search')}</button></form><span class="site-local"><i></i>本地运行</span><button id="siteSettings" class="site-settings" aria-label="连接设置">${RadarIcons.svg('settings')}</button></header><nav class="site-nav" aria-label="主导航">${pages.map(([path,title])=>`<a href="${path}" class="${path===(location.pathname==='/creative'?'/tools':location.pathname)?'active':''}" ${path===(location.pathname==='/creative'?'/tools':location.pathname)?'aria-current="page"':''}>${title}</a>`).join('')}<span>你的内容选题工作台</span></nav>`;
  document.querySelector('aside.sidebar')?.remove();
  document.body.insertAdjacentHTML('beforeend',`<footer class="site-footer"><span>${RadarIcons.svg('lock')}关键词与视频记录保存在本机</span><span>联网检索 / 本地记录</span><button id="clientSettingsLink">连接设置 ↗</button></footer><dialog id="clientSettingsDialog" class="modal"><button id="closeClientSettings" class="close-dialog icon-button" aria-label="关闭连接设置">${RadarIcons.svg('x')}</button><h2>连接设置</h2><p>每份软件使用对应客户的专属密钥。保存设置不会获取视频。</p><form id="clientSettingsForm"><label for="clientCustomer">客户标识</label><input id="clientCustomer" maxlength="60" required placeholder="例如：客户001"><label for="clientKey">专属访问密钥</label><input id="clientKey" type="password" autocomplete="off" maxlength="500" placeholder="填写分配给此客户的独立密钥"><label class="client-check"><input id="clientRemember" type="checkbox">在此 Windows 账户加密保存</label><p class="helper">换电脑或 Windows 账户后需重新配置。不要将共用主密钥分发给客户。</p><fieldset class="client-usage"><legend>调用保护</legend><label class="client-check"><input id="clientEnabled" type="checkbox">开启赠送额度调用</label><div class="client-usage-fields"><label>本机累计次数上限<input id="clientCalls" type="number" min="0" max="1000000" step="1" required></label><label>本次保存后有效天数<input id="clientDays" type="number" min="1" max="3650" step="1" placeholder="留空持续开启"></label></div><p id="clientUsage" class="helper"></p><p class="helper">余额不足即停止，不使用充值余额。失败也可能预留一次次数；重启不重置累计用量。此为本机保护，不是供应商侧限额。</p></fieldset><p id="clientSettingsStatus" class="clear-error" role="status"></p><div class="dialog-actions"><button type="button" id="forgetClientKey" class="text-button">清除本机密钥</button><button class="primary" type="submit">保存设置</button></div></form></dialog>`);
  const el=id=>document.getElementById(id);
  let config=null;
  async function request(path,body){
    const state=await (await fetch('/api/state?mode=live')).json();
    const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Radar-Token':state.token},body:JSON.stringify(body)});
    const result=await response.json();if(!response.ok)throw new Error(result.error||'操作失败');return result;
  }
  async function settings(){try{
    config=await request('/api/client/config');el('clientCustomer').value=config.customer;el('clientCustomer').readOnly=Boolean(config.customer);el('clientKey').value='';
    el('clientKey').placeholder=config.connected?'已配置；留空保留':'填写分配给此客户的独立密钥';el('clientRemember').checked=config.remembered||!config.customer;
    el('clientEnabled').checked=config.access.enabled;el('clientCalls').value=config.access.limit||20;
    el('clientDays').value=config.access.expires_at?Math.max(1,Math.ceil((config.access.expires_at-Date.now()/1000)/86400)):'';
    el('clientUsage').textContent=`已预留 ${config.access.spent} 次，剩余本机预算 ${config.access.remaining} 次。`;
    el('clientSettingsStatus').textContent=config.restore_error?'加密凭据无法读取，请重新填写专属密钥。':'';
    el('forgetClientKey').disabled=!config.connected&&!config.remembered;el('clientSettingsDialog').showModal();
  }catch(error){alert(error.message);}}
  el('siteSettings').onclick=settings;el('clientSettingsLink').onclick=settings;
  el('closeClientSettings').onclick=()=>el('clientSettingsDialog').close();el('clientSettingsDialog').addEventListener('close',()=>{el('clientKey').value='';});
  el('clientSettingsForm').onsubmit=async event=>{event.preventDefault();const button=event.submitter;button.disabled=true;try{
    await request('/api/client/config',{customer:el('clientCustomer').value.trim(),key:el('clientKey').value.trim(),remember:el('clientRemember').checked,enabled:el('clientEnabled').checked,calls:Number(el('clientCalls').value),days:el('clientDays').value?Number(el('clientDays').value):null});
    el('clientKey').value='';el('clientSettingsDialog').close();document.dispatchEvent(new Event('radar-client-config'));
  }catch(error){el('clientSettingsStatus').textContent=error.message;}finally{button.disabled=false;}};
  el('forgetClientKey').onclick=async()=>{try{await request('/api/client/forget',{});el('clientKey').value='';el('clientSettingsStatus').textContent='已清除本机密钥；供应商侧撤销须另行操作。';el('forgetClientKey').disabled=true;document.dispatchEvent(new Event('radar-client-config'));}catch(error){el('clientSettingsStatus').textContent=error.message;}};
  el('siteSearch').onsubmit=event=>{event.preventDefault();const query=el('siteSearchInput').value.trim();if(query)location.href='/?q='+encodeURIComponent(query);};
  async function find(keyword,kind){const state=await request('/api/client/config');if(!state.connected||!state.access.active){await settings();throw new Error('请先配置专属密钥，并开启次数预算后再获取视频。');}return request('/api/client/search',{keyword,kind});}
  return {find,settings,escape};
})();
const SiteUI={escape:ClientUI.escape};
