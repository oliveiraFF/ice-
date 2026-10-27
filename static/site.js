/* Shared local navigation and search; never calls content collection endpoints. */
const SiteUI=(()=>{
  const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pages=[['/dashboard','dashboardNav','运营工作台','grid'],['/advice','adviceNav','运营建议','comment'],['/','discoverNav','发现内容','compass'],['/draft','draftNav','研究稿','file-text'],['/research','researchNav','研究增强','compass'],['/media-review','reviewNav','成片审阅','play'],['/script','scriptNav','内容任务','layers'],['/feedback','feedbackNav','反馈复盘','chart'],['/strategy','strategyNav','账号策略','user'],['/market','marketNav','API 市场','globe'],['/tools','toolsNav','工具管理','wrench']];
  const current=pages.find(p=>p[0]===(location.pathname==='/creative'?'/tools':location.pathname))||pages[0];
  document.body.classList.add('site-app','owner-workspace');
  document.querySelector('.topbar').outerHTML=`<header class="site-header"><button class="site-menu" id="siteMenu" aria-label="展开导航" aria-expanded="false" aria-controls="siteNav">☰</button><div class="site-context"><span>我的工作空间</span><b>/</b><strong>${current[2]}</strong></div><form id="siteSearch" class="site-search" role="search"><select id="siteSearchScope" aria-label="搜索范围"><option value="all">全部</option><option value="content">内容</option><option value="api">接口</option><option value="tools">工具</option></select><input type="search" id="siteSearchInput" aria-label="全站搜索" placeholder="搜索内容、接口或工具" maxlength="100" autocomplete="off"><button type="submit" aria-label="搜索">${RadarIcons.svg('search')}</button></form><span class="site-local"><i></i>本地运行</span><button class="site-settings" id="siteSettings" aria-label="数据源设置">${RadarIcons.svg('settings')}</button></header><nav id="siteNav" class="site-nav" aria-label="主导航"><a class="site-brand" href="/dashboard" aria-label="ice运营台，运营工作台"><span class="site-logo"><img src="/ice-avatar.jpg" alt="" width="40" height="40"></span><span>ice运营台<small>运营工作空间</small></span></a><span class="nav-group">工作空间</span>${pages.map((p,i)=>`${i===9?'<span class="nav-group">资源与设置</span>':''}<a id="${p[1]}" href="${p[0]}" class="${p[0]===current[0]?'active':''}" ${p[0]===current[0]?'aria-current="page"':''}>${RadarIcons.svg(p[3])}<span>${p[2]}</span></a>`).join('')}<span class="nav-foot"><i></i>个人本地版<br>数据保存在当前电脑</span></nav>`;
  document.getElementById('siteMenu').onclick=()=>{const open=document.body.classList.toggle('nav-open');document.getElementById('siteMenu').setAttribute('aria-expanded',String(open));};
  document.addEventListener('keydown',event=>{if(event.key==='Escape'){document.body.classList.remove('nav-open');document.getElementById('siteMenu').setAttribute('aria-expanded','false');}});
  document.querySelector('aside.sidebar')?.remove();
  document.querySelector('.wb-details')?.removeAttribute('open');
  document.body.insertAdjacentHTML('beforeend',`<footer class="site-footer"><span>${RadarIcons.svg('lock')}关键词与视频记录保存在本机</span><span>TikHub / 本地记录 · 额度调用由你控制</span><button data-site-settings>管理数据源 ↗</button></footer><dialog id="siteSearchDialog" class="site-search-dialog"><div class="site-dialog-heading"><h2>本地搜索结果</h2><button class="icon-button" id="closeSiteSearch" aria-label="关闭搜索">${RadarIcons.svg('x')}</button></div><p id="siteSearchStatus"></p><div id="siteSearchResults"></div></dialog><dialog id="siteSettingsDialog" class="modal"><button id="closeSiteSettings" class="close-dialog icon-button" aria-label="关闭设置">${RadarIcons.svg('x')}</button><h2>TikHub 数据源设置</h2><p>视频分析、评论分析和导入导出无需密钥。此处供API市场需要认证的接口使用；赠送额度在API市场设置。</p><form id="siteSettingsForm"><label for="siteApiKey">TikHub API Key</label><input id="siteApiKey" type="password" autocomplete="off"><p class="helper" data-owner-credential-status>由 Windows 当前账户加密保存在本机，重启自动恢复；换电脑或账户需重填。保存不执行接口，也不会开启额度。</p><p id="siteSettingsStatus" class="helper" role="status"></p><div class="dialog-actions"><button type="button" class="text-button" id="clearSiteKey">清除密钥</button><button class="primary" type="submit">保存配置</button></div></form></dialog>`);
  const el=id=>document.getElementById(id);
  fetch('/api/state?mode=live').then(r=>r.json()).then(state=>{
    if(!state.desktop_exit_enabled)return;
    const button=document.createElement('button');button.textContent='退出程序';button.id='exitDesktop';
    document.querySelector('.site-footer').append(button);
    button.onclick=async()=>{
      if(!confirm('退出前请确认已保存当前修改；现在退出程序？'))return;
      button.disabled=true;
      try{const response=await fetch('/api/desktop/exit',{method:'POST',headers:{'Content-Type':'application/json','X-Radar-Token':state.token},body:JSON.stringify({confirm:true})});const data=await response.json();if(!response.ok)throw new Error(data.error);}
      catch(error){button.disabled=false;button.textContent=error.message||'退出失败，请重试';}
    };
  }).catch(()=>{});
  async function settings(){const dialog=el('marketSettings')||el('settingsDialog')||el('siteSettingsDialog');dialog.showModal();try{const state=await (await fetch('/api/state?mode=live')).json();const status=dialog.querySelector('[data-owner-credential-status]');if(status)status.textContent=state.credential_error||(state.credential_remembered?'当前 Windows 账户已有加密凭据，重启自动恢复；清除密钥会同时移除本机保存。':'由 Windows 当前账户加密保存在本机；换电脑或账户需重填。保存不会调用接口或开启额度。');}catch{}}
  el('siteSettings').onclick=settings;document.querySelector('[data-site-settings]').onclick=settings;
  el('closeSiteSettings').onclick=()=>el('siteSettingsDialog').close();el('closeSiteSearch').onclick=()=>el('siteSearchDialog').close();
  async function key(value){const state=await (await fetch('/api/state?mode=live')).json();const response=await fetch('/api/connect',{method:'POST',headers:{'Content-Type':'application/json','X-Radar-Token':state.token},body:JSON.stringify({key:value})});const result=await response.json();if(!response.ok)throw new Error(result.error);el('siteApiKey').value='';el('siteSettingsStatus').textContent=value?'已在本机加密保存，没有执行接口。':'已清除运行及本机加密密钥。';}
  el('siteSettingsForm').onsubmit=async event=>{event.preventDefault();try{const value=el('siteApiKey').value.trim();if(!value)throw new Error('请填写密钥，或点击清除密钥');await key(value);}catch(error){el('siteSettingsStatus').textContent=error.message;}};
  el('clearSiteKey').onclick=()=>key('').catch(error=>el('siteSettingsStatus').textContent=error.message);
  const toolIndex=[['script','脚本准备'],['creative','视频分析与改编'],['video','视频数据分析'],['creator','创作者分析'],['comments','评论分析'],['download','缓存视频下载'],['voice','AI 声音克隆（本期暂缓）'],['fraud','刷量检测（本期暂缓）']];
  el('siteSearch').onsubmit=async event=>{
    event.preventDefault();const query=el('siteSearchInput').value.trim(),scope=el('siteSearchScope').value;if(!query){el('siteSearchInput').focus();return;}
    const match=value=>String(value).toLowerCase().includes(query.toLowerCase());el('siteSearchDialog').showModal();el('siteSearchStatus').textContent='正在搜索本地记录…';el('siteSearchResults').replaceChildren();
    try{
      const results=[];
      const [content,catalog]=await Promise.all([scope==='all'||scope==='content'?fetch('/api/state?mode=live').then(r=>{if(!r.ok)throw new Error('内容读取失败');return r.json();}):null,scope==='all'||scope==='api'?fetch('/api/catalog').then(r=>{if(!r.ok)throw new Error('接口目录读取失败');return r.json();}):null]);
      if(content)for(const post of content.posts)if(match(post.title+' '+post.author))results.push({type:'内容',title:post.title,note:post.author,url:'/?post='+post.id});
      if(catalog)for(const api of catalog.items)if(match(api.title+' '+api.path+' '+api.platform_name))results.push({type:'接口',title:api.title,note:api.method+' '+api.path,url:'/market?q='+encodeURIComponent(query)+'&id='+encodeURIComponent(api.id)});
      if(scope==='all'||scope==='tools')for(const [id,title] of toolIndex)if(match(title))results.push({type:'工具',title,note:'本地工具管理',url:'/tools?tool='+id});
      el('siteSearchStatus').textContent=`“${query}” · 找到 ${results.length} 项${results.length>50?'，显示前50项':''}`;
      el('siteSearchResults').innerHTML=results.length?results.slice(0,50).map(result=>`<a class="site-search-result" href="${escape(result.url)}"><span>${result.type}</span><div><strong>${escape(result.title)}</strong><p>${escape(result.note)}</p></div><b>↗</b></a>`).join(''):'<p class="site-search-empty">没有匹配结果，试试其他关键词或搜索范围。</p>';
    }catch(error){el('siteSearchStatus').textContent=error.message;}
  };
  return {escape};
})();

