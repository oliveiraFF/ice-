const icon=name=>RadarIcons.svg(name);
const $=id=>document.getElementById(id);
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=value=>value===null||value===undefined?'—':value>=100000000?(value/100000000).toFixed(2).replace(/\.?0+$/,'')+'亿':value>=10000?(value/10000).toFixed(1).replace(/\.0$/,'')+'万':Number(value).toLocaleString('zh-CN');
const playText=value=>value===null||value===undefined?'未知':fmt(value);
const platformName=p=>p==='dy'?'抖音':'小红书';
const age=p=>RadarData.ageHours(p);
const velocity=p=>age(p)!==null&&p.likes!==null?Math.round(p.likes/Math.max(age(p),1)):null;
const ageText=p=>age(p)===null?'时间未知':age(p)<24?'24小时内':Math.floor(age(p)/24)+'天前';
const dateText=value=>value?new Date(value*1000).toLocaleString('zh-CN',{timeZone:'America/Los_Angeles',hour12:false}):'未知';
const params=new URLSearchParams(location.search);
let mode=params.has('post')?'live':localStorage.getItem('radar-mode')==='demo'?'demo':'live';
let selectedKeyword=Number(params.get('keyword')||localStorage.getItem('radar-keyword'))||null,platform='all',preset='all',tag='',direction='',contentQuery=params.get('q')||'',activePost=null;
let data={keywords:[],posts:[],token:''},toastTimer;
let directionState={scope:'',result:null,error:''},generationDraft=null,aiBusy=false;
function artwork(p){const colors=[['#e8e0c5','#c6cfad'],['#dae4f1','#adb9d5'],['#e9dbce','#cabfae'],['#d9eee7','#b0d8d1'],['#e4def0','#cbb9d7']][Number(p.id)%5];return `<svg class="cover-art" viewBox="0 0 360 320" role="img" aria-label="暂无封面"><defs><linearGradient id="cover${p.id}" x2="1" y2="1"><stop stop-color="${colors[0]}"/><stop offset="1" stop-color="${colors[1]}"/></linearGradient></defs><rect width="360" height="320" fill="url(#cover${p.id})"/><circle cx="180" cy="155" r="25" fill="none" stroke="#354044" stroke-opacity=".2" stroke-width="3"/><path d="m174 143 20 12-20 12Z" fill="#354044" opacity=".2"/><text x="180" y="205" fill="#59645f" font-size="12" text-anchor="middle" opacity=".6">暂无封面</text></svg>`;}
function cover(p){return p.cover?`<img src="${esc(p.cover)}" alt="${esc(p.title)}" loading="lazy" referrerpolicy="no-referrer">`:artwork(p);}
function toast(message){clearTimeout(toastTimer);$('toast').textContent=message;$('toast').hidden=false;toastTimer=setTimeout(()=>$('toast').hidden=true,5000);}
async function api(path,body){const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Radar-Token':data.token},body:JSON.stringify(body)});const value=await response.json();if(!response.ok)throw new Error(value.error||'操作失败');return value;}
async function load(){data=await api('/api/state?mode='+mode);if(selectedKeyword!==null&&!data.keywords.some(k=>k.id===selectedKeyword))selectedKeyword=null;const post=data.posts.find(p=>p.id===Number(params.get('post')));if(post)selectedKeyword=post.keyword_ids[0]||selectedKeyword;render();if(post&&!activePost)showDetail(post.id);}
function selectedName(){return contentQuery?'本地内容搜索':selectedKeyword===null?'全部内容':data.keywords.find(k=>k.id===selectedKeyword)?.name||'发现内容';}
function basePosts(){return contentQuery||selectedKeyword===null?data.posts:data.posts.filter(p=>p.keyword_ids.includes(selectedKeyword));}
function baselinePosts(){return RadarData.filter(basePosts(),{platform,query:contentQuery,minPlays:Number($('playFilter').value),days:Number($('timeFilter').value),sort:$('sortOrder').value});}
function filtered(){const group=directionState.result?.directions[Number(direction)];return RadarData.filter(baselinePosts(),{preset,tag,postIds:direction!==''?(group?.post_ids||[]):null,sort:$('sortOrder').value});}
function setOnly(kind,value){({preset,tag,direction}=RadarData.selectOnly(kind,value));}
function scopeSignature(posts){return JSON.stringify([mode,...[...posts].sort((a,b)=>a.id-b.id).map(p=>[p.id,p.title,RadarData.tags(p)])]);}
function renderOnly(){
  const posts=baselinePosts(),scope=scopeSignature(posts);
  if(directionState.scope!==scope){
    directionState={scope,result:null,error:''};if(direction!=='')setOnly('common','all');
    if(posts.length>200)directionState.error='当前超过200条，请缩小关键词或筛选范围后生成。';
    else api('/api/ai/cache',{mode,ids:posts.map(p=>p.id)}).then(result=>{if(directionState.scope!==scope)return;directionState.result=result;render();}).catch(error=>{if(directionState.scope!==scope)return;directionState.error=error.message;render();});
  }
  const shared=RadarData.sharedTags(posts);if(tag&&!shared.some(([name])=>name===tag))setOnly('common','all');
  const common=[['all','全部',posts.length,''],['first','首次上榜','—','缺少前一天可比榜单'],['recent','24 小时内发布',RadarData.filter(posts,{preset:'recent'}).length,'按视频发布时间'],['small','低粉爆款',posts.filter(RadarData.small).length,'粉丝＜1万，可叠加播放量']];
  $('presets').innerHTML=common.map(([value,label,count,note])=>`<button data-preset="${value}" ${value==='first'?'disabled':''} aria-pressed="${preset===value&&!tag&&direction===''}"><span class="only-radio"></span><span>${label} <b>${count}</b>${note?`<small>${note}</small>`:''}</span></button>`).join('');
  const result=directionState.result;
  $('directionStatus').textContent=aiBusy?'正在生成，请等待模型返回…':directionState.error||(!result?'读取本地分类…':result.cached?`AI 已归类 ${result.count} 条 · ${dateText(result.generated_at)}`:result.config.endpoint?'尚未生成 · 按当前范围的标题和标签归类':'尚未生成 · 请先配置 AI 模型服务');
  $('generateDirections').textContent=result?.cached?'重新生成':'生成 AI 分类';
  $('generateDirections').disabled=aiBusy||!posts.length||posts.length>200;$('aiSettingsButton').disabled=aiBusy;
  $('directions').innerHTML=result?.directions.length?result.directions.map((group,index)=>{
    const members=posts.filter(p=>group.post_ids.includes(p.id));
    return `<button class="direction-card" data-direction="${index}" aria-pressed="${direction===String(index)}"><span class="direction-covers">${members.slice(0,3).map(p=>cover(p)).join('')}</span><span class="direction-copy"><strong>${esc(group.name)}</strong><span class="direction-count">${[...new Set(members.map(p=>p.platform))].map(p=>RadarIcons.platform(p)).join('')} ${members.length} 条视频</span><span class="direction-description">${esc(group.description)}</span></span><span class="only-radio"></span></button>`;
  }).join(''):'<p class="direction-empty">'+(posts.length?'配置模型后，点击“生成 AI 分类”查看内容方向。':'当前范围没有视频，先获取或导入作品。')+'</p>';
  document.querySelectorAll('#directions img').forEach(img=>img.addEventListener('error',()=>img.replaceWith(Object.assign(document.createElement('span'),{className:'direction-cover-missing',textContent:'暂无封面'})),{once:true}));
  $('tags').innerHTML=shared.length?shared.map(([name,count])=>`<button data-tag="${esc(name)}" aria-pressed="${tag===name}"><span class="only-radio"></span>#${esc(name)} <small>${count}</small></button>`).join(''):'<p>当前范围没有至少 2 条视频共用的标签。</p>';
}
function render(){
  localStorage.setItem('radar-mode',mode);localStorage.setItem('radar-keyword',selectedKeyword??'');
  $('pageTitle').textContent=selectedName();$('pageSubtitle').textContent=mode==='demo'?'演示样本，仅用于体验界面。':'本地缓存、TikHub返回及用户导入';
  $('fetchAccessStatus').textContent=data.access?.active?'赠送额度调用已开启':'赠送额度调用已关闭或停止';
  $('keywords').innerHTML=`<button class="keyword ${selectedKeyword===null&&!contentQuery?'active':''}" data-keyword="all"><span class="hash">#</span><span>全部关键词</span><span class="count">${data.posts.length}</span></button>`+data.keywords.map(k=>`<button class="keyword ${k.id===selectedKeyword&&!contentQuery?'active':''}" data-keyword="${k.id}"><span class="hash">#</span><span>${esc(k.name)}</span><span class="count">${data.posts.filter(p=>p.keyword_ids.includes(k.id)).length}</span></button>`).join('');
  for(const [key,value] of Object.entries({mode,platform,preset}))document.querySelectorAll(`[data-${key}]`).forEach(b=>{b.classList.toggle('selected',b.dataset[key]===value);b.setAttribute('aria-pressed',b.dataset[key]===value);});
  document.querySelectorAll('[data-platform]').forEach(b=>{b.disabled=mode==='live'&&b.dataset.platform==='xhs'&&!data.posts.some(p=>p.platform==='xhs');b.title=b.disabled?'尚无小红书本地视频，可导入JSON':'';});
  $('modeMessage').textContent=mode==='demo'?'虚构演示样本':'缓存与用户导入';
  $('scanSummaryLine').textContent=mode==='demo'?'当前显示独立演示样本，不代表真实平台表现。':`本地已收录 ${data.posts.length} 条视频；未知指标不补零。接口由你选择后手动执行，不自动扫描。`;
  const scan=data.last_scan;$('scanArchive').hidden=!scan;$('scanStatus').replaceChildren();
  if(scan){$('scanStatus').textContent='历史记录 · '+dateText(scan.at)+'\n'+(scan.message||scan.error||'')+'\n历史标价上限 $'+scan.cost_upper_bound+'；旧版热榜采集记录。';if(scan.response_saved){const a=document.createElement('a');a.href='/api/last-response';a.target='_blank';a.rel='noopener noreferrer';a.textContent='查看历史原始响应 ↗';$('scanStatus').append(document.createElement('br'),a);}if(scan.cache_url?.startsWith('https://cache.tikhub.io/')){const a=document.createElement('a');a.href=scan.cache_url;a.target='_blank';a.rel='noopener noreferrer';a.textContent=' 打开供应商缓存 ↗';$('scanStatus').append(a);}}
  renderOnly();
  $('contentQueryBar').hidden=!contentQuery;$('contentQueryText').textContent='搜索：'+contentQuery;
  const posts=filtered();$('keywordTitle').textContent='视频内容';$('resultCount').textContent=posts.length+' 条'+(mode==='demo'?'演示样本':'内容');
  $('grid').innerHTML=posts.map((p,i)=>`<article class="content-card ${p.id===activePost?'is-highlighted':''}" id="post-${p.id}" tabindex="-1"><button class="cover-button" data-detail="${p.id}" aria-label="查看：${esc(p.title)}">${cover(p)}<span class="sample-rank">样本 #${i+1}</span><span class="cover-labels"><span class="platform-badge ${p.platform}">${RadarIcons.platform(p.platform)}${platformName(p.platform)}</span></span><span class="open-hint">${icon('arrow')}</span></button><div class="card-body"><div class="card-topline"><span class="play-count"><small>播放</small>${playText(p.plays)}</span><span class="post-age">${ageText(p)}</span></div><button class="card-title" data-detail="${p.id}">${esc(p.title)}</button><p class="card-author"><span class="avatar">${esc((p.author||'—')[0])}</span>${esc(p.author||'作者未知')}</p><div class="card-bottom"><span class="stat" title="点赞">${icon('heart')}${fmt(p.likes)}</span><span class="stat" title="平台收藏数">${icon('bookmark')}${fmt(p.saves)}</span><span class="stat" title="评论">${icon('comment')}${fmt(p.comments)}</span></div></div></article>`).join('');
  document.querySelectorAll('#grid img').forEach(img=>img.addEventListener('error',()=>{const p=data.posts.find(p=>p.id===Number(img.closest('[data-detail]').dataset.detail));if(p)img.outerHTML=artwork(p);},{once:true}));
  $('empty').hidden=posts.length>0;$('emptyMessage').textContent=basePosts().length?'试试放宽筛选；时间未知的内容仅在全部时间中显示。':'当前关键词没有视频，可选择TikHub接口获取或导入JSON。';$('emptyAction').textContent=basePosts().length?'清除筛选':'导入本地视频';
  $('lastUpdated').textContent='视频最近记录 '+dateText(Math.max(0,...data.posts.map(p=>p.updated_at||0)));$('metricNote').textContent='播放量按缓存或用户导入来源展示；未知值排最后。样本排序不代表全站播放榜或成交表现。';
  renderHeatRanking(posts);
  renderClearControls();
}
function renderHeatRanking(posts){
  const summary=RadarData.overview(posts),sort=$('sortOrder').value;
  $('radarCount').textContent=summary.total;
  $('radarPlays').textContent=summary.plays===null?'未知':fmt(summary.plays);
  $('radarPlaysNote').textContent=`${summary.playsKnown}条已知 / ${summary.total}条样本`;
  $('radarSmall').textContent=summary.eligible?summary.small:'—';
  $('radarSmallNote').textContent=`${summary.eligible}条粉丝已知 · 少于1万`;
  $('heatSortNote').textContent=sort==='plays'?'按已知播放量排序，条形越长播放越高':sort==='newest'?'按发布时间排序，时间未知排最后':'当前排序：'+$('sortOrder').selectedOptions[0].textContent;
  document.querySelectorAll('[data-rank-sort]').forEach(button=>button.setAttribute('aria-pressed',button.dataset.rankSort===sort));
  $('heatRanking').innerHTML=posts.length?posts.slice(0,6).map((p,i)=>{
    const width=p.plays!==null&&p.plays!==undefined&&summary.highest>0?Math.min(100,p.plays/summary.highest*100):0;
    return `<button class="heat-row ${p.id===activePost?'chosen':''}" data-rank="${p.id}" aria-label="定位视频：${esc(p.title)}"><span class="heat-index">${i+1}</span><span class="heat-info"><strong>${esc(p.title)}</strong><span class="heat-meta">${esc(p.author||'作者未知')} · ${platformName(p.platform)} <span>${ageText(p)}</span></span><svg viewBox="0 0 100 4" preserveAspectRatio="none" aria-hidden="true"><rect width="100" height="4" rx="2" class="heat-track"/><rect width="${width}" height="4" rx="2" class="heat-bar"/></svg></span><span class="heat-value"><strong>${playText(p.plays)}</strong><small>播放</small></span></button>`;
  }).join(''):'<p class="heat-empty">当前筛选没有作品，可重置筛选或选择接口获取内容。</p>';
}
function locate(id){const card=$('post-'+id);if(!card){toast('该视频已被筛选排除，清除筛选后可查看。');return;}activePost=id;document.querySelectorAll('.content-card').forEach(el=>el.classList.toggle('is-highlighted',el.id==='post-'+id));document.querySelectorAll('[data-rank]').forEach(el=>el.classList.toggle('chosen',Number(el.dataset.rank)===id));card.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'center'});card.focus({preventScroll:true});}
$('heatRanking').onclick=event=>{const row=event.target.closest('[data-rank]');if(row)locate(Number(row.dataset.rank));};
document.querySelectorAll('[data-rank-sort]').forEach(button=>button.onclick=()=>{$('sortOrder').value=button.dataset.rankSort;render();});

