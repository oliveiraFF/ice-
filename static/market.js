const $ = id => document.getElementById(id);
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const PAGE_SIZE = 24;
let model={items:[],tools:{},token:'',connected:false}, page=1, type='', credit='', discount='', platform='', feature='', detail=null, busy=false, toastTimer;
const platformNames = {bilibili:'Bilibili',demo:'Demo',douyin:'Douyin',hybrid:'Hybrid',instagram:'Instagram',kuaishou:'Kuaishou',lemon8:'Lemon8',linkedin:'LinkedIn',pipixia:'Pipixia',reddit:'Reddit',telegram:'Telegram',threads:'Threads',tikhub:'TikHub',tiktok:'TikTok',toutiao:'Toutiao',twitter:'X / Twitter',wechat_channels:'WeChat Channels',wechat_mp:'WeChat MP',wechat_search:'WeChat Search',weibo:'Weibo',xiaohongshu:'Xiaohongshu',xigua:'Xigua',youtube:'YouTube',zhihu:'Zhihu',captcha:'Captcha',health:'Health',ios_shortcut:'iOS Shortcut',net_ease_cloud_music:'NetEase Music',sora2:'Sora 2'};
const featureIcons = ['comment','download','users','hash','mouse-pointer-click','heart','radio','play','file-text','search','shopping-bag','trending-up','user','file-text','wrench','ellipsis'];
function platformBadge(id){return `<span class="api-platform-icon ${esc(id)}" aria-hidden="true">${RadarIcons.platform(id)}</span>`;}
const timeText = at => at ? new Date(at*1000).toLocaleString('zh-CN',{timeZone:'America/Los_Angeles',hour12:false}) : '尚未测试';
const moneyText = value => value === null || value === undefined ? '未知' : '$'+(Number(value)===0?'0.0000':value);
function toast(message){clearTimeout(toastTimer);$('marketToast').textContent=message;$('marketToast').hidden=false;toastTimer=setTimeout(()=>$('marketToast').hidden=true,6000);}
async function api(path,body){const response=await fetch(path,body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Radar-Token':model.token},body:JSON.stringify(body)});const value=await response.json();if(!response.ok)throw new Error(value.error||'请求失败');return value;}
function methodBadge(row){return `<span class="api-method ${esc(row.method.toLowerCase())}">${row.method==='UNKNOWN'?'待核实':esc(row.method)}</span>`;}
function feeBadges(row){return `${row.price==='0'?'<span class="api-badge free">$0 零费用</span>':''}<span class="api-badge ${row.free_credit?'credit':''}">${row.free_credit?RadarIcons.svg('gift')+'赠送额度':'⊗ 无赠送额度'}</span><span class="api-badge ${row.discount?'discount':''}">${row.discount?RadarIcons.svg('percent')+'折扣':'⊗ 无折扣'}</span><span class="api-badge" title="已验证响应仅指最近请求成功，不代表视频已收录或分析完成">${esc(row.availability_label||'待验证')}</span>${!row.documented?'<span class="api-badge">文档待补充</span>':''}`;}
async function load(){model=await api('/api/catalog');render();if(detail)refreshDetail();}
function filtered(){
  return model.items.filter(row=>MarketData.matches(row,{q:$('apiSearch').value.trim(),platform,feature,type,credit,discount,method:$('methodFilter').value,cost:$('priceFilter').value,managed:$('managedFilter').checked},model.tools));
}
function render(){
  const count=model.items.length, zero=model.items.filter(r=>r.price==='0').length, managed=Object.keys(model.tools).length;
  $('marketNav').classList.add('active');
  $('totalCount').textContent=count.toLocaleString();$('freeCount').textContent=zero;$('managedCount').textContent=managed;
  $('importTime').textContent='目录快照 · '+timeText(model.imported_at);
  const access=model.access||{};
  $('iceKeyState').textContent=model.credential_error?'本机密钥恢复失败，请重新配置':model.connected?(model.credential_remembered?'已配置 · 当前系统账户加密保存':'已配置 · 本次运行可用'):'未配置 · 可手动添加';
  $('accessStatus').textContent=access.active?(access.allow_balance?'接口调用已开启 · 允许充值余额':'接口调用已开启 · 仅赠送额度'):access.enabled?'接口调用已停止 · 预算不足或已到期':'接口调用已关闭';
  $('creditTotals').textContent=`赠送余额 ${moneyText(access.free_credit)} · 充值余额 ${moneyText(access.balance)} · 查询于 ${timeText(access.checked_at)}`;
  $('budgetTotals').textContent=`累计预算 ${moneyText(access.limit)} · 已预留 ${moneyText(access.spent)} · 剩余 ${moneyText(access.remaining)} · ${access.expires_at?'到期 '+timeText(access.expires_at):'未设置到期时间'}`;
  if(!$('platformChips').children.length){
    const platforms=[...new Set(model.items.map(r=>r.platform))].sort((a,b)=>(platformNames[a]||a).localeCompare(platformNames[b]||b));
    $('platformChips').innerHTML=`<button data-platform="" class="filter-chip"><span class="all-icon">${RadarIcons.svg('layers')}</span>全部</button>`+platforms.map(id=>`<button class="filter-chip" data-platform="${esc(id)}" title="${esc(model.items.find(r=>r.platform===id).platform_name)}">${platformBadge(id)}${esc(platformNames[id]||id)}</button>`).join('');
    $('featureChips').innerHTML=`<button data-feature="" class="filter-chip"><span class="all-icon">${RadarIcons.svg('layers')}</span>全部</button>`+MarketData.features.map((name,i)=>`<button class="filter-chip" data-feature="${name}"><span class="feature-icon tone-${i%6}" aria-hidden="true">${RadarIcons.svg(featureIcons[i])}</span>${name}</button>`).join('');
  }
  for(const [key,value] of Object.entries({type,credit,discount,platform,feature})) document.querySelectorAll(`[data-${key}]`).forEach(b=>{const selected=b.dataset[key]===value;b.classList.toggle('selected',selected);b.setAttribute('aria-pressed',selected);});
  const rows=filtered(), pages=Math.max(1,Math.ceil(rows.length/PAGE_SIZE));page=Math.min(page,pages);
  $('apiResultCount').textContent=`找到 ${rows.length.toLocaleString()} 个接口`;
  $('apiGrid').innerHTML=rows.slice((page-1)*PAGE_SIZE,page*PAGE_SIZE).map(row=>{
    const tool=model.tools[row.id], free=row.price==='0';
    const actions=tool?`<button class="toggle-tool" data-toggle="${esc(row.id)}" ${row.execution_reason&&!tool.enabled?'disabled':''}>${tool.enabled?'停用':'启用'}</button><button class="remove-tool" data-remove="${esc(row.id)}">移除</button>`:`<button class="add-tool" data-add="${esc(row.id)}">＋ 添加接口</button>`;
    return `<article class="api-card"><div class="api-card-top">${platformBadge(row.platform)}<span class="api-platform-name">${esc(platformNames[row.platform]||row.platform_name)}</span>${methodBadge(row)}</div><code class="api-path" title="${esc(row.path)}">${esc(row.path.replace('/api/v1',''))}</code><p class="api-name">${esc(row.title)}</p><div class="api-price-row"><span class="api-price ${free?'zero':''}">${moneyText(row.price)}</span>${feeBadges(row)}</div><div class="api-meta"><span>↯ ${esc(row.rate_limit)}</span><span>· ${esc(MarketData.featureOf(row))}</span>${tool?`<span class="tool-state ${tool.enabled?'enabled':''}"><i></i>${tool.enabled?'已启用':'已添加'}</span>`:''}</div><div class="api-card-actions"><button class="detail-button" data-detail="${esc(row.id)}">查看详情 ↗</button>${actions}</div></article>`;
  }).join('');
  $('apiEmpty').hidden=rows.length>0;$('pageLabel').textContent=`${page} / ${pages} 页`;$('prevPage').disabled=page<=1;$('nextPage').disabled=page>=pages;
}
function resetFilters(){type='';credit='';discount='';platform='';feature='';page=1;$('apiSearch').value='';$('methodFilter').value='';$('priceFilter').value='';$('managedFilter').checked=false;render();}
async function manage(id,action){await api('/api/tools',{id,action});await load();toast({add:'已添加，可用“已添加”筛选查看',remove:'已移除，可在API市场重新添加',enable:'接口已启用；尚未执行',disable:'接口已停用'}[action]);}
function isLegacyDouyinSearch(row){return row?.platform==='douyin'&&row.legacy_documentation&&/(?:video|general)_search|search_video$/.test(row.path);}
function refreshDetail(){
  if(!detail)return;const tool=model.tools[detail.id],free=detail.price==='0',reasonNow=model.items.find(row=>row.id===detail.id)?.execution_reason??detail.execution_reason;
  const reason=(isLegacyDouyinSearch(detail)?'该历史搜索地址不在当前官方文档中，已暂停执行；可通过视频分享链接收录单条视频。':'')||reasonNow||(!tool?.enabled?'请先启用接口':(detail.requires_key||!free)&&!model.connected?'请先配置密钥':!free&&!model.access?.active?'请先在市场页面开启额度并设置预算':'');
  $('detailManage').disabled=Boolean(reasonNow&&!tool?.enabled)||busy;
  $('detailManage').textContent=tool?.enabled?'停用接口':reasonNow?'当前不可执行':'启用接口';
  $('runTool').disabled=busy||Boolean(reason);
  $('runTool').textContent=busy?'正在运行…':detail.availability==='unavailable'?'接口不可用 · 已暂停':`手动探针 · ${moneyText(detail.price)}`;
  $('runEligibility').textContent=reason||'执行前再次检查实时价格与额度';
}
async function openDetail(id){
  detail=await api('/api/catalog/detail?id='+encodeURIComponent(id));
  $('detailTitle').textContent=detail.title;$('detailPath').textContent=detail.method+' https://api.tikhub.io'+detail.path;
  $('detailBadges').innerHTML=methodBadge(detail)+feeBadges(detail)+`<span class="api-badge">${esc(detail.platform_name)}</span><span class="api-badge">${moneyText(detail.price)} / 请求</span>`;
  $('officialDocs').href=detail.docs_url;$('officialDocs').hidden=!detail.documented;
  $('detailDescription').textContent=detail.description||'价格目录收录了此接口，但当前公开文档没有相应的请求方法与参数说明。仅展示目录信息，不提供运行。';
  $('parameterSchema').textContent=JSON.stringify(detail.parameters,null,2);$('bodySchema').textContent=detail.body_schema?JSON.stringify(detail.body_schema,null,2):'没有 JSON 请求体';
  $('queryInput').value=JSON.stringify(detail.query||{},null,2);$('bodyInput').value=JSON.stringify(detail.body??{},null,2);$('bodyEditor').hidden=detail.method!=='POST';
  const keyword=new URLSearchParams(location.search).get('keyword');
  if(keyword){const query=JSON.parse($('queryInput').value),body=JSON.parse($('bodyInput').value);if(detail.parameters.some(p=>p.in==='query'&&p.name==='keyword'))query.keyword=keyword;else if(detail.body_schema?.properties?.keyword)body.keyword=keyword;else if(detail.body_schema?.properties?.query)body.query=keyword;$('queryInput').value=JSON.stringify(query,null,2);$('bodyInput').value=JSON.stringify(body,null,2);}
  if(detail.path==='/api/v1/douyin/app/v3/fetch_one_video_by_share_url'&&new URLSearchParams(location.search).get('collect')==='1'){const query=JSON.parse($('queryInput').value);query.share_url='';$('queryInput').value=JSON.stringify(query,null,2);}
  $('legacyNotice').hidden=!detail.legacy_documentation;
  $('legacyNotice').textContent=detail.availability==='unavailable'?detail.execution_reason:'此接口参数来自官方历史SDK，当前服务可用性尚未验证。';
  $('collectionOptions').hidden=!['douyin','xiaohongshu'].includes(detail.platform)||detail.collection_supported===false||detail.availability==='unavailable';
  $('captureHelp').hidden=detail.platform!=='douyin'||!(detail.capture_help||detail.availability==='unavailable');
  $('capturePurpose').textContent=detail.capture_help||detail.execution_reason||'';
  $('captureInputHelp').textContent=detail.input_help||'请手动选择用途对应的当前接口；这里只切换表单，不发起抓取。';
  $('captureRoutes').innerHTML=[['POST /api/v1/douyin/search/fetch_video_search_v2','视频搜索 V2'],['POST /api/v1/douyin/search/fetch_challenge_search_v2','话题搜索 V2'],['GET /api/v1/douyin/app/v3/fetch_one_video_by_share_url','分享链接收录']].map(([id,label])=>`<button type="button" class="secondary compact" data-capture-target="${esc(id)}" ${id===detail.id?'disabled':''}>${label}</button>`).join('');
  $('collectResult').checked=new URLSearchParams(location.search).get('collect')==='1'&&!$('collectionOptions').hidden;
  $('collectionKeyword').value=keyword||'TikHub采集';$('collectionStatus').textContent='';$('viewCollected').hidden=true;renderParameterFields();
  $('toolResponse').textContent=detail.last_result||'尚未执行这个接口，没有测试结果。';
  const tool=model.tools[id];$('runStatus').textContent=tool?.last_at?'上次运行 '+timeText(tool.last_at):'尚未运行';
  refreshDetail();$('apiDialog').showModal();
}
document.addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button)return;
  try{
    if(button.hasAttribute('data-type')){type=button.dataset.type;page=1;render();}
    if(button.hasAttribute('data-credit')){credit=button.dataset.credit;page=1;render();}
    if(button.hasAttribute('data-discount')){discount=button.dataset.discount;page=1;render();}
    if(button.hasAttribute('data-platform')){platform=button.dataset.platform;page=1;render();}
    if(button.hasAttribute('data-feature')){feature=button.dataset.feature;page=1;render();}
    if(button.dataset.detail)await openDetail(button.dataset.detail);
    if(button.dataset.captureTarget)await openDetail(button.dataset.captureTarget);
    if(button.dataset.add)await manage(button.dataset.add,'add');
    if(button.dataset.remove)await manage(button.dataset.remove,'remove');
    if(button.dataset.toggle)await manage(button.dataset.toggle,model.tools[button.dataset.toggle].enabled?'disable':'enable');
  }catch(error){toast(error.message);}
});
$('detailManage').onclick=()=>{if(detail)manage(detail.id,model.tools[detail.id]?.enabled?'disable':'enable').catch(e=>toast(e.message));};
$('runTool').onclick=async()=>{
  if(busy||!detail)return;
  if(isLegacyDouyinSearch(detail)){$('runStatus').textContent='历史搜索接口已暂停，未发出请求。请使用当前接口文档中的地址。';refreshDetail();return;}
  const id=detail.id;let params,body;
  for(const field of document.querySelectorAll('#parameterFields input,#parameterFields select'))if(!field.checkValidity()){field.reportValidity();return;}
  try{params=JSON.parse($('queryInput').value);body=detail.method==='POST'?JSON.parse($('bodyInput').value):null;if(!params||Array.isArray(params)||typeof params!=='object')throw new Error('查询参数必须是 JSON 对象');}catch(error){toast('请检查参数 JSON：'+error.message);return;}
  if(detail.path==='/api/v1/douyin/app/v3/fetch_one_video_by_share_url'&&!String(params.share_url||'').trim()){$('runStatus').textContent='请先在 share_url 中粘贴你的视频分享链接；未发送请求。';return;}
  busy=true;refreshDetail();$('runStatus').textContent='正在核实实时价格并执行一次…';
  try{const result=await api('/api/tools/run',{id,params,body,collect:$('collectResult').checked,keyword:$('collectionKeyword').value.trim()});if(detail?.id===id){$('toolResponse').textContent=result.result;$('runStatus').textContent=(result.ok?'已返回响应 · ':'返回错误 · ')+timeText(result.at)+' · 本次标价 '+moneyText(result.cost)+(result.funding_source==='balance'?' · 充值余额':result.funding_source==='free_credit'?' · 赠送额度':'');$('collectionStatus').textContent=result.ok?(result.collection_message||''):('接口执行失败，未收录视频。实际原因：'+String(result.result||'未返回可识别的错误说明').slice(0,500));$('viewCollected').hidden=!result.keyword_id;if(result.keyword_id)$('viewCollected').href='/?keyword='+result.keyword_id;}await load();}
  catch(error){if(detail?.id===id)$('runStatus').textContent=error.message;toast(error.message);}
  finally{busy=false;refreshDetail();}
};
$('copyEndpoint').onclick=()=>{if(detail)navigator.clipboard.writeText('https://api.tikhub.io'+detail.path).then(()=>toast('接口地址已复制')).catch(()=>toast('浏览器未允许复制，请从上方选择接口地址。'));};
$('closeDetail').onclick=()=>$('apiDialog').close();
$('closeSettings').onclick=()=>$('marketSettings').close();
$('iceKeySettings').onclick=()=>$('siteSettings').click();
$('marketSettingsForm').onsubmit=async event=>{event.preventDefault();const key=$('marketApiKey').value.trim();if(!key){toast('请填写密钥，或点击清除密钥');return;}try{await api('/api/connect',{key});$('marketApiKey').value='';$('marketSettings').close();await load();toast('密钥已配置；没有执行接口测试');}catch(error){toast(error.message);}};
$('clearMarketKey').onclick=async()=>{try{await api('/api/connect',{key:''});$('marketApiKey').value='';$('marketSettings').close();await load();toast('已清除运行及本机加密密钥');}catch(error){toast(error.message);}};
$('apiSearch').oninput=()=>{page=1;render();};
for(const id of ['methodFilter','priceFilter','managedFilter'])$(id).onchange=()=>{page=1;render();};
$('clearFilters').onclick=resetFilters;$('emptyClear').onclick=resetFilters;
$('prevPage').onclick=()=>{page--;render();};$('nextPage').onclick=()=>{page++;render();};
document.addEventListener('keydown',event=>{if(event.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)&&!$('apiDialog').open&&!$('marketSettings').open){event.preventDefault();$('apiSearch').focus();}});
$('apiSearch').value=new URLSearchParams(location.search).get('q')||'';
load().then(()=>{const id=new URLSearchParams(location.search).get('id');if(id)return openDetail(id);}).catch(error=>{$('apiResultCount').textContent='本地目录加载失败：'+error.message;toast(error.message);});