/* U1 interactions: ripple (mouse/keyboard), robust segment indicator, nav inert sync. */
(() => {
  if (!document.body || !document.body.classList.contains('owner-workspace')) return;
  const reduced = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : {matches: false};
  const isReduced = () => !!(reduced && reduced.matches);
  function ripple(target, x, y) {
    if (!target || target.disabled || isReduced()) return;
    const rect = target.getBoundingClientRect();
    const size = Math.max(rect.width, rect.height);
    const span = document.createElement('span');
    span.className = 'ui-ripple';
    span.style.width = span.style.height = size + 'px';
    span.style.left = (x - rect.left - size / 2) + 'px';
    span.style.top = (y - rect.top - size / 2) + 'px';
    target.appendChild(span);
    span.addEventListener('animationend', () => span.remove(), {once: true});
  }
  const clickable = 'button.primary, button.secondary, .text-button, .icon-button, .filter-chip, .only-options button, .rank-sort button, .mode-options button';
  document.body.addEventListener('pointerdown', event => {
    const target = event.target.closest(clickable);
    if (target) ripple(target, event.clientX, event.clientY);
  });
  document.body.addEventListener('keydown', event => {
    if (event.key !== 'Enter' && event.key !== ' ' && event.key !== 'Spacebar') return;
    if (event.repeat) return;
    const target = event.target.closest(clickable);
    if (!target) return;
    const rect = target.getBoundingClientRect();
    ripple(target, rect.left + rect.width / 2, rect.top + rect.height / 2);
  });
  function segment(container) {
    if (!container || container.dataset.uiSeg === 'ready') return;
    container.dataset.uiSeg = 'ready';
    const ensure = () => {
      let indicators = [...container.querySelectorAll(':scope > .ui-seg-indicator')];
      indicators.forEach((node, index) => { if (index > 0) node.remove(); });
      let indicator = indicators[0];
      if (!indicator) { indicator = document.createElement('span'); indicator.className = 'ui-seg-indicator'; }
      if (indicator.parentNode !== container || indicator !== container.firstElementChild) container.prepend(indicator);
      return indicator;
    };
    const place = () => {
      const button = container.querySelector('button[aria-pressed="true"], button.selected');
      const indicator = ensure();
      if (!button) { indicator.style.display = 'none'; return; }
      const cr = container.getBoundingClientRect(); const br = button.getBoundingClientRect();
      indicator.style.display = 'block';
      indicator.style.left = (br.left - cr.left) + 'px';
      indicator.style.top = (br.top - cr.top) + 'px';
      indicator.style.width = br.width + 'px';
      indicator.style.height = br.height + 'px';
      indicator.style.bottom = 'auto';
    };
    let scheduled = false;
    const schedule = () => { if (scheduled) return; scheduled = true; requestAnimationFrame(() => { scheduled = false; place(); }); };
    new MutationObserver(schedule).observe(container, {childList: true, subtree: true, attributes: true, attributeFilter: ['aria-pressed', 'class']});
    if (window.ResizeObserver) new ResizeObserver(schedule).observe(container);
    window.addEventListener('resize', schedule);
    schedule();
  }
  const initSegments = () => {
    ['#presets', '.only-options', '.rank-sort', '.mode-options', '.market-segments'].forEach(selector => {
      if (selector.startsWith('#')) { const el = document.querySelector(selector); if (el) segment(el); return; }
      document.querySelectorAll(selector).forEach(segment);
    });
  };
  initSegments();
  const presets = document.getElementById('presets');
  if (presets) new MutationObserver(initSegments).observe(presets, {childList: true});
  const nav = document.getElementById('siteNav');
  const menu = document.getElementById('siteMenu');
  function syncNav() {
    if (!nav) return;
    const small = window.matchMedia('(max-width: 900px)').matches;
    const open = document.body.classList.contains('nav-open');
    if (small && !open) { nav.setAttribute('inert', ''); nav.setAttribute('aria-hidden', 'true'); }
    else { nav.removeAttribute('inert'); nav.removeAttribute('aria-hidden'); }
    if (menu) menu.setAttribute('aria-expanded', String(small && open));
  }
  syncNav();
  window.addEventListener('resize', syncNav);
  if (menu) menu.addEventListener('click', () => setTimeout(syncNav, 0));
  document.addEventListener('keydown', event => {
    if (event.key !== 'Escape') return;
    if (!nav || !menu) return;
    const small = window.matchMedia('(max-width: 900px)').matches;
    const focusInside = nav.contains(document.activeElement);
    if (small && (document.body.classList.contains('nav-open') || focusInside)) {
      document.body.classList.remove('nav-open');
      menu.setAttribute('aria-expanded', 'false');
      menu.focus();
      syncNav();
    } else {
      setTimeout(syncNav, 0);
    }
  });
  function enhanceCards() {
    const grid = document.getElementById('grid');
    if (!grid) return;
    grid.querySelectorAll('.content-card').forEach(card => {
      if (card.dataset.uiCard === 'ready') return;
      card.dataset.uiCard = 'ready';
      const id = card.id.replace('post-', '');
      const checkbox = document.createElement('label');
      checkbox.className = 'card-select';
      checkbox.title = '仅在当前页面选择，不改变业务状态';
      checkbox.innerHTML = '<input type="checkbox" data-card-select="' + id + '" aria-label="选择内容"><span class="card-select-mark"></span>';
      card.insertBefore(checkbox, card.firstChild);
      const hint = card.querySelector('.open-hint');
      if (hint && !hint.querySelector('span')) {
        const text = document.createElement('span'); text.textContent = '查看详情'; hint.appendChild(text);
      }
    });
  }
  const grid = document.getElementById('grid');
  if (grid) { enhanceCards(); new MutationObserver(enhanceCards).observe(grid, {childList: true}); }
  document.addEventListener('change', event => {
    const box = event.target.closest ? event.target.closest('[data-card-select]') : null;
    if (!box) return;
    const card = box.closest('.content-card');
    if (card) card.classList.toggle('is-selected', box.checked);
  });
})();

/* U2-REWORK1 R1: hide empty error boxes without touching real error writes. */
(() => {
  if (!document.body || !document.body.classList.contains('owner-workspace')) return;
  function sync(el){
    if (!el || !el.classList) return;
    const empty = !el.textContent || !el.textContent.trim();
    if (empty) {
      if (!el.dataset.uiEmptyError) { el.dataset.uiEmptyError = '1'; el.hidden = true; }
    } else if (el.dataset.uiEmptyError) {
      delete el.dataset.uiEmptyError; el.hidden = false;
    }
  }
  function scan(){ document.querySelectorAll('.script-error, .screen-error').forEach(sync); }
  new MutationObserver(scan).observe(document.body, {childList:true, subtree:true, characterData:true});
  scan();
})();

const agentSettingsScript = document.createElement('script');
agentSettingsScript.src = '/agent-workspace-settings.js';
document.head.append(agentSettingsScript);