function showDetail(id,open=true) {
  activePost=id; const p=data.posts.find(p=>p.id===id); if(!p)return;
  $('detailContent').innerHTML=`<div class="drawer-header"><span class="platform-badge ${p.platform}">${RadarIcons.platform(p.platform)} ${platformName(p.platform)}</span><span>${mode==='demo'?'演示内容':'本地记录 · 来源见下方'}</span><button class="icon-button" data-close aria-label="关闭详情">${icon('x')}</button></div><div class="drawer-main"><div class="drawer-cover">${cover(p)}</div><h2>${esc(p.title)}</h2><p class="drawer-author">${esc(p.author)} · ${ageText(p)}</p><div class="detail-stats">${[['播放量',p.plays],['点赞',p.likes],['平台收藏',p.saves],['评论',p.comments],['粉丝',p.followers]].map(([n,v])=>`<div><span>${n}</span><strong>${n==='播放量'?playText(v):fmt(v)}</strong></div>`).join('')}</div><div class="detail-section"><h3>${mode==='demo'?'演示选题说明':'内容说明'}</h3><p>${esc(p.description || '这里只展示采集结果，暂未进行视频转写或画面分析。')}</p></div><div class="detail-section"><h3>数据记录</h3><dl class="detail-meta"><dt>发布时间</dt><dd>${dateText(p.published_at)}</dd><dt>首次收录</dt><dd>${dateText(p.first_seen)}</dd><dt>最近记录</dt><dd>${dateText(p.updated_at)}</dd><dt>播放量核查</dt><dd>${dateText(p.plays_checked_at)}</dd><dt>平均点赞 / 时</dt><dd>${fmt(velocity(p))} · 非实时增速</dd><dt>数据来源</dt><dd>${mode==='demo'?'本地虚构样本，插画封面':esc(p.source || '历史采集结果')}</dd></dl></div><div class="drawer-actions">${p.url?`<a href="${esc(p.url)}" class="secondary" target="_blank" rel="noopener noreferrer">打开原视频 ${icon('arrow')}</a>`:'<span class="helper">没有可用的原视频链接</span>'}</div><div class="connection-info">${icon('info')}<p>当前展示缓存或用户导入的视频数据，视频转写和画面分析尚未接入。</p></div></div>`;
  if(open)$('detailDialog').showModal();
}


