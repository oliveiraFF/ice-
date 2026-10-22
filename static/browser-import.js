let capture;
const el=id=>document.getElementById(id),escape=SiteUI.escape;
try{
  const fragment=location.hash.slice(1);history.replaceState(null,'',location.pathname);
  if(!fragment||fragment.length>800000)throw new Error('没有有效的采集数据。请从Chrome抖音搜索结果页点击采集助手进入。');
  const bytes=Uint8Array.from(atob(fragment),c=>c.charCodeAt(0));capture=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));
  if(capture.version!==1||typeof capture.keyword!=='string'||!capture.keyword.trim()||capture.keyword.length>40||!Array.isArray(capture.posts)||!capture.posts.length||capture.posts.length>20||capture.posts.some(p=>!p||p.platform!=='dy'||!/^\d+$/.test(p.external_id)))throw new Error('采集数据格式不正确，请回到抖音搜索页重新采集。');
  el('captureSummary').textContent=`关键词“${capture.keyword}” · 待确认 ${capture.posts.length} 条 · 只读网页快照，未经独立核验`;
  el('captureRows').innerHTML=capture.posts.map(p=>`<article class="capture-row"><div><h2>${escape(p.title||'无标题视频')}</h2><p>${escape(p.author||'未知作者')} · 作品ID ${escape(p.external_id)}</p></div><span>播放量 <strong>${typeof p.plays==='number'?escape(p.plays.toLocaleString('zh-CN')):'未知'}</strong></span></article>`).join('');
  el('capturePreview').hidden=false;
}catch(error){capture=null;el('captureError').textContent=error.message;el('captureError').hidden=false;}
el('confirmCapture').onclick=async()=>{
  if(!capture)return;const button=el('confirmCapture');button.disabled=true;
  try{
    const response=await fetch('/api/state?mode=live');if(!response.ok)throw new Error('本地服务读取失败');const state=await response.json();
    const saved=await fetch('/api/browser-import',{method:'POST',headers:{'Content-Type':'application/json','X-Radar-Token':state.token},body:JSON.stringify(capture)}),result=await saved.json();if(!saved.ok)throw new Error(result.error||'收录失败');
    el('captureResult').textContent=`已收录 ${result.count} 条新视频，跳过 ${result.skipped} 条已有视频，并关联本次关键词。`;
    const link=document.createElement('a');link.href='/?keyword='+result.keyword_id;link.textContent='查看该关键词的视频 ↗';el('captureResult').append(document.createElement('br'),link);button.textContent='已确认收录';
  }catch(error){el('captureResult').textContent=error.message;button.disabled=false;}
};
