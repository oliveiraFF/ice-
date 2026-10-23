/* Local video sampling. Only an explicit generation submits media to the configured model. */
const CreativeData=(()=>{
  const names={shooting:'真人拍摄改编稿',video_prompt:'AI 视频生成提示词',writing_prompt:'视频写稿提示词'};
  function sampleTimes(duration){
    if(!Number.isFinite(duration)||duration<=0||duration>180)throw new Error('参考视频需在3分钟以内');
    const end=Math.max(0,duration-.08),times=[0,.8,1.8,3,5,8,...Array.from({length:10},(_,i)=>end*(i+1)/10)];
    return [...new Set(times.filter(t=>t<=end).map(t=>Math.round(t*100)/100))].sort((a,b)=>a-b);
  }
  function clock(seconds){const value=Math.max(0,seconds);return `${String(Math.floor(value/60)).padStart(2,'0')}:${(value%60).toFixed(2).padStart(5,'0')}`;}
  function checkBrief(body){
    for(const [key,label] of [['product','商品名称'],['audience','目标人群'],['facts','真实卖点']])if(!body[key]?.trim())throw new Error('请填写'+label);
    if(!body.outputs.length)throw new Error('请至少选择一类成果');
    if(!Number.isInteger(body.target_seconds)||body.target_seconds<10||body.target_seconds>180)throw new Error('目标时长需为10至180秒整数');
  }
  function provenance(task,dirty){
    if(!task)return '';
    const input={...task.input,frames:task.input.frames.map(f=>({at:f.at}))};
    const snapshot={account_uid:task.account.account_uid,identity_state:task.account.identity_state,
      strategy:task.strategy,media:task.media,source:task.source,input};
    return `# 任务 ${task.task_uid} · 已保存 v${task.version}\n\n${dirty?'当前导出含未保存修改，不属于已保存版本；下面的依据是该版本的输入快照。':'成果与依据来自已保存版本。'}\n\n规则 ${task.rules.version} · ${task.rules.sha256}\n\n人工逐字稿未做时间对齐；采样时间是原视频证据时间，分镜时间是建议安排。\n\n## 已保存的输入与来源快照\n\n\`\`\`json\n${JSON.stringify(snapshot,null,2)}\n\`\`\`\n\n`;
  }
  function sameMedia(task,media){return Boolean(task&&media&&task.media.media_id===media.media_id);}
  return {names,sampleTimes,clock,checkBrief,provenance,sameMedia};
})();
if(typeof module!=='undefined')module.exports=CreativeData;
if(typeof document!=='undefined')(()=>{
  const el=id=>document.getElementById(id),esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let file=null,url='',frames=[],duration=0,busy=false,config=null,token='',result=null,transcriptOrigin='';
  let currentTask=null,savedMedia=null,accountInfo=null,uiBaseline='',tasksEnabled=false;
  const initial=fetch('/api/state?mode=live').then(async r=>{if(!r.ok)throw new Error('本机连接失败，请重新打开页面');const state=await r.json();token=state.token;tasksEnabled=state.agent_tasks_enabled===true;el('creativeTaskTitle').closest('section').hidden=!tasksEnabled;el('saveCreativeInput').hidden=!tasksEnabled;});
  initial.catch(error=>{el('creativeStatus').textContent=error.message;});
  async function request(path,body,headers={}){
    await initial;
    const options=body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-Radar-Token':token,...headers},body:body instanceof Blob?body:JSON.stringify(body)};
    const response=await fetch(path,options),data=await response.json();
    if(!response.ok)throw new Error(data.error||'操作失败');return data;
  }
  function taskReadOnly(){return Boolean(currentTask&&currentTask.version!==currentTask.current_version);}
  function inputKey(body){return JSON.stringify({...body,confirmed:false});}
  function editedResult(){
    if(!result)return null;
    const copy=JSON.parse(JSON.stringify(result));
    for(const key of Object.keys(copy.report.deliverables)){const area=el('creativeText-'+key);if(area)copy.report.deliverables[key]=area.value;}
    return copy;
  }
  function taskScope(){
    const account=currentTask?.account||accountInfo?.account,strategy=currentTask?.strategy||accountInfo?.strategy;
    return `${account?.label||'当前本地账号'} · 平台身份待确认 · 策略 ${strategy?.confirmed?'已确认':'草稿'} v${strategy?.version||0}`;
  }
  function showTask(){
    el('creativeAccountScope').textContent=taskScope();
    const task=currentTask;
    el('creativeTaskVersion').innerHTML=task?task.versions.map(v=>`<option value="${v.version}" ${v.version===task.version?'selected':''}>v${v.version} · ${esc(v.source)}</option>`).join(''):'<option value="">—</option>';
    el('creativeTaskEvidence').textContent=task?`${taskScope()}。规则 ${task.rules.version}（${task.rules.sha256.slice(0,12)}）；台词来源：${{manual:'人工逐字稿',transcription:'外部转写',none:'未提供'}[task.input.transcript_source]||'用户资料'}。视频、采样、输入与成果按版本保留；没有读取其他账号或平台指标。`:'保存后保留账号、策略、规则、原视频、采样画面和台词。保存不调用模型。';
    el('creativeTaskStatus').textContent=task?`任务 ${task.task_uid} · v${task.version}${taskReadOnly()?' · 历史版本只读，请打开最新版本继续。':' · 已保存，可关闭后继续。'}`:'先选择视频并填写资料，可以仅保存输入，稍后继续。';
    const attempt=task?.attempts?.filter(a=>a.input_version<=task.version).at(-1);
    if(attempt&&!taskReadOnly())el('creativeTaskStatus').textContent+=` 最近生成：${{processing:'处理中',success:'成功',validation_failed:'校验失败，待人工处理',result_unconfirmed:'结果未确认',failed:'失败'}[attempt.status]||attempt.status}。${attempt.validation?.error||''}`;
    if(task)history.replaceState(null,'','/creative?task='+task.task_uid+'&version='+task.version);
  }
  async function loadTaskList(){
    const rows=await request('/api/agent/tasks');
    el('creativeTaskChoice').innerHTML='<option value="">选择已保存任务</option>'+rows.map(t=>`<option value="${t.task_uid}">${esc(t.product||'未命名任务')} · v${t.current_version} · ${esc(t.goal||'')}</option>`).join('');
    if(currentTask)el('creativeTaskChoice').value=currentTask.task_uid;
  }
  async function persistTask(body,withEdits){
    CreativeData.checkBrief(body);
    if(taskReadOnly())throw new Error('历史版本只读，请打开最新版本继续');
    if(!savedMedia){
      if(!file)throw new Error('请先选择视频');
      savedMedia=await request('/api/agent/media',file,{'Content-Type':/\.webm$/i.test(file.name)?'video/webm':'video/mp4','X-Radar-Filename':encodeURIComponent(file.name)});
    }
    const key=inputKey(body);
    if(currentTask&&key===uiBaseline&&CreativeData.sameMedia(currentTask,savedMedia)&&!withEdits)return currentTask;
    const payload={input:body,media_id:savedMedia.media_id,expected_version:currentTask?.current_version||0};
    if(currentTask)payload.task_uid=currentTask.task_uid;
    if(withEdits&&result&&key===uiBaseline&&CreativeData.sameMedia(currentTask,savedMedia))payload.result=editedResult();
    currentTask=await request('/api/agent/task/save',payload);result=currentTask.result;savedMedia=currentTask.media;uiBaseline=key;
    history.replaceState(null,'','/creative?task='+currentTask.task_uid);
    showTask();await loadTaskList();
    if(result)renderResult();else el('creativeResults').hidden=true;
    return currentTask;
  }
  async function saveCurrentTask(withEdits){
    if(busy)return;
    locked(true);
    try{await persistTask(brief(),withEdits);el('creativeStatus').textContent='当前任务已保存，未调用模型。';el('creativeBriefError').textContent='';el('creativeBriefDialog').close();}
    catch(error){el('creativeTaskStatus').textContent=error.message;el('creativeBriefError').textContent=error.message;}
    finally{locked(false);}
  }
  function unsaved(){
    if(!frames.length||taskReadOnly())return false;
    if(!currentTask||inputKey(brief())!==uiBaseline||!CreativeData.sameMedia(currentTask,savedMedia))return true;
    return result&&Object.entries(result.report.deliverables).some(([key,value])=>el('creativeText-'+key)?.value!==value);
  }
  async function openTask(uid,version){
    if(busy||!uid)return;
    if(unsaved()&&!confirm('当前有未保存的修改，打开已保存任务会替换它们；继续？'))return;
    locked(true);
    try{
      const task=await request('/api/agent/task?id='+encodeURIComponent(uid)+(version?'&version='+encodeURIComponent(version):''));
      currentTask=task;savedMedia=task.media;file=null;frames=task.input.frames;duration=task.input.duration;result=task.result;
      if(url){URL.revokeObjectURL(url);url='';}
      const video=el('creativeVideo');video.pause();video.src='/api/agent/media?id='+savedMedia.media_id;video.hidden=false;video.load();
      el('creativeUploadLabel').hidden=true;el('replaceCreativeFile').hidden=false;
      el('creativeFileInfo').textContent=`${savedMedia.filename} · ${duration.toFixed(1)}秒 · ${(savedMedia.size/1048576).toFixed(1)}MB`;
      el('creativeFrames').innerHTML=frames.map((f,i)=>`<figure class="creative-frame"><img src="${f.image}" alt="采样画面 ${i+1}"><figcaption>${CreativeData.clock(f.at)}</figcaption></figure>`).join('');el('creativeFramesHeading').hidden=false;
      for(const [key,id] of Object.entries({product:'creativeProduct',audience:'creativeAudience',facts:'creativeFacts',goal:'creativeGoal',target_seconds:'creativeSeconds',format:'creativeFormat',style:'creativeStyle',reference:'creativeReference',conditions:'creativeConditions',details:'creativeDetails',transcript:'creativeTranscript'}))el(id).value=task.input[key]??'';
      document.querySelectorAll('[name="creativeOutput"]').forEach(box=>{box.checked=task.input.outputs.includes(box.value);});
      transcriptOrigin=task.input.transcript_source==='transcription'?'transcription':'user';
      el('creativeConsent').checked=false;el('creativeTranscribe').checked=false;el('creativeSpeechField').hidden=true;el('creativeSpeechModel').required=false;
      uiBaseline=inputKey(brief());showTask();await loadTaskList();
      if(result)renderResult();else el('creativeResults').hidden=true;
      el('creativeStatus').textContent=taskReadOnly()?'正在查看已保存的历史版本。':'已恢复任务，可以查看资料、生成或保存修改。';
    }catch(error){el('creativeTaskStatus').textContent=error.message;}
    finally{locked(false);}
  }
  async function refreshConfig(){config=await request('/api/ai/config');el('creativeModelStatus').textContent=config.endpoint?`当前模型：${config.model} · ${config.connected||config.local?'可提交请求；需模型支持图片输入':'需填写本次运行的模型密钥'}`:'尚未配置模型，请打开 AI 模型设置。';return config;}
  refreshConfig().catch(error=>{el('creativeModelStatus').textContent=error.message;});
  function locked(value){busy=value;const readonly=taskReadOnly();el('creativeFile').disabled=value||readonly;el('openCreativeBrief').disabled=value||!frames.length;el('openCreativeModel').disabled=value;el('replaceCreativeFile').disabled=value||readonly;el('creativeBriefFields').disabled=value||readonly;el('generateCreative').disabled=value||readonly;el('cancelCreativeBrief').disabled=value;el('closeCreativeBrief').disabled=value;el('saveCreativeTask').disabled=value||readonly||!frames.length;el('saveCreativeInput').disabled=value||readonly;el('openCreativeTask').disabled=value;el('creativeTaskChoice').disabled=value;el('creativeTaskVersion').disabled=value;}
  function eventOnce(target,event,action){return new Promise((resolve,reject)=>{
    const timer=setTimeout(()=>finish(new Error('视频读取超时，请换用可正常播放的 MP4/WebM')),20000);
    function done(){finish();}function fail(){finish(new Error('当前视频编码无法读取，请换用可正常播放的 MP4/WebM'));}
    function finish(error){clearTimeout(timer);target.removeEventListener(event,done);target.removeEventListener('error',fail);error?reject(error):resolve();}
    target.addEventListener(event,done,{once:true});target.addEventListener('error',fail,{once:true});try{action();}catch(error){finish(error);}
  });}
  async function selectVideo(selected){
    if(busy||!selected)return;locked(true);file=null;savedMedia=null;frames=[];result=null;el('creativeResults').hidden=true;el('creativeFrames').replaceChildren();el('creativeFramesHeading').hidden=true;el('creativeConsent').checked=false;
    el('creativeTranscript').value='';transcriptOrigin='';el('creativeTranscribe').checked=false;el('creativeSpeechField').hidden=true;el('creativeSpeechModel').required=false;
    const video=el('creativeVideo');video.pause();video.removeAttribute('src');video.load();if(url){URL.revokeObjectURL(url);url='';}
    try{
      if(selected.size>20*1024*1024||!selected.size)throw new Error('请选择20MB以内的视频');
      if(!/\.(mp4|webm)$/i.test(selected.name))throw new Error('请选择 MP4 或 WebM 视频');
      el('creativeStatus').textContent='正在本机读取视频并提取关键画面…';
      url=URL.createObjectURL(selected);await eventOnce(video,'loadeddata',()=>{video.src=url;video.load();});duration=video.duration;
      const times=CreativeData.sampleTimes(duration),canvas=document.createElement('canvas');
      const scale=Math.min(1,640/Math.max(video.videoWidth,video.videoHeight));canvas.width=Math.max(1,Math.round(video.videoWidth*scale));canvas.height=Math.max(1,Math.round(video.videoHeight*scale));
      const ctx=canvas.getContext('2d');
      for(const at of times){
        if(Math.abs(video.currentTime-at)>.005)await eventOnce(video,'seeked',()=>{video.currentTime=at;});
        ctx.drawImage(video,0,0,canvas.width,canvas.height);let image=canvas.toDataURL('image/jpeg',.75);
        if(image.length>270000)image=canvas.toDataURL('image/jpeg',.45);
        if(image.length>270000)throw new Error('关键画面过大，请缩小视频分辨率后重试');
        frames.push({at,image});el('creativeStatus').textContent=`正在本机提取关键画面 ${frames.length}/${times.length}…`;
      }
      video.currentTime=0;file=selected;video.hidden=false;el('creativeUploadLabel').hidden=true;el('replaceCreativeFile').hidden=false;
      el('creativeFileInfo').textContent=`${selected.name} · ${duration.toFixed(1)}秒 · ${(selected.size/1048576).toFixed(1)}MB`;
      el('creativeFrames').innerHTML=frames.map((f,i)=>`<figure class="creative-frame"><img src="${f.image}" alt="采样画面 ${i+1}"><figcaption>${CreativeData.clock(f.at)}</figcaption></figure>`).join('');el('creativeFramesHeading').hidden=false;
      el('creativeStatus').textContent=`已在本机提取 ${frames.length} 张画面，尚未发送给模型。`;
    }catch(error){frames=[];file=null;video.hidden=true;el('creativeUploadLabel').hidden=false;el('creativeFileInfo').textContent='尚未选择';el('creativeStatus').textContent=error.message;}
    finally{locked(false);el('creativeFile').value='';}
    if(file)await openBrief();
  }
  function sendScope(){
    const speech=el('creativeTranscribe').checked;
    el('creativeSendScope').textContent=`${tasksEnabled?taskScope()+'。\n':''}${frames.length} 张采样画面、采样时间、商品资料与创作选项${el('creativeTranscript').value.trim()?'、参考台词':''}。\n模型：${config?.model||'尚未配置'} · ${config?.endpoint?new URL(config.endpoint).host:'请先设置模型'}。\n${speech?'另发送原视频至同一服务转写口播，然后发送1次分析请求，共最多2次模型请求。':'发送1次分析请求，不发送原视频和音轨。'}`;
  }
  async function openBrief(){if(!frames.length)return;el('creativeBriefError').textContent='';el('creativeConsent').checked=false;try{await refreshConfig();}catch(error){el('creativeBriefError').textContent=error.message;}sendScope();el('creativeBriefDialog').showModal();}
  el('creativeFile').onchange=event=>selectVideo(event.target.files[0]);el('replaceCreativeFile').onclick=()=>el('creativeFile').click();el('openCreativeBrief').onclick=openBrief;
  el('closeCreativeBrief').onclick=el('cancelCreativeBrief').onclick=()=>el('creativeBriefDialog').close();
  el('creativeBriefDialog').addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  el('creativeTranscribe').onchange=()=>{el('creativeSpeechField').hidden=!el('creativeTranscribe').checked;el('creativeSpeechModel').required=el('creativeTranscribe').checked;el('creativeConsent').checked=false;sendScope();};
  el('creativeTranscript').oninput=()=>{transcriptOrigin='user';el('creativeConsent').checked=false;sendScope();};
  el('creativeBriefForm').oninput=()=>{el('creativeBriefError').textContent='';};
  function brief(){const transcript=el('creativeTranscript').value.trim();return {confirmed:el('creativeConsent').checked,duration,frames,product:el('creativeProduct').value.trim(),audience:el('creativeAudience').value.trim(),facts:el('creativeFacts').value.trim(),outputs:[...document.querySelectorAll('[name="creativeOutput"]:checked')].map(n=>n.value),goal:el('creativeGoal').value,format:el('creativeFormat').value,style:el('creativeStyle').value,target_seconds:Number(el('creativeSeconds').value),reference:el('creativeReference').value,conditions:el('creativeConditions').value.trim(),details:el('creativeDetails').value.trim(),transcript,transcript_source:transcript?(transcriptOrigin==='transcription'?'transcription':'manual'):'none'};}
  el('creativeBriefForm').onsubmit=async event=>{
    event.preventDefault();if(busy)return;
    try{
      const body=brief();CreativeData.checkBrief(body);if(!body.confirmed)throw new Error('请确认本次发送范围');
      if(!config?.endpoint||!config?.model||!config.connected&&!config.local)throw new Error('请先关闭此弹窗，在 AI 模型设置中填写支持图片输入的模型和密钥');
      locked(true);el('creativeBriefError').textContent='';el('generateCreative').textContent='正在生成…';
      el('creativeConsent').checked=false;
      result=null;el('creativeResults').hidden=true;
      if(el('creativeTranscribe').checked){
        const model=el('creativeSpeechModel').value.trim();if(!/^[A-Za-z0-9][A-Za-z0-9._:/-]{0,149}$/.test(model))throw new Error('请填写有效的转写模型标识');
        el('creativeStatus').textContent='正在识别参考视频口播；完成后继续分析…';
        if(!file&&savedMedia){const response=await fetch('/api/agent/media?id='+savedMedia.media_id);if(!response.ok)throw new Error('已保存视频读取失败');file=new File([await response.blob()],savedMedia.filename,{type:savedMedia.mime});}
        const audio=await request('/api/video/transcribe',file,{'Content-Type':/\.webm$/i.test(file.name)?'video/webm':'video/mp4','X-Radar-Speech-Model':model,'X-Radar-Confirmed':'true'});
        body.transcript=audio.text;el('creativeTranscript').value=audio.text;transcriptOrigin='transcription';el('creativeTranscribe').checked=false;el('creativeSpeechField').hidden=true;el('creativeSpeechModel').required=false;
        body.transcript_source='transcription';
        sendScope();
      }
      el('creativeStatus').textContent='正在分析关键画面并生成所选成果…';
      if(tasksEnabled){await persistTask(body,false);currentTask=await request('/api/agent/task/generate',{task_uid:currentTask.task_uid,expected_version:currentTask.current_version,confirm:true});savedMedia=currentTask.media;result=currentTask.result;uiBaseline=inputKey(body);showTask();await loadTaskList();}
      else result=await request('/api/video/generate',body);
      renderResult();el('creativeBriefDialog').close();el('creativeStatus').textContent=tasksEnabled?'分析完成，成果已随任务保存。请核对后继续；没有生成视频成片。':'分析完成，请导出保存；没有生成视频成片。';el('creativeResults').scrollIntoView({behavior:'smooth',block:'start'});
    }catch(error){
      el('creativeBriefError').textContent=error.message;el('creativeStatus').textContent='本次未完成：'+error.message+(transcriptOrigin==='transcription'?' 已转写的台词仍在弹窗中，再次生成不会自动重复转写。':'');
      if(tasksEnabled&&currentTask&&inputKey(brief())===uiBaseline){
        try{currentTask=await request('/api/agent/task?id='+currentTask.task_uid);result=currentTask.result;showTask();if(result)renderResult();}catch{}
      }
    }
    finally{locked(false);el('generateCreative').textContent='生成所选成果';}
  };
  function renderResult(){
    const report=result.report,scope=result.scope;
    el('creativeResults').hidden=false;el('creativeResultScope').textContent=`规则 V1.1 · 模型 ${result.model} · ${scope.frames.length} 张采样画面 · ${scope.audio}。${scope.limitation}`;
    const stamp=id=>CreativeData.clock(scope.frames[id-1].at);
    el('creativeAnalysis').innerHTML=`<p class="creative-analysis-summary">${esc(report.summary)}</p><details class="creative-analysis-details" open><summary>关键画面拆解 · 事实 / 推测 / 建议</summary>${report.observations.map(row=>`<div class="creative-observation"><b>画面 ${row.frame} · ${stamp(row.frame)}</b><p><em>观察事实</em>${esc(row.evidence)}</p><p><em>分析推测</em>${esc(row.inference)}</p><p><em>改编建议</em>${esc(row.advice)}</p></div>`).join('')}</details><details class="creative-analysis-details"><summary>十项内容评价</summary><div class="creative-evaluations">${report.evaluations.map(row=>`<div class="creative-evaluation"><strong>${esc(row.dimension)}</strong><span>${esc(row.verdict)}</span><p>${esc(row.reason)}</p><p>${row.frames.map(i=>`画面 ${i} · ${stamp(i)}`).join(' / ')||'无可验证的画面证据'}</p></div>`).join('')}</div></details><details class="creative-analysis-details"><summary>适配判断与待补信息</summary>${[['reuse','可沿用'],['adjust','需调整'],['avoid','不适合沿用']].map(([key,title])=>`<div class="creative-adaptation"><strong>${title}</strong><ul>${report.adaptation[key].map(t=>`<li>${esc(t)}</li>`).join('')}</ul></div>`).join('')}<div class="creative-adaptation"><strong>待补资料 / 无法判断</strong><ul>${report.missing.map(t=>`<li>${esc(t)}</li>`).join('')}</ul></div></details>`;
    const descriptions={shooting:'用于真人准备与拍摄，镜头时间为建议安排。',video_prompt:'交给视频生成工具使用；素材依赖需补齐，商品效果示意不能作为真实证明。',writing_prompt:'可复制交给文字大模型继续写稿，包含必要上下文。'};
    el('creativeDeliverables').innerHTML=Object.entries(report.deliverables).map(([key,value])=>`<article class="creative-deliverable"><header><h3>${CreativeData.names[key]}</h3><button class="secondary compact" data-copy-creative="${key}">复制内容</button></header><p>AI 生成 · ${descriptions[key]}可编辑。</p><textarea id="creativeText-${key}" aria-label="${CreativeData.names[key]}" spellcheck="false">${esc(value)}</textarea></article>`).join('');
    el('creativeDeliverables').querySelectorAll('textarea').forEach(area=>{area.readOnly=taskReadOnly();});
  }
  el('creativeDeliverables').onclick=async event=>{const button=event.target.closest('[data-copy-creative]');if(!button)return;const area=el('creativeText-'+button.dataset.copyCreative);try{await navigator.clipboard.writeText(area.value);button.textContent='已复制';setTimeout(()=>{button.textContent='复制内容';},1800);}catch{area.focus();area.select();button.textContent='已选中，请按 Ctrl+C';}};
  el('saveReference').onclick=async()=>{
    if(!result)return;
    el('saveReference').disabled=true;
    try{
      const data=await request('/api/reference/save',{title:'视频分析 '+new Date().toLocaleDateString('sv-SE'),version:'T03',report:editedResult().report,scope:result.scope,model:result.model,post_id:null,source_name:file?file.name:savedMedia?.filename||''});
      el('creativeStatus').textContent='已保存为参考 #'+data.id+'，可在脚本页选用。';
    }catch(error){el('creativeStatus').textContent=error.message;}
    finally{el('saveReference').disabled=false;}
  };
  el('exportCreative').onclick=()=>{
    if(!result)return;const r=result.report,s=result.scope;
    let content=`# 视频分析与改编\n\n规则 V1.1 · 模型 ${result.model}\n\n${s.limitation}\n\n读取范围：${s.frames.length}张采样画面；${s.audio}\n\n## 分析摘要\n\n${r.summary}\n\n## 关键画面拆解\n\n`;
    content=CreativeData.provenance(currentTask,unsaved())+content;
    for(const row of r.observations)content+=`### 画面 ${row.frame} · ${CreativeData.clock(s.frames[row.frame-1].at)}\n\n观察事实：${row.evidence}\n\n分析推测：${row.inference}\n\n改编建议：${row.advice}\n\n`;
    content+='## 十项评价\n\n';for(const row of r.evaluations)content+=`- ${row.dimension}：${row.verdict}。${row.reason}（${row.frames.map(i=>'画面'+i).join('、')||'证据不足'}）\n`;
    for(const [key,title] of [['reuse','可沿用'],['adjust','需调整'],['avoid','不适合沿用']])content+=`\n## ${title}\n\n${r.adaptation[key].map(t=>'- '+t).join('\n')}\n`;
    content+='\n## 待补信息\n\n'+r.missing.map(t=>'- '+t).join('\n')+'\n';
    for(const key of Object.keys(r.deliverables))content+=`\n## ${CreativeData.names[key]}\n\nAI 生成，可编辑；不是实际效果证明。\n\n${el('creativeText-'+key).value}\n`;
    const href=URL.createObjectURL(new Blob(['\ufeff'+content],{type:'text/markdown;charset=utf-8'})),link=document.createElement('a');link.href=href;link.download='视频分析与改编-'+new Date().toISOString().slice(0,10)+'.md';document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(href),60000);
  };
  el('openCreativeModel').onclick=async()=>{try{await refreshConfig();el('creativeEndpoint').value=config.endpoint;el('creativeModelName').value=config.model;el('creativeModelKey').value='';el('creativeModelKey').placeholder=config.connected?'已配置；留空保留':'填写密钥，本机免密服务可留空';el('creativeModelError').textContent='';el('creativeModelDialog').showModal();}catch(error){el('creativeStatus').textContent=error.message;}};
  el('closeCreativeModel').onclick=()=>el('creativeModelDialog').close();el('creativeModelDialog').addEventListener('close',()=>{el('creativeModelKey').value='';});
  async function saveModel(clear=false){
    const body={endpoint:el('creativeEndpoint').value.trim(),model:el('creativeModelName').value.trim(),clear_key:clear};const key=el('creativeModelKey').value.trim();if(key&&!clear)body.key=key;
    el('saveCreativeModel').disabled=true;el('forgetCreativeModelKey').disabled=true;
    try{config=await request('/api/ai/config',body);el('creativeModelKey').value='';el('creativeModelDialog').close();await refreshConfig();el('creativeStatus').textContent=clear?'已清除模型密钥。':'模型配置已保存，未调用模型。';}catch(error){el('creativeModelError').textContent=error.message;}finally{el('saveCreativeModel').disabled=false;el('forgetCreativeModelKey').disabled=false;}
  }
  el('creativeModelForm').onsubmit=event=>{event.preventDefault();saveModel();};el('forgetCreativeModelKey').onclick=()=>saveModel(true);
  el('saveCreativeTask').onclick=()=>saveCurrentTask(true);
  el('saveCreativeInput').onclick=()=>saveCurrentTask(false);
  el('openCreativeTask').onclick=()=>openTask(el('creativeTaskChoice').value);
  el('creativeTaskVersion').onchange=()=>{if(currentTask)openTask(currentTask.task_uid,el('creativeTaskVersion').value);};
  window.addEventListener('beforeunload',event=>{if(tasksEnabled&&unsaved()){event.preventDefault();event.returnValue='';}});
  initial.then(async()=>{if(!tasksEnabled)return;accountInfo=await request('/api/agent/account');showTask();await loadTaskList();const params=new URLSearchParams(location.search),uid=params.get('task');if(uid&&/^[a-f0-9]{12}$/.test(uid))await openTask(uid,params.get('version'));}).catch(error=>{el('creativeTaskStatus').textContent=error.message;});
})();