function resetFilters(){platform='all';preset='all';tag='';direction='';contentQuery='';selectedKeyword=null;activePost=null;$('timeFilter').value='0';$('playFilter').value='0';$('sortOrder').value='plays';$('searchKeywordInput').value='';params.delete('q');params.delete('post');params.delete('keyword');history.replaceState(null,'',location.pathname+(params.size?'?'+params.toString():''));render();toast('已清除全部筛选，显示全部关键词内容');}
document.addEventListener('click',async event=>{const button=event.target.closest('button');if(!button)return;try{if(button.hasAttribute('data-close')){button.closest('dialog').close();return;}if(button.dataset.action==='add'){$('keywordInput').value=$('searchKeywordInput').value.trim();$('addDialog').showModal();$('keywordInput').focus();}if(button.dataset.action==='settings')$('settingsDialog').showModal();if(button.dataset.keyword){selectedKeyword=button.dataset.keyword==='all'?null:Number(button.dataset.keyword);setOnly('common','all');contentQuery='';params.delete('q');params.delete('post');history.replaceState(null,'',location.pathname);render();}if(button.dataset.mode){mode=button.dataset.mode;setOnly('common','all');activePost=null;await load();}if(button.dataset.platform){platform=button.dataset.platform;render();}if(button.dataset.preset){setOnly('common',button.dataset.preset);render();}if(button.hasAttribute('data-tag')){setOnly('tag',button.dataset.tag);render();}if(button.hasAttribute('data-direction')){setOnly('direction',button.dataset.direction);render();}if(button.dataset.detail)showDetail(Number(button.dataset.detail));}catch(error){toast(error.message);}});
$('addForm').onsubmit=async event=>{event.preventDefault();try{const result=await api('/api/keyword',{name:$('keywordInput').value});selectedKeyword=result.id;contentQuery='';$('keywordInput').value='';$('addDialog').close();await load();toast('关键词已保存');}catch(error){toast(error.message);}};
$('settingsForm').onsubmit=async event=>{event.preventDefault();try{const key=$('apiKey').value.trim();if(!key)throw new Error('请填写密钥，或点击清除密钥');await api('/api/connect',{key});$('apiKey').value='';$('settingsDialog').close();toast('已保存；接口调用受额度设置限制。');}catch(error){toast(error.message);}};
$('disconnect').onclick=async()=>{try{await api('/api/connect',{key:''});$('apiKey').value='';$('settingsDialog').close();toast('已清除密钥');}catch(error){toast(error.message);}};
$('scanButton').onclick=()=>location.href='/tools?open=import';$('emptyAction').onclick=()=>basePosts().length?resetFilters():location.href='/tools?open=import';
for(const id of ['timeFilter','playFilter','sortOrder'])$(id).onchange=render;
$('resetFilters').onclick=resetFilters;$('clearContentQuery').onclick=()=>{contentQuery='';$('searchKeywordInput').value='';params.delete('q');params.delete('post');history.replaceState(null,'',location.pathname);render();};
$('searchKeywordInput').value=contentQuery;
$('keywordSearchForm').onsubmit=event=>{event.preventDefault();const keyword=$('searchKeywordInput').value.trim(),id=$('keywordEndpoint').value;if(!keyword||!id){toast('请填写关键词并选择接口');return;}location.href='/market?id='+encodeURIComponent(id)+'&keyword='+encodeURIComponent(keyword)+'&collect=1';};
api('/api/catalog').then(model=>{const rows=model.items.filter(r=>r.platform==='douyin'&&/fetch_video_search_result|fetch_video_search_v\d|search_video$/.test(r.path));$('keywordEndpoint').innerHTML=rows.map(r=>`<option value="${esc(r.id)}" ${r.execution_reason?'disabled':''}>${esc(r.path.replace('/api/v1/douyin/',''))} · $${esc(r.price??'?')}${r.legacy_documentation?' · 历史接口':''}${r.execution_reason?' · '+esc(r.execution_reason):''}</option>`).join('');}).catch(error=>$('keywordSearchStatus').textContent=error.message);
$('searchLocal').onclick=()=>{const keyword=$('searchKeywordInput').value.trim();if(!keyword){toast('请输入关键词');return;}resetFilters();contentQuery=keyword;$('searchKeywordInput').value=keyword;params.set('q',keyword);history.replaceState(null,'',location.pathname+'?'+params.toString());render();toast('已搜索本地内容；没有发起平台采集');};
let clearExpectedCount=0,clearMode='live';
function renderClearControls(){const last=data.last_clear;$('undoClear').hidden=!last;$('clearUndoNote').hidden=!last;if(last)$('undoClear').textContent=`撤销清空${last.kind==='videos'?'视频':'关键词'}（${last.count}）`;}
function showClearScope(){const videos=$('clearKind').value==='videos';clearExpectedCount=videos?data.posts.length:data.keywords.length;$('clearScope').textContent=videos?`将清空${clearMode==='demo'?'演示模式':'本地真实记录模式'}的全部 ${clearExpectedCount} 条视频，保留关键词和另一模式的视频。`:`将清空全部 ${clearExpectedCount} 个监测关键词（两个模式共用），保留全部视频；之后可在“全部内容”查看视频。`;$('confirmClearList').textContent=`确认清空 ${clearExpectedCount} ${videos?'条视频':'个关键词'}`;$('confirmClearList').disabled=clearExpectedCount===0;$('clearListError').textContent=clearExpectedCount?'':'当前所选列表已经为空。';}
$('openClearLists').onclick=async()=>{try{await load();clearMode=mode;$('clearKind').value='videos';showClearScope();$('clearListsDialog').showModal();}catch(error){toast(error.message);}};
$('clearKind').onchange=showClearScope;
$('confirmClearList').onclick=async()=>{const button=$('confirmClearList');button.disabled=true;try{const kind=$('clearKind').value,result=await api('/api/clear-list',{kind,mode:clearMode,count:clearExpectedCount});$('clearListsDialog').close();resetFilters();await load();toast(`已清空 ${result.count} ${kind==='videos'?'条视频':'个关键词'}，可撤销恢复。`);}catch(error){$('clearListError').textContent=error.message;button.disabled=false;}};
$('undoClear').onclick=async()=>{if(!data.last_clear)return;const button=$('undoClear');button.disabled=true;try{const result=await api('/api/undo-clear',{id:data.last_clear.id});await load();toast(`已恢复 ${result.count} ${result.kind==='videos'?'条视频':'个关键词'}。`);}catch(error){toast(error.message);}finally{button.disabled=false;}};
$('aiSettingsButton').onclick=async()=>{try{
  const config=await api('/api/ai/config');$('aiEndpoint').value=config.endpoint;$('aiModel').value=config.model;$('aiKey').value='';
  $('aiKey').placeholder=config.connected?'本次运行已配置；留空保留':'填写模型服务的密钥';
  $('aiKeyStatus').textContent=config.connected?'模型密钥已配置；更换服务地址会清除原密钥。':'尚未配置密钥；本机免密模型可留空。';
  $('aiClearKey').disabled=!config.connected;$('aiSettingsError').textContent='';$('aiSettingsDialog').showModal();
}catch(error){toast(error.message);}};
$('aiSettingsDialog').addEventListener('close',()=>{$('aiKey').value='';});
async function saveAI(clearKey=false){
  const body={endpoint:$('aiEndpoint').value.trim(),model:$('aiModel').value.trim(),clear_key:clearKey};
  const key=$('aiKey').value.trim();if(key&&!clearKey)body.key=key;
  await api('/api/ai/config',body);$('aiKey').value='';$('aiSettingsDialog').close();directionState.scope='';render();toast(clearKey?'已清除模型密钥':'AI 配置已保存，未发起模型请求');
}
$('aiSettingsForm').onsubmit=async event=>{event.preventDefault();try{await saveAI();}catch(error){$('aiSettingsError').textContent=error.message;}};
$('aiClearKey').onclick=async()=>{try{await saveAI(true);}catch(error){$('aiSettingsError').textContent=error.message;}};
$('generateDirections').onclick=async()=>{try{
  const posts=baselinePosts(),scope={mode,ids:posts.map(p=>p.id)},preview=await api('/api/ai/cache',scope);
  if(!preview.config.endpoint||!preview.config.model||!preview.config.connected&&!preview.config.local){toast('请先在 AI 模型设置中填写地址、模型名和密钥');$('aiSettingsButton').click();return;}
  generationDraft={...scope,fingerprint:preview.fingerprint,force:preview.cached,confirmed:true};
  $('aiGenerateScope').textContent=`将为 ${preview.count} 条${mode==='demo'?'演示':'本地'}作品${preview.cached?'重新生成':'生成'}分类。模型：${preview.config.model}；地址：${preview.config.endpoint}`;
  $('aiGenerateError').textContent='';$('aiConfirmGenerate').disabled=false;$('aiGenerateDialog').showModal();
}catch(error){toast(error.message);}};
$('aiConfirmGenerate').onclick=async()=>{
  if(aiBusy||!generationDraft)return;aiBusy=true;$('aiConfirmGenerate').disabled=true;render();
  try{await api('/api/ai/generate',generationDraft);$('aiGenerateDialog').close();directionState.scope='';render();toast('AI 分类已生成并保存在本机');}
  catch(error){$('aiGenerateError').textContent=error.message;toast(error.message);}
  finally{aiBusy=false;$('aiConfirmGenerate').disabled=false;render();}
};
RadarIcons.fill();load().catch(error=>{$('empty').hidden=false;$('emptyMessage').textContent=error.message;$('resultCount').textContent='读取失败';});