function renderParameterFields(){
  let query,body;try{query=JSON.parse($('queryInput').value);body=JSON.parse($('bodyInput').value);}catch{return;}
  const fields=detail.parameters.filter(p=>p.in==='query').map(p=>({...p,scope:'query'}));
  for(const [name,schema] of Object.entries(detail.body_schema?.properties||{}))fields.push({name,schema,scope:'body',required:detail.body_schema.required?.includes(name),description:schema.description});
  const common=[],advanced=[];
  fields.forEach((p,index)=>{
    const schema=p.schema?.anyOf?.find(s=>s.type!=='null')||p.schema||{},value=(p.scope==='query'?query:body)?.[p.name],text=value===undefined||value===null?'':typeof value==='object'?JSON.stringify(value):String(value);
    const attrs=`data-param-index="${index}" aria-label="参数 ${esc(p.name)}" ${p.required?'required':''}`;
    const control=schema.enum?`<select ${attrs}>${value===undefined?'<option value="">请选择</option>':''}${schema.enum.map((v,i)=>`<option value="${esc(v)}" ${String(v)===text?'selected':''}>${esc(schema['x-enum-labels']?.[i]||v)}</option>`).join('')}</select>`:`<input ${attrs} value="${esc(text)}" type="${['integer','number'].includes(schema.type)?'number':'text'}" ${schema.minimum!==undefined?`min="${esc(schema.minimum)}"`:''} ${schema.type==='number'?'step="any"':''} placeholder="${esc(p.name==='keyword'?'输入你要搜索的关键词':p.example||schema.type||'值')}">`;
    const markup=`<label>${esc(schema['x-ui-label']||p.name)} ${p.required?'<b>必填</b>':'<small>选填</small>'}${control}<small>${esc((schema['x-ui-help']||p.description||'').slice(0,500))}</small></label>`;
    (schema['x-ui-advanced']?advanced:common).push(markup);
  });
  $('parameterFields').innerHTML=common.join('')+(advanced.length?`<details class="parameter-advanced"><summary>更多筛选与分页（选填）</summary><div class="parameter-fields">${advanced.join('')}</div></details>`:'');
  const update=event=>{const index=event.target.dataset.paramIndex;if(index===undefined)return;const p=fields[Number(index)],schema=p.schema?.anyOf?.find(s=>s.type!=='null')||p.schema||{},input=event.target.value,target=p.scope==='query'?'queryInput':'bodyInput';try{const data=JSON.parse($(target).value);if(input===''&&(schema.type!=='string'||schema.enum)&&!p.required)delete data[p.name];else data[p.name]=['integer','number','boolean','array','object'].includes(schema.type)?JSON.parse(input):input;$(target).value=JSON.stringify(data,null,2);event.target.setCustomValidity(p.required&&!input.trim()?'请填写'+(schema['x-ui-label']||p.name):'');}catch{event.target.setCustomValidity('请填写正确的数字、布尔值或JSON');}};
  $('parameterFields').oninput=update;$('parameterFields').onchange=update;
}
$('queryInput').oninput=renderParameterFields;$('bodyInput').oninput=renderParameterFields;
$('refreshCredit').onclick=async()=>{const button=$('refreshCredit');button.disabled=true;try{await api('/api/credit',{});await load();toast('已更新账户余额；未调用内容接口');}catch(error){toast(error.message);}finally{button.disabled=false;}};
$('openAccess').onclick=()=>{const a=model.access||{};$('accessEnabled').checked=Boolean(a.enabled);$('allowBalance').checked=Boolean(a.allow_balance);$('accessLimit').value=a.limit||'0';$('accessDuration').value=a.expires_at?'days':'continuous';$('accessDays').value=a.expires_at?Math.max(1,Math.ceil((a.expires_at-Date.now()/1000)/86400)):1;$('accessDaysLabel').hidden=!a.expires_at;$('accessError').textContent='';$('accessDialog').showModal();};
$('detailAccess').onclick=()=>$('openAccess').onclick();
$('accessDuration').onchange=()=>$('accessDaysLabel').hidden=$('accessDuration').value!=='days';
$('closeAccess').onclick=()=>$('accessDialog').close();
$('accessForm').onsubmit=async event=>{event.preventDefault();try{await api('/api/access',{enabled:$('accessEnabled').checked,allow_balance:$('allowBalance').checked,limit:$('accessLimit').value,days:$('accessDuration').value==='days'?Number($('accessDays').value):null});$('accessDialog').close();await load();toast('额度设置已保存；没有执行内容请求');}catch(error){$('accessError').textContent=error.message;}};
