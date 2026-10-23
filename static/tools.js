const tools = [
  {id:'script',name:'脚本准备',icon:'file-text',tone:'blue',description:'用雷达已收录作品和商品事实生成可审阅脚本，带事实引用和运行记录。测试模式不调用模型。',status:'local',label:'本地 + 可选模型'},
  {id:'creative',name:'视频分析与改编',icon:'circle-play',tone:'blue',description:'上传参考视频，按固定规则分析，生成真人拍摄稿、AI视频提示词和视频写稿提示词。需配置图片模型，可能计费。',status:'ai',label:'自配模型'},
  {id:'video',name:'视频数据分析',icon:'eye',tone:'blue',description:'查看本地视频的播放量、点赞和互动数据。支持CSV导出及视频JSON导入、导出。',status:'local',label:'本地免费'},
  {id:'creator',name:'创作者分析',icon:'user',tone:'orange',description:'按平台和作者名称汇总本地视频样本，比较已知播放量与点赞，支持CSV导出。',status:'local',label:'本地免费'},
  {id:'comments',name:'评论分析',icon:'comment',tone:'green',description:'粘贴评论或导入TXT、JSON，统计高频词和重复文本。只在浏览器本地处理。',status:'local',label:'本地免费'},
  {id:'download',name:'视频下载',icon:'download',tone:'indigo',description:'采集直链自动保存，支持手动导入和批量下载。缺少直链时，可确认费用后获取抖音直链并下载。',status:'local',label:'已有直链免费 / 可选付费解析'},
  {id:'voice',name:'AI 声音克隆',icon:'mic',tone:'purple',description:'本期未接入语音模型或外部服务，暂不提供声音克隆。',status:'pending',label:'本期暂缓'},
  {id:'fraud',name:'刷量检测',icon:'shield',tone:'red',description:'本期没有足够的历史数据及验证依据，暂不提供刷量判定。',status:'pending',label:'本期暂缓'},
  {id:'extension',name:'浏览器采集',icon:'browser',tone:'blue',description:'此版本采用TikHub接口获取内容，浏览器手动采集入口已停用。',status:'pending',label:'未启用'}
];
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $=id=>document.getElementById(id);
const num=value=>value===null||value===undefined?'未知':Number(value).toLocaleString('zh-CN');
let localState={posts:[],keywords:[],token:''}, exportRows=[], exportName='', commentResult=null, commentEvidence=[];
$('featureTools').innerHTML=tools.map(tool=>`<article class="feature-tool ${tool.status==='pending'?'is-pending':''}"><div class="feature-tool-top"><span class="feature-tool-icon tool-${tool.tone}">${RadarIcons.svg(tool.icon)}</span><span class="tool-arrow" aria-hidden="true">${tool.status==='pending'?'':'↗'}</span></div><h2>${tool.name}</h2><p>${tool.description}</p><div class="feature-tool-bottom"><span class="tool-tag ${tool.status!=='pending'?'available':'pending'}">${tool.label}</span><button data-tool="${tool.id}" ${tool.status==='pending'?'disabled':''}>${tool.status!=='pending'?'打开工具 →':'暂不可用'}</button></div></article>`).join('');
function notice(message){$('toolsError').textContent=message;$('toolsError').hidden=false;}
async function readState(){const response=await fetch('/api/state?mode=live');if(!response.ok)throw new Error('本地视频数据读取失败');localState=await response.json();return localState;}
async function post(path,body){const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Radar-Token':localState.token},body:JSON.stringify(body)});const result=await response.json();if(!response.ok)throw new Error(result.error||'操作失败');return result;}
function saveFile(name,text,type){const url=URL.createObjectURL(new Blob([text],{type}));const link=document.createElement('a');link.href=url;link.download=name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);}
function safeVideoLink(post){try{const url=new URL(post.url);if(url.protocol==='https:'&&['www.douyin.com','www.xiaohongshu.com'].includes(url.hostname))return `<a href="${esc(url.href)}" target="_blank" rel="noopener noreferrer">${esc(post.title)}</a>`;}catch{}return esc(post.title);}
function stats(items){$('analysisStats').innerHTML=items.map(([value,label])=>`<div><strong>${num(value)}</strong><span>${label}</span></div>`).join('');}
function table(headers,rows){$('analysisResult').innerHTML=rows.length?`<table class="analysis-table"><thead><tr>${headers.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.join('')}</tbody></table>`:'<p class="analysis-empty">还没有视频数据，可导入本地视频JSON。</p>';}
async function analyze(id,open=true){
  const data=await readState(),posts=data.posts,known=posts.filter(p=>p.plays!==null&&p.plays!==undefined);
  $('exportVideoJSON').hidden=id!=='video';$('openVideoImport').hidden=id!=='video';
  if(id==='video'){
    $('analysisTitle').textContent='视频数据分析';$('analysisNote').textContent='展示已收录及本地导入的视频快照，未知字段不补零。播放量不是近期增速或成交量；导出不发起网络采集。';
    stats([[posts.length,'已收录视频'],[known.length,'播放量已知'],[known.length?Math.max(...known.map(p=>p.plays)):null,'样本最高播放量']]);
    const sorted=[...posts].sort((a,b)=>(b.plays??-1)-(a.plays??-1));
    table(['视频','作者','播放量','点赞','评论','来源'],sorted.map(p=>`<tr><td class="video-title">${safeVideoLink(p)}</td><td>${esc(p.author)}</td><td class="number">${num(p.plays)}</td><td class="number">${num(p.likes)}</td><td class="number">${num(p.comments)}</td><td>${esc(p.source||'历史缓存')}</td></tr>`));
    exportRows=[['平台','作品ID','标题','作者','播放量','点赞','评论','原视频','来源'],...sorted.map(p=>[p.platform,p.external_id,p.title,p.author,p.plays,p.likes,p.comments,p.url,p.source])];exportName='videos';
  }else{
    $('analysisTitle').textContent='创作者分析';$('analysisNote').textContent='按“平台 + 作者名称”汇总本地样本；同名可能合并，不代表完整账号档案。只合计已知字段，不提供历史增长分析。';
    const groups=FreeToolsData.creators(posts);stats([[groups.length,'样本作者名称'],[posts.length,'已收录视频'],[known.length,'播放量已知的视频']]);
    table(['平台','作者名称','样本作品数','已知播放量合计','已知点赞合计'],groups.map(g=>`<tr><td>${g.platform==='dy'?'抖音':'小红书'}</td><td>${esc(g.name)}</td><td>${num(g.count)}</td><td class="number">${num(g.plays)}</td><td class="number">${num(g.likes)}</td></tr>`));
    exportRows=[['平台','作者名称','样本作品数','已知播放量合计','已知点赞合计'],...groups.map(g=>[g.platform,g.name,g.count,g.plays,g.likes])];exportName='creators';
  }
  $('exportAnalysis').disabled=posts.length===0;$('exportVideoJSON').disabled=posts.length===0;if(open)$('analysisDialog').showModal();
}
let downloadPosts=[],downloadResolver=null,downloadBusy=false,downloadLoadSeq=0;
const resolverId='GET /api/v1/douyin/app/v3/fetch_video_high_quality_play_url';
function selectedDownloads(){const ids=new Set([...$('downloadVideoSelect').selectedOptions].map(o=>Number(o.value)));return downloadPosts.filter(p=>ids.has(p.id));}
function updateDownloadActions(){
  const selected=selectedDownloads();
  $('startDownload').disabled=downloadBusy||!selected.some(p=>p.video_url);
  $('resolveDownload').disabled=downloadBusy||!selected.length||!downloadResolver?.ready||selected.some(p=>p.platform!=='dy'||!/^\d{1,30}$/.test(p.external_id));
  $('resolveDownload').textContent=`获取直链并下载 · $${downloadResolver?.price??'?'} / 条`;
  $('downloadVideoSelect').disabled=downloadBusy;$('refreshDownloads').disabled=downloadBusy;
  $('downloadDialog').querySelector('[data-close-tool]').disabled=downloadBusy;
}
async function openDownloads(){
  if(downloadBusy)return;
  const seq=++downloadLoadSeq;
  $('downloadStatus').textContent='正在读取本地视频…';$('startDownload').disabled=true;$('resolveDownload').disabled=true;
  if(!$('downloadDialog').open)$('downloadDialog').showModal();
  try{
    const [state,catalogResponse]=await Promise.all([fetch('/api/state?mode=live').then(async r=>{if(!r.ok)throw new Error('本地视频读取失败');return r.json();}),fetch('/api/catalog')]);
    const catalog=catalogResponse.ok?await catalogResponse.json():null;
    if(seq!==downloadLoadSeq)return;
    const selected=new Set([...$('downloadVideoSelect').selectedOptions].map(o=>Number(o.value)));
    localState=state;downloadPosts=state.posts;
    const item=catalog?.items.find(row=>row.id===resolverId);
    const reason=item?.execution_reason||(!catalog?.tools[resolverId]?.enabled?'请先启用直链解析接口':!catalog?.connected?'请先配置 TikHub API Key':!catalog?.access?.active?'请先开启接口调用并设置预算':'');
    downloadResolver=item?{price:item.price,ready:!reason}:null;
    $('downloadResolverSettings').hidden=!item;
    $('downloadResolverNote').textContent=item?`额外解析目录标价 $${item.price} / 条。${reason||'接口已就绪；只有点击并确认费用后才执行。'}`:'此版本不提供额外解析；可使用已有直链或手动导入。';
    $('downloadVideoSelect').innerHTML=downloadPosts.map(p=>`<option value="${p.id}" ${selected.has(p.id)?'selected':''}>${esc(p.title.slice(0,65))} · ${p.video_url?'已有直链':'缺少直链'}${p.platform==='dy'?' · 抖音':' · 小红书'}</option>`).join('');
    if(!selectedDownloads().length&&downloadPosts.length)$('downloadVideoSelect').value=String((downloadPosts.find(p=>p.video_url)||downloadPosts[0]).id);
    $('downloadStatus').textContent=downloadPosts.length?`共 ${downloadPosts.length} 条，其中 ${downloadPosts.filter(p=>p.video_url).length} 条已有直链。可多选；单批最多20条。`:'暂无视频。先采集视频，或用“手动导入视频JSON”。';
    updateDownloadActions();
  }catch(error){if(seq===downloadLoadSeq){downloadResolver=null;$('downloadStatus').textContent=error.message;}}
}
$('featureTools').onclick=async event=>{const button=event.target.closest('[data-tool]');if(!button||button.disabled)return;button.disabled=true;$('toolsError').hidden=true;try{const id=button.dataset.tool;if(id==='script'){location.href='/script';return;}if(id==='creative'){location.href='/creative';return;}if(id==='comments')$('commentsDialog').showModal();else if(id==='download')await openDownloads();else await analyze(id);}catch(error){notice(error.message);}finally{button.disabled=false;}};
$('painEvidence').onchange=()=>{
  const index=$('painEvidence').value;
  const row=index!==''&&commentEvidence?commentEvidence[Number(index)]:null;
  if(row&&!$('painInput').value.trim())$('painInput').value=row.text;
  $('painInput').placeholder=row?'已选评论证据；可编辑归纳后保存。':'没有选择评论证据时，将按“用户观察”保存。';
};
$('savePain').onclick=async()=>{
  const value=$('painInput').value.trim();
  if(!value){$('painStatus').textContent='请先填写痛点线索';return;}
  const index=$('painEvidence').value;
  const row=index!==''&&commentEvidence?commentEvidence[Number(index)]:null;
  try{
    await readState();
    const data=await post('/api/pain/save',{
      pain:value,
      source:row?'comment':'user_observation',
      evidence_role:row?'comment_evidence':'user_observation',
      evidence:row?row.text:'',
      frequency:row?row.count:1,
    });
    $('painStatus').textContent='已保存痛点线索 #'+data.id+(row?'（附评论原摘录）':'（用户观察，无评论证据）')+'，可在脚本页选用。';
  }catch(error){$('painStatus').textContent=error.message;}
};
$('closeAnalysis').onclick=()=>$('analysisDialog').close();
$('exportAnalysis').onclick=()=>saveFile(exportName+'.csv',FreeToolsData.csv(exportRows),'text/csv;charset=utf-8');
$('exportVideoJSON').onclick=()=>{const posts=localState.posts.map(p=>Object.fromEntries(['platform','external_id','title','author','plays','likes','saves','comments','followers','duration','published_at','url','video_url'].map(key=>[key,p[key]??null])));saveFile('videos.json',JSON.stringify({posts},null,2),'application/json;charset=utf-8');};
$('openVideoImport').onclick=()=>$('videoImportDialog').showModal();
async function readFile(file){if(!file)return '';if(file.size>2000000)throw new Error('文件最多2MB');return file.text();}
$('commentFile').onchange=async event=>{try{$('commentInput').value=await readFile(event.target.files[0]);commentResult=null;commentEvidence=[];$('painEvidence').innerHTML='<option value="">不选择（按“用户观察”保存）</option>';$('commentResults').hidden=true;$('exportComments').disabled=true;$('commentStatus').textContent='已读取文件；点击开始分析。';}catch(error){$('commentStatus').textContent=error.message;}finally{event.target.value='';}};
$('analyzeComments').onclick=()=>{try{const comments=FreeToolsData.parseComments($('commentInput').value);if(!comments.length)throw new Error('请先粘贴或导入评论');commentResult=FreeToolsData.analyzeComments(comments);const result=commentResult;$('commentStats').innerHTML=[[result.total,'评论条数'],[result.unique,'不同文本'],[result.repeated,'重复的额外条数']].map(([value,label])=>`<div><strong>${value}</strong><span>${label}</span></div>`).join('');$('wordResults').innerHTML=result.words.length?result.words.map(w=>`<span class="word-token">${esc(w.word)}<b>${w.count}</b></span>`).join(''):'<p class="analysis-note">没有可统计的词语。</p>';$('duplicateResults').innerHTML=result.duplicates.length?result.duplicates.map(row=>`<div class="duplicate-row"><p>${esc(row.text)}</p><strong>${row.count}次</strong></div>`).join(''):'<p class="analysis-note">没有发现重复文本。</p>';commentEvidence=FreeToolsData.dedupComments(comments);$('painEvidence').innerHTML='<option value="">不选择（按“用户观察”保存）</option>'+commentEvidence.map((row,index)=>`<option value="${index}">${esc(row.text.slice(0,60))}（${row.count}次）</option>`).join('');$('commentResults').hidden=false;$('exportComments').disabled=false;$('commentStatus').textContent='分析完成。高频词为规则分词统计，重复文本不代表刷量。';}catch(error){commentResult=null;$('commentResults').hidden=true;$('exportComments').disabled=true;$('commentStatus').textContent=error.message;}};
$('commentInput').oninput=()=>{commentResult=null;commentEvidence=[];$('painEvidence').innerHTML='<option value="">不选择（按“用户观察”保存）</option>';$('commentResults').hidden=true;$('exportComments').disabled=true;$('commentStatus').textContent='文本已改变，请重新分析。';};
$('exportComments').onclick=()=>{if(commentResult)saveFile('comments-analysis.json',JSON.stringify(commentResult,null,2),'application/json;charset=utf-8');};
$('videoJSONFile').onchange=async event=>{try{$('videoJSONInput').value=await readFile(event.target.files[0]);$('videoImportStatus').textContent='已读取文件，确认后导入。';}catch(error){$('videoImportStatus').textContent=error.message;}finally{event.target.value='';}};
$('importVideoJSON').onclick=async()=>{const button=$('importVideoJSON');button.disabled=true;try{const input=$('videoJSONInput').value;if(input.length>1000000)throw new Error('JSON文本最多100万字符');let payload;try{payload=JSON.parse(input);}catch{throw new Error('视频JSON格式不正确');}const posts=Array.isArray(payload)?payload:payload.posts;await readState();const result=await post('/api/import',{keyword:$('importKeyword').value,posts});$('videoImportStatus').textContent=`已导入 ${result.count} 条，跳过已有作品 ${result.skipped} 条。`;if($('analysisDialog').open)await analyze('video',false);}catch(error){$('videoImportStatus').textContent=error.message;}finally{button.disabled=false;}};
async function downloadSelected(resolve=false){
  if(downloadBusy)return;
  const jobs=selectedDownloads().map(p=>({...p})),cost=downloadResolver?.price;
  if(!jobs.length||jobs.length>20){$('downloadStatus').textContent='请选择1～20条视频。';return;}
  if(resolve){
    if(!downloadResolver?.ready||jobs.some(p=>p.platform!=='dy'||!/^\d{1,30}$/.test(p.external_id))){$('downloadStatus').textContent='请先配置解析接口；额外解析仅支持抖音视频。';return;}
    const total=(Number(cost)*jobs.length).toFixed(4);
    if(!confirm(`将为所选 ${jobs.length} 条抖音视频逐条重新获取直链并下载。接口标价 $${cost} / 条，合计最多 $${total}，计入累计预算；可能使用充值余额。失败不重试，任一项失败后停止余下解析。继续？`))return;
  }
  downloadBusy=true;updateDownloadActions();$('downloadResult').hidden=true;$('downloadItems').replaceChildren();
  let done=0,failed=0,skipped=0,stop=false;
  try{
    for(const [index,job] of jobs.entries()){
      const row=document.createElement('li');row.textContent=job.title+'：等待中';$('downloadItems').append(row);
      if(stop||(!resolve&&!job.video_url)){row.textContent=job.title+(stop?'：未执行，前一项失败后已停止':'：跳过，缺少直链；可单独获取直链后下载');skipped++;continue;}
      row.textContent=job.title+(resolve?'：正在获取直链并下载…':'：正在下载已有直链…');
      $('downloadStatus').textContent=`正在处理 ${index+1}/${jobs.length}；请等待完成。`;
      try{
        const result=await post('/api/download',{id:job.id,...(resolve?{resolve:true,confirmed_cost:cost}:{})});
        row.textContent=`${job.title}：已保存 ${result.directory}\\${result.filename} · ${(result.bytes/1048576).toFixed(2)} MB `;
        const link=document.createElement('a');link.href=result.url;link.download=result.filename;link.textContent='另存一份';row.append(link);done++;
        if(resolve){const state=await fetch('/api/state?mode=live').then(r=>r.ok?r.json():null).catch(()=>null);if(state){localState=state;downloadPosts=state.posts;}}
      }catch(error){row.textContent=job.title+'：'+error.message;failed++;if(resolve)stop=true;}
    }
    $('downloadStatus').textContent=`处理完成：成功 ${done}，失败 ${failed}，跳过 ${skipped}。文件保存在程序目录的 downloads 文件夹；不会自动重试或自动付费解析。`;
  }finally{downloadBusy=false;updateDownloadActions();}
}
$('startDownload').onclick=()=>downloadSelected();
$('resolveDownload').onclick=()=>downloadSelected(true);
$('downloadVideoSelect').onchange=updateDownloadActions;
$('refreshDownloads').onclick=openDownloads;
$('downloadDialog').addEventListener('cancel',event=>{if(downloadBusy)event.preventDefault();else downloadLoadSeq++;});
$('downloadDialog').addEventListener('close',()=>{downloadLoadSeq++;});
$('downloadImport').onclick=()=>$('videoImportDialog').showModal();
document.querySelectorAll('[data-close-tool]').forEach(button=>button.onclick=()=>button.closest('dialog').close());

if(new URLSearchParams(location.search).get('open')==='import')$('videoImportDialog').showModal();

const initialTool=new URLSearchParams(location.search).get('tool');if(tools.some(t=>t.id===initialTool&&t.status!=='pending'))document.querySelector('[data-tool="'+initialTool+'"]').click();
