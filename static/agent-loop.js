(() => {
  'use strict';
  const el=id=>document.getElementById(id);
  let run=null, latest=null, busy=false;
  const labels={created:'已建立',diagnosed_with_gaps:'资料已诊断，表现资料待补',topic_selected:'选题已确认',reference_fetched:'已抓取标题资料',reference_ready:'标题分析已保存',creation_ready:'分镜已生成，待人工评审',draft_saved:'测试创作稿已保存',feedback_saved:'反馈已保存',test_loop_complete:'隔离技术流程已完成；真实发布与人工质量待验'};
  async function api(path,body){
    const options={};
    if(body){const state=await (await fetch('/api/state?mode=live')).json();options.method='POST';options.headers={'Content-Type':'application/json','X-Radar-Token':state.token};options.body=JSON.stringify(body);}
    const response=await fetch(path,options),data=await response.json();
    if(!response.ok||data.error)throw new Error(data.error||'本机请求失败');
    return data;
  }
  function node(tag,text){const n=document.createElement(tag);n.textContent=text;return n;}
  function status(text,error=false){el('loopStatus').textContent=text;el('loopStatus').dataset.error=String(error);}
  function allowed(action){
    if(!run||run.version!==latest||busy)return false;
    return {diagnose:!run.diagnosis,select:!!run.diagnosis&&!run.reference,
      fetch:!!run.topic&&!run.reference,reference:run.reference?.status==='fetched'&&!run.reference_attempt,
      creation:!!run.reference_analysis&&!run.creation_attempt,handoff:!!run.creation&&!run.content_task,
      feedback:!!run.content_task&&!run.feedback?.actual,review:!!run.feedback?.actual}[action];
  }
  function render(){
    el('loopNew').disabled=busy;el('loopRuns').disabled=busy;el('loopVersions').disabled=busy||!run;
    el('loopExport').disabled=busy||!run;
    document.querySelectorAll('[data-loop-action]').forEach(b=>b.disabled=!allowed(b.dataset.loopAction));
    el('loopSynthetic').disabled=busy||!run?.content_task||run.version!==latest||!!run.feedback?.simulation;
    if(!run)return;
    status(`${labels[run.status]||run.status} · v${run.version} · ${run.run_uid}${run.version!==latest?' · 历史只读':''}`);
    el('loopEvidence').textContent=JSON.stringify(run,null,2);
    const stages=[['诊断',run.diagnosis],['选题',run.topic],['参考',run.reference_analysis],['创作',run.creation],['反馈',run.feedback?.actual],['复盘',run.review]];
    el('loopProgress').replaceChildren(...stages.map(([label,done])=>{const n=node('li',`${label} · ${done?'已保存':'待执行'}`);n.dataset.done=String(!!done);return n;}));
    const result=el('loopResult');result.replaceChildren();
    if(run.diagnosis)result.append(node('p','表现类结论：未输出。未配置门槛、未提供自有作品指标；资料画像有来源快照可查。'));
    if(run.reference)result.append(node('p',`参考：${run.reference.title||'尚无可确认结果'}。${run.reference.scope||'请求未确认，不自动重试。'}`));
    if(run.reference_analysis){result.append(node('h3','可借鉴表达 · 仅标题资料'));run.reference_analysis.patterns.forEach(p=>{result.append(node('strong',p.pattern||'待核对表达'),node('p','依据：'+(p.basis||'待补')));});result.append(node('p','限制：'+run.reference_analysis.limitations.join('；')));}
    if(run.creation){result.append(node('h3',run.creation.title||run.topic.title));run.creation.beats.forEach(b=>{const article=node('article','');article.className='agent-loop-shot';article.append(node('strong',`${b.beat} · ${b.seconds}秒`),node('p',b.text),node('p',`待拍镜头：${b.shot}`));result.append(article);});result.append(node('h3','AI辅助画面提示词'),node('p',run.creation.video_prompt));}
    if(run.content_task){const a=node('a','打开已保存创作稿 →');a.href='/script?task='+encodeURIComponent(run.content_task.task_uid);result.append(a);}
    if(run.review){result.append(node('h3','未发布的真实分支'),node('p',run.review.actual.observations.join('；')));if(run.review.simulation)result.append(node('h3','合成反馈演练 · 不代表账号效果'),node('p',run.review.simulation.observations.join('；')));result.append(node('p',run.review.next_action));}
  }
  async function refresh(uid){
    const state=await api('/api/agent/loop');
    el('agentLoop').hidden=!state.enabled;if(!state.enabled)return;
    document.querySelector('.wallboard-intro').textContent='运营资料只读展示；下方隔离测试面板按步骤执行，正式账号不改动。';
    el('loopRuns').replaceChildren(node('option','新建测试'));
    el('loopRuns').firstChild.value='';
    state.runs.forEach(r=>{const option=node('option',`${r.title} · ${r.run_uid} · v${r.version}`);option.value=r.run_uid;el('loopRuns').append(option);});
    run=state.runs.find(r=>r.run_uid===(uid||run?.run_uid))||state.runs[0]||null;
    latest=run?.version||null;
    if(run){el('loopRuns').value=run.run_uid;el('loopVersions').replaceChildren(...Array.from({length:latest},(_,i)=>{const option=node('option','v'+(i+1));option.value=String(i+1);return option;}));el('loopVersions').value=String(latest);}else status('尚无测试运行。先建立运行，再逐步执行。');
    render();
  }
  async function act(action,extra={}){
    if(busy)return;busy=true;render();status(`正在执行 ${action}；不会自动请求下一步。外部请求发出后关闭页面不能撤回。`);
    let failure='';
    try{const saved=await api('/api/agent/loop/action',{action,run_uid:run?.run_uid,expected_version:run?.version,...extra});await refresh(saved.run_uid);}
    catch(error){failure=error.message+'；请检查设置或检查证据，付费失败不会自动重试。';}
    finally{busy=false;render();if(failure)status(failure,true);}
  }
  el('loopNew').onclick=()=>act('create',{confirm_test:true,title:'AI创作者 · 隔离全流程'});
  el('loopRuns').onchange=()=>refresh(el('loopRuns').value).catch(e=>status(e.message,true));
  el('loopVersions').onchange=async()=>{try{run=await api('/api/agent/loop?run_uid='+run.run_uid+'&version='+el('loopVersions').value);render();}catch(e){status(e.message,true);}};
  document.querySelectorAll('[data-loop-action]').forEach(button=>button.onclick=()=>{
    const action=button.dataset.loopAction,extra={};
    if(action==='select')Object.assign(extra,{title:el('loopTopic').value,source_url:el('loopSource').value,excerpt:el('loopExcerpt').value,role:'market_task',observed_at:new Date().toISOString().slice(0,10)});
    if(action==='fetch')extra.video_id=el('loopVideo').value;
    act(action,extra);
  });
  el('loopSynthetic').onclick=()=>act('feedback',{simulated:true,confirm_simulated:true,metrics:{plays:Number(el('loopPlays').value),comments:Number(el('loopComments').value)}});
  el('loopExport').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(run,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`ICE-test-${run.run_uid}-v${run.version}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  refresh().catch(error=>status(error.message,true));
})();
