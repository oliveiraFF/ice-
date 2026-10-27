const $ = id => document.getElementById(id);
const esc = value => String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const exact = value => value===null?'未知':value.toLocaleString('zh-CN');
const compact = value => value===null?'未知':value>=100000000?(value/100000000).toFixed(2)+'亿':value>=10000?(value/10000).toFixed(1)+'万':exact(value);
const date = at => at?new Date(at*1000).toLocaleString('zh-CN',{timeZone:'America/Los_Angeles',hour12:false}):'尚无记录';
const platformName = id => id==='dy'?'抖音':id==='xhs'?'小红书':id;
function bar(count,total){const width=total?Math.min(100,count/total*100):0;return `<svg viewBox="0 0 100 4" preserveAspectRatio="none" aria-hidden="true"><rect class="rank-track" width="100" height="4" rx="2"/><rect class="rank-bar" width="${width}" height="4" rx="2"/></svg>`;}
function videoTitle(post){try{const url=new URL(post.url);if(url.protocol==='https:'&&['www.douyin.com','www.xiaohongshu.com'].includes(url.hostname))return `<a href="${esc(url.href)}" target="_blank" rel="noopener noreferrer" title="${esc(post.title)}">${esc(post.title)}</a>`;}catch{}return `<span class="rank-title">${esc(post.title)}</span>`;}
function render(summary){
  $('sourceAccessStatus').textContent=summary.access?.active?'已开启':'已关闭或停止';
  $('videoTotal').textContent=exact(summary.total);$('playsTotal').textContent=compact(summary.playsTotal);$('playsTotal').title=exact(summary.playsTotal);
  $('playsCoverage').textContent=`${summary.playsKnown} 条已知 · ${summary.total-summary.playsKnown} 条未知`;
  $('highestPlays').textContent=compact(summary.highest);$('highestPlays').title=exact(summary.highest);
  $('keywordsCovered').textContent=`${summary.keywordsCovered} / ${summary.keywords.length}`;
  $('videoRanking').innerHTML=summary.top.length?summary.top.map((post,i)=>`<li><span class="rank-index">${String(i+1).padStart(2,'0')}</span><div class="rank-info">${videoTitle(post)}<p>${esc(post.author)} · ${platformName(post.platform)}</p>${bar(post.plays,summary.highest)}</div><span class="rank-number" title="${exact(post.plays)}">${compact(post.plays)}</span></li>`).join(''):'<li class="screen-empty">暂无播放量已知的本地视频</li>';
  const circumference=2*Math.PI*63;let offset=0;
  $('platformDonut').innerHTML='<circle class="donut-track" cx="80" cy="80" r="63"/>'+summary.platforms.map((p,i)=>{const length=summary.total?p.count/summary.total*circumference:0;const element=`<circle class="donut-segment segment-${i%3}" cx="80" cy="80" r="63" stroke-dasharray="${length} ${circumference}" stroke-dashoffset="${-offset}"/>`;offset+=length;return element;}).join('');
  $('platformDonut').setAttribute('aria-label',summary.platforms.length?summary.platforms.map(p=>platformName(p.id)+' '+p.count+'条').join('；'):'没有平台数据');
  $('platformTotal').textContent=summary.total;
  $('platformLegend').innerHTML=summary.platforms.length?summary.platforms.map(p=>`<div>${RadarIcons.platform(p.id)}${esc(platformName(p.id))}<strong>${(p.count/summary.total*100).toFixed(0)}%</strong></div>`).join(''):'<span class="screen-empty">暂无数据</span>';
  $('dataCoverage').innerHTML=[['播放量',summary.playsKnown],['点赞数',summary.likesKnown]].map(([label,count])=>`<div class="coverage-item"><span>${RadarIcons.svg('eye')}${label}已知</span><strong>${count} / ${summary.total}</strong></div><div class="coverage-progress">${bar(count,summary.total)}</div>`).join('');
  const maxBin=Math.max(1,...summary.bins.map(bin=>bin.count));
  $('playDistribution').innerHTML=summary.bins.map((bin,i)=>{const height=bin.count/maxBin*90;return `<div class="distribution-row ${i===4?'unknown':''}"><span>${bin.name}</span><svg viewBox="0 0 60 100" preserveAspectRatio="none" aria-hidden="true"><rect class="rank-bar" x="10" y="${100-height}" width="40" height="${height}" rx="2"/></svg><strong>${bin.count}</strong></div>`;}).join('');
  $('keywordWatch').innerHTML=summary.keywords.length?summary.keywords.map(k=>`<div><span>${esc(k.name)}<small>${k.count?'已有本地样本':'暂无本地样本'}</small></span><strong>${k.count} 条</strong></div>`).join(''):'<p class="screen-empty">尚未设置监测关键词</p>';
  const scan=summary.lastScan;
  $('lastScanTitle').textContent=!scan?'尚未采集':scan.error?'历史采集已停止':'历史采集记录';
  $('lastScanIndicator').classList.toggle('warning',Boolean(scan?.error));
  $('lastScanMessage').textContent=scan?(scan.error||scan.message||`返回 ${scan.count??0} 条候选`):'可在API市场选择接口收录作品，也可导入本地视频数据。';
  $('lastScanTime').textContent=date(scan?.at);
  $('dashboardReadAt').textContent='本次读取 '+date(Date.now()/1000)+' · 视频最近记录 '+date(summary.updatedAt);
  $('dashboardUpdated').textContent='数据更新 '+date(summary.updatedAt);
}
async function load(){const button=$('refreshDashboard');button.disabled=true;$('dashboardError').hidden=true;try{const response=await fetch('/api/state?mode=live');if(!response.ok)throw new Error('读取本地数据失败，请确认服务仍在运行。');render(DashboardData.summarize(await response.json()));}catch(error){$('dashboardError').textContent=error.message+' 原有显示数据保留。';$('dashboardError').hidden=false;}finally{button.disabled=false;}}
let opsSeq=0,opsLast=null,opsLastAt='';
function escOps(value){return String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function opsLink(path,text){return '<a href="'+path+'">'+text+'</a>';}
function opsList(items,render){return items.length?items.map(render).join(''):'<p class="source-muted">暂无</p>';}
function taskTopic(data,item){const plan=(data.plans||[]).find(row=>row.task_uid===item.task_uid&&String(row.version)===String(item.version));const snap=plan?((plan.plan||{}).topic_snapshot||{}):{};return snap.topic?' · 主题 '+escOps(snap.topic):' · 主题未提供';}
function formalLabel(item){if(item.formal===1)return '（正式）';if(item.formal===0)return '（试用）';return '';}
function taskLabel(data,label,item){return label+' '+escOps(item.task_uid)+' v'+item.version+formalLabel(item)+taskTopic(data,item)+(item.product?' · 业务对象 '+escOps(item.product):'');}
function renderOps(data){
  const counts=data.tasks.counts;
  $('opsSummary').innerHTML='<p>草稿/待补 <strong>'+counts.draft+'</strong> · 待审 <strong>'+counts.pending_review+'</strong> · 已审未登记 <strong>'+counts.approved_unpublished+'</strong> · 已登记发布 <strong>'+data.published.count+'</strong> 篇作品</p><p class="source-muted">参考作品样本与本人运营记录分区；样本播放不进入本人效果。</p><h3>任务</h3>'+opsList(data.tasks.draft,item=>opsLink('/script?task='+encodeURIComponent(item.task_uid)+'&version='+item.version,taskLabel(data,'草稿',item)))+opsList(data.tasks.pending_review,item=>opsLink('/script?task='+encodeURIComponent(item.task_uid)+'&version='+item.version,taskLabel(data,'待审',item)))+opsList(data.tasks.approved_unpublished,item=>opsLink('/feedback?task='+encodeURIComponent(item.task_uid)+'&version='+item.version,taskLabel(data,'已审未登记',item)));
  $('opsBlockers').innerHTML='<h3>阻断</h3>'+(data.blockers.length?data.blockers.map(item=>'<p>'+escOps(item.reason)+(item.target?' '+opsLink(item.target,'处理'):'')+'</p>').join(''):'<p class="source-muted">暂无</p>');
  $('opsCombo').innerHTML='<h3>今日组合</h3>'+(data.combo?'<p>组合 '+escOps(data.combo.combo_uid)+' v'+data.combo.version+' · 策略 v'+data.combo.strategy_version+' · '+(data.combo.snapshot_json||[]).map(item=>escOps(item.lane+' '+item.topic)).join('；')+'</p>':'<p class="source-muted">今日尚未选择；'+opsLink('/script','去选择')+'</p>');
  $('opsPlans').innerHTML='<h3>执行计划</h3>'+opsList(data.plans,item=>{const plan=item.plan||{},snap=plan.topic_snapshot||{};const topic=snap.topic?escOps(snap.topic):'主题未提供';const source=plan.combo_uid?'来源 组合 '+escOps(plan.combo_uid):'来源未提供';const strategy=plan.strategy_version?' · 策略 v'+plan.strategy_version:'';return opsLink('/script?task='+encodeURIComponent(item.task_uid)+'&version='+item.version,escOps(item.task_uid)+' v'+item.version+' · '+topic)+' <small>'+source+strategy+' · 建立日期未提供 · 状态未提供（按现有响应）</small>';});
  $('opsMetrics').innerHTML='<h3>本人作品最新指标</h3>'+(data.latest_metrics.length?data.latest_metrics.map(item=>'<p>'+opsLink('/feedback?record='+encodeURIComponent(item.record_uid),escOps(item.platform)+' · '+escOps(item.platform_post_id)+' · v'+item.version)+(item.snapshot?' · '+escOps(item.snapshot.collected_at)+' · '+escOps(JSON.stringify(item.snapshot.metrics)):' · 尚未录入')+'</p>').join(''):'<p class="source-muted">尚无已登记作品</p>');
  $('opsSuggestions').innerHTML='<h3>复盘建议</h3>'+(data.suggestions.length?data.suggestions.map(item=>'<p>'+opsLink('/feedback?record='+encodeURIComponent(item.record_uid)+'&review='+encodeURIComponent(item.review_uid)+'&suggestion='+encodeURIComponent(item.id),escOps(item.id))+' · '+(item.used?'已用于稿件':'未采用')+' · '+escOps(item.suggestion.text)+'</p>').join(''):'<p class="source-muted">暂无</p>');
  $('opsActions').innerHTML='<h3>今日动作</h3>'+(data.actions.length?data.actions.map(item=>'<p>'+opsLink(item.target,escOps(item.reason))+'</p>').join(''):'<p class="source-muted">暂无待办</p>');
  $('opsStrategy').innerHTML='<h3>策略</h3><p>'+(data.strategy.configured?(data.strategy.confirmed?'已确认 v'+data.strategy.version:'未确认 v'+data.strategy.version):'未设置')+' · 受影响正式任务 '+data.strategy.affected_formal.length+' 个 · '+opsLink('/strategy','打开策略')+'</p><p class="source-muted">诊断：'+escOps(data.diagnosis.reason)+'</p>';
}
async function loadOps(){
  opsSeq+=1;const seq=opsSeq;
  try{const response=await fetch('/api/ops/dashboard');if(!response.ok)throw new Error('运营数据读取失败');const data=await response.json();if(seq!==opsSeq)return;opsLast=data;opsLastAt=new Date().toLocaleString('zh-CN');renderOps(data);$('opsError').hidden=true;$('opsError').textContent='';$('opsReadAt').textContent='业务日 '+data.business_date+' · 读取 '+data.read_at+' · 时区 '+data.timezone;}
  catch(error){if(seq!==opsSeq)return;$('opsError').textContent=error.message+'（'+(opsLast?'显示旧数据，上次成功 '+opsLastAt:'尚无成功数据')+'）';$('opsError').hidden=false;}
}
$('refreshDashboard').onclick=()=>{load();if(document.getElementById('opsPanel'))loadOps();};
if(document.getElementById('opsPanel'))loadOps();
$('dashboardSettings').onclick=()=>$('siteSettings').click();
$('fullScreen').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}catch{$('dashboardError').textContent='当前浏览器未允许全屏，可继续在窗口中查看。';$('dashboardError').hidden=false;}};
document.addEventListener('fullscreenchange',()=>{const active=Boolean(document.fullscreenElement);$('fullScreen').innerHTML=RadarIcons.svg(active?'minimize':'maximize');$('fullScreen').setAttribute('aria-label',active?'退出全屏':'进入全屏');$('fullScreen').title=active?'退出全屏':'进入全屏';});
function clock(){$('screenClock').textContent=new Date().toLocaleString('zh-CN',{timeZone:'America/Los_Angeles',hour12:false});}
clock();setInterval(clock,1000);load();

/* The today view reads existing local records; refreshing never generates or collects. */
(() => {
  if (!document.getElementById('workbench')) return;
  const node = id => document.getElementById(id);
  const safe = esc;
  const empty = (text, href, label) => '<p class="wb-empty">' + text + (href ? ' <a href="' + href + '">' + label + ' →</a>' : '') + '</p>';
  const at = value => typeof value === 'number' ? value * 1000 : Date.parse(value);
  const time = value => Number.isFinite(at(value)) ? new Date(at(value)).toLocaleString('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}) : '时间未提供';
  const badge = (label, tone) => '<span class="wb-pill ' + (tone || '') + '">' + safe(label) + '</span>';
  let sequence = 0;
  async function read(path) {
    const response = await fetch(path);
    if (!response.ok) throw new Error('本机运营记录读取失败');
    return response.json();
  }
  function renderWeek(summary) {
    const maximum = Math.max(1, ...summary.week.map(day => day.count));
    const labels = ['日','一','二','三','四','五','六'];
    node('wbWeekChart').innerHTML = summary.week.map((day,i) => {
      const label = '周' + labels[new Date(day.day + 'T12:00:00Z').getUTCDay()];
      return '<div class="wb-day" title="' + safe(day.day) + ' · ' + day.count + ' 篇"><strong>' + day.count + '</strong><div class="wb-day-track"><svg viewBox="0 0 50 124" preserveAspectRatio="none" aria-hidden="true"><defs><linearGradient id="wbBar' + i + '" x1="0" y1="0" x2="0" y2="1"><stop class="wb-bar-top" offset="0"/><stop class="wb-bar-bottom" offset="1"/></linearGradient></defs><rect fill="url(#wbBar' + i + ')" x="7" y="' + (124 - day.count / maximum * 112) + '" width="36" height="' + day.count / maximum * 112 + '" rx="7"/></svg></div><span>' + label + '</span></div>';
    }).join('');
    node('wbWeekChart').setAttribute('aria-label', summary.week.map(day=>day.day+'：'+day.count+'篇').join('；'));
    node('wbWeekNote').textContent = summary.unknownDates ? summary.unknownDates + ' 篇缺少有效发布时间，未计入图表。' : '按本机业务时区统计；登记数据尚未经平台核实。';
  }
  async function loadWorkbench() {
    const seq = ++sequence;
    node('wbRefresh').disabled = true;
    node('wbReadStatus').textContent = '本机记录 · 正在读取';
    try {
      const [operations, advices, drafts, reviews, videoTasks] = await Promise.all([
        '/api/ops/dashboard','/api/ops/advice/list','/api/ops/draft/list','/api/ops/media-review/list','/api/agent/tasks'
      ].map(read));
      const latest = advices.find(item => item.result_json && (item.result_json.week_actions || []).length && item.source !== 'demo' && !item.simulated);
      const actions = latest ? (latest.result_json.week_actions || []).map(action => ({
        text:action.action, state:(latest.actions || []).find(item=>item.action_id === action.id)?.status || 'todo'
      })) : [];
      const videoDetails = await Promise.all(videoTasks.slice(0,4).map(item => read('/api/agent/task?id=' + encodeURIComponent(item.task_uid))));
      if (seq !== sequence) return;
      const summary = DashboardData.operationsSummary(operations, actions);
      node('wbBusinessDate').textContent = '业务日 ' + operations.business_date;
      node('wbFocusCount').textContent = summary.focusCount;
      node('wbWeekOutput').textContent = summary.weekOutput === null ? '—' : (summary.unknownDates ? '≥ ' : '') + summary.weekOutput;
      node('wbWeekOutput').title = summary.unknownDates ? summary.unknownDates + ' 篇缺少有效发布时间，未计入' : '按发布时间统计本周已登记作品';
      node('wbPendingCount').textContent = summary.projects.length;
      const focusLink = node('wbFocusAction');
      const openAdvice = actions.find(item=>!['done','cancelled'].includes(item.state));
      if (summary.firstAction) {
        node('wbFocusCopy').textContent = '先处理：' + summary.firstAction.reason + '。进度与依据可在任务内继续查看。';
        focusLink.href = summary.firstAction.target;
        focusLink.innerHTML = '处理当前任务 <span aria-hidden="true">→</span>';
      } else if (openAdvice) {
        node('wbFocusCopy').textContent = '下一步：' + openAdvice.text + '。来自最近一次已保存的运营建议。';
        focusLink.href = '/advice?id=' + encodeURIComponent(latest.advice_uid);
        focusLink.innerHTML = '查看行动建议 <span aria-hidden="true">→</span>';
      } else {
        node('wbFocusCopy').textContent = '当前没有已登记的待办。从一个真实主题或本地视频开始，保存资料后继续创作。';
        focusLink.href = '/creative';
        focusLink.innerHTML = '新建内容任务 <span aria-hidden="true">→</span>';
      }
      const projects = [
        ...summary.projects.map(item=>({title:item.product || item.task_uid, meta:'内容任务 · v'+item.version, path:item.path, label:item.label, tone:item.tone})),
        ...videoDetails.filter(item=>!item.result).map(item=>{
          const attempt = (item.attempts || []).filter(row=>row.input_version === item.version).at(-1);
          const label = {processing:'处理中',validation_failed:'检查失败',failed:'生成失败',result_unconfirmed:'结果待确认'}[attempt?.status] || '待补资料';
          return {title:item.input?.product || '未命名视频任务',meta:'视频任务 · v'+item.version+' · '+time(item.updated_at),path:'/creative?task='+encodeURIComponent(item.task_uid),label,tone:attempt?.status === 'processing'?'blue':'warn'};
        })
      ];
      node('wbActiveCount').textContent = Math.min(projects.length,4) + ' 项';
      node('wbProjects').innerHTML = projects.length ? projects.slice(0,4).map(item=>'<a class="wb-project" href="'+safe(item.path)+'"><div><strong title="'+safe(item.title)+'">'+safe(item.title)+'</strong><small>'+safe(item.meta)+'</small></div>'+badge(item.label,item.tone)+'</a>').join('') : empty('尚无进行中的项目，先保存一条内容任务。','/creative','新建任务');
      node('wbProjects').nextElementSibling.textContent = projects.length ? '内容待办与最近 4 条视频任务中的未完成项，显示前 ' + Math.min(projects.length,4) + ' 项。' : '任务会保留输入、成果和历史版本。';
      renderWeek(summary);
      node('wbStructureValue').textContent = '—';
      node('wbStructureMessage').innerHTML = '<strong>分类待接入</strong><p>当前记录未保存口播、产品、探店等内容类型，暂时无法统计占比。</p><a href="/feedback">查看发布记录 →</a>';
      node('wbStructureDonut').setAttribute('aria-label','尚无可统计的内容分类；不显示示例占比');
      const entries = [
        ...drafts.map(item=>({title:item.topic || '未命名研究稿',at:item.updated_at,label:'研究稿 · v'+(item.versions?.at(-1)?.version || 0),source:item.versions?.at(-1)?.source === 'demo'?'演示':item.versions?.at(-1)?.source === 'llm'?'模型生成':'手动',path:'/draft?id='+encodeURIComponent(item.draft_uid),tone:'blue'})),
        ...reviews.map(item=>({title:item.goal || '未命名审阅',at:item.created_at,label:'已审阅',source:item.source === 'demo'?'演示':'成片审阅',path:'/media-review?id='+encodeURIComponent(item.review_uid),tone:'mint'})),
        ...advices.map(item=>({title:item.status_json?.business || '运营建议',at:item.created_at,label:item.draft?'草稿':'已分析',source:item.source === 'demo'?'演示':'运营建议',path:'/advice?id='+encodeURIComponent(item.advice_uid),tone:item.draft?'':'mint'})),
        ...summary.records.map(item=>({title:item.snapshot_json?.product || item.platform_post_id,at:item.registered_at,label:'已登记发布',source:platformName(item.platform)+' · '+(item.source === 'manual'?'手动登记':'本机登记'),path:'/feedback?record='+encodeURIComponent(item.record_uid),tone:'mint'})),
        ...videoTasks.map(item=>({title:(()=>{try{return JSON.parse(item.input_json || '{}').product || '视频任务';}catch{return '视频任务';}})(),at:item.updated_at,label:'视频任务 · v'+item.current_version,source:'本机保存',path:'/creative?task='+encodeURIComponent(item.task_uid),tone:'blue'}))
      ].sort((a,b)=>(at(b.at)||0)-(at(a.at)||0));
      node('wbRecentRows').innerHTML = entries.length ? entries.slice(0,6).map(item=>'<tr><td data-label="时间">'+safe(time(item.at))+'</td><td data-label="条目"><a href="'+safe(item.path)+'" title="'+safe(item.title)+'">'+safe(item.title)+'</a></td><td data-label="状态">'+badge(item.label,item.tone)+'</td><td data-label="来源">'+safe(item.source)+'</td><td data-label="操作"><a class="wb-view" href="'+safe(item.path)+'">查看 →</a></td></tr>').join('') : '<tr><td class="wb-table-empty" colspan="5">'+empty('还没有本机工作记录。保存一个主题或任务后会出现在这里。','/creative','新建任务')+'</td></tr>';
      node('wbRecentCount').textContent = '显示最近 ' + Math.min(entries.length,6) + ' 条；研究稿、审阅、建议与视频任务各读取最近 30 条。';
      node('wbReadAt').textContent = '业务日 ' + operations.business_date + ' · 本机保存与发布登记';
      node('wbReadStatus').textContent = '本机记录 · 刚刚更新';
      node('wbError').hidden = true;
    } catch (error) {
      if (seq !== sequence) return;
      node('wbReadStatus').textContent = '读取失败';
      node('wbError').textContent = error.message + '。保留上次显示，请点击刷新重试。';
      node('wbError').hidden = false;
    } finally { if (seq === sequence) node('wbRefresh').disabled = false; }
  }
  node('wbRefresh').onclick = loadWorkbench;
  loadWorkbench();
})();

// FI-F1：本地提醒（仅应用内；GET/POST 同源 token）。
(() => {
  if (!$('reminderPanel')) return;
  const state = {items: [], editing: null, editVersion: 0, baseline: '', token: null,
    session: 0, listSeq: 0, targetSeq: 0, subSeq: 0, bindingEdit: 0,
    requestSeq: 0, busy: 0, errorSeq: 0, errorOwner: '', savedDue: null};
  const input = () => ({title: $('reminderTitle').value, note: $('reminderNote').value,
    due: $('reminderDue').value, kind: $('reminderKind').value,
    target: $('reminderTarget').value, sub: $('reminderSub').value,
    occurrence: $('reminderOccurrence')?.value || '0'});
  const field = () => JSON.stringify(input());
  const dirty = () => field() !== state.baseline;
  function setError(text, owner = 'form') {
    state.errorSeq++; state.errorOwner = owner;
    $('reminderError').textContent = text || ''; $('reminderError').hidden = !text;
  }
  const pad = n => String(n).padStart(2, '0');
  function localInput(epoch) {
    const d = new Date(epoch * 1000);
    return `${String(d.getFullYear()).padStart(4, '0')}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}` +
      (d.getMilliseconds() ? '.' + String(d.getMilliseconds()).padStart(3, '0') : '');
  }
  function timeCandidates(value) {
    const m = /^(\d{4,6})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?$/.exec(value);
    if (!m) return [];
    const parts = [+m[1], +m[2]-1, +m[3], +m[4], +m[5], +(m[6] || 0), +((m[7] || '').padEnd(3, '0'))];
    if (parts[1] < 0 || parts[1] > 11 || parts[2] < 1 || parts[2] > 31 || parts[3] > 23 || parts[4] > 59 || parts[5] > 59) return [];
    const wall = new Date(0); wall.setUTCFullYear(parts[0], parts[1], parts[2]); wall.setUTCHours(...parts.slice(3));
    const offsets = new Set();
    for (let hours = -48; hours <= 48; hours += 6) offsets.add(new Date(wall.getTime() + hours * 3600000).getTimezoneOffset());
    return [...offsets].map(offset => wall.getTime() + offset * 60000).filter(epoch => {
      const d = new Date(epoch);
      return [d.getFullYear(), d.getMonth(), d.getDate(), d.getHours(), d.getMinutes(), d.getSeconds(), d.getMilliseconds()]
        .every((part, i) => part === parts[i]);
    }).sort((a, b) => a - b);
  }
  function selectedTime() {
    const candidates = timeCandidates($('reminderDue').value);
    const index = Math.min(Number($('reminderOccurrence')?.value || 0), candidates.length - 1);
    return {candidates, epoch: candidates[index]};
  }
  function describeTime(epoch) {
    const d = new Date(epoch), offset = -d.getTimezoneOffset();
    return `${localInput(epoch / 1000)} UTC${offset < 0 ? '-' : '+'}${pad(Math.floor(Math.abs(offset)/60))}:${pad(Math.abs(offset)%60)}（${d.toISOString()}）`;
  }
  function previewTime(savedEpoch) {
    const candidates = timeCandidates($('reminderDue').value), select = $('reminderOccurrence');
    if (select) {
      const previous = select.value;
      select.innerHTML = candidates.map((epoch, i) => `<option value="${i}">${esc(describeTime(epoch))}</option>`).join('');
      const hit = candidates.findIndex(epoch => epoch === Math.round(savedEpoch * 1000));
      select.value = String(hit >= 0 ? hit : Math.min(Number(previous || 0), Math.max(0, candidates.length - 1)));
      select.disabled = candidates.length < 2;
    }
    if ($('reminderTimeChoice')) $('reminderTimeChoice').hidden = candidates.length < 2;
    if ($('reminderTimePreview')) $('reminderTimePreview').textContent = !$('reminderDue').value ? '' :
      candidates.length ? '实际保存时刻：' + describeTime(selectedTime().epoch) : '本地时间无效或在该时区不存在，请重新选择。';
  }
  async function api(path, body) {
    let options = {};
    if (body !== undefined) {
      const serialized = JSON.stringify(body);
      if (new TextEncoder().encode(serialized).length > 65536) throw new Error('请求超过 65536 字节；未发送，请缩短输入。');
      if (!state.token) state.token = fetch('/api/state?mode=live').then(async response => {
        if (!response.ok) throw new Error('本机连接失败');
        return (await response.json()).token;
      }).catch(error => { state.token = null; throw error; });
      options = {method: 'POST', headers: {'Content-Type': 'application/json', 'X-Radar-Token': await state.token}, body: serialized};
    }
    const response = await fetch(path, options), data = await response.json();
    if (!response.ok) { const error = new Error(data.error || '请求失败'); error.status = response.status; throw error; }
    return data;
  }
  function setBusy(owner) {
    state.busy = owner; $('reminderSave').disabled = Boolean(owner);
    render();
  }
  function newSession() {
    state.session++; state.targetSeq++; state.subSeq++; setBusy(0);
    return state.session;
  }
  const owns = (owner, session) => state.busy === owner && state.session === session;
  function render() {
    $('reminderCount').textContent = `${state.items.length} 条`;
    $('reminderClock').textContent = '本地时间：' + new Date().toLocaleString('zh-CN', {timeZoneName: 'short'});
    const list = $('reminderList');
    list.innerHTML = state.items.length ? state.items.map(item => {
      const parent = `${item.target_uid} / ${item.target_kind === 'draft_version' ? 'v' : ''}${item.target_sub_id}`;
      const href = item.target_kind === 'advice_action' ? '/advice?id=' + encodeURIComponent(item.target_uid) :
        '/draft?id=' + encodeURIComponent(item.target_uid);
      const versionLink = item.target_kind === 'draft_version' ? ` · <a href="/api/ops/draft/export?id=${encodeURIComponent(item.target_uid)}&version=${encodeURIComponent(item.target_sub_id)}">v${esc(item.target_sub_id)} 导出</a>` : '';
      return `<article class="reminder-card" data-uid="${esc(item.uid)}"><div><strong>${esc(item.title)}</strong><p>${esc(item.note || '无备注')}</p>
        <p>${esc(item.state_label)} · ${esc(new Date(item.due_at * 1000).toLocaleString('zh-CN', {timeZoneName:'short'}))}</p>
        <p>${item.parent_available === false ? '关联对象不可用 · ' : ''}${esc(item.parent?.title || '')} · ${esc(parent)} · <a href="${href}">查看父对象</a>${versionLink}</p></div>
        <div class="reminder-actions"><button type="button" class="secondary" data-act="edit">编辑</button>
        <button type="button" class="secondary" data-act="done" ${item.status === 'done' || state.busy ? 'disabled' : ''}>完成</button>
        <button type="button" class="secondary" data-act="cancelled" ${item.status === 'cancelled' || state.busy ? 'disabled' : ''}>取消</button></div></article>`;
    }).join('') : '<p class="screen-empty">还没有本地提醒</p>';
    list.querySelectorAll('[data-act]').forEach(button => { button.onclick = () => {
      const item = state.items.find(row => row.uid === button.closest('[data-uid]').dataset.uid);
      return button.dataset.act === 'edit' ? edit(item) : transition(item, button.dataset.act);
    }; });
  }
  async function refresh(silent = false) {
    const seq = ++state.listSeq, session = state.session, errorSeq = state.errorSeq;
    try {
      const data = await api('/api/ops/reminders/list');
      if (seq !== state.listSeq) return;
      state.items = data.items || []; render();
      if (state.session === session && state.errorSeq === errorSeq && state.errorOwner === 'list') setError('');
    } catch (error) {
      if (!silent && seq === state.listSeq && session === state.session && errorSeq === state.errorSeq) setError(error.message + '；保留上次列表。', 'list');
    }
  }
  function adoptBindingBaseline(revision) {
    if (revision !== state.bindingEdit || state.editing) return;
    const base = JSON.parse(state.baseline), current = input();
    ['kind', 'target', 'sub'].forEach(key => { base[key] = current[key]; });
    state.baseline = JSON.stringify(base);
  }
  async function loadTargets(options = {}) {
    const seq = ++state.targetSeq, session = state.session, kind = $('reminderKind').value, revision = state.bindingEdit;
    state.subSeq++;
    const fresh = () => session === state.session && seq === state.targetSeq && kind === $('reminderKind').value;
    try {
      const data = await api(kind === 'advice_action' ? '/api/ops/advice/list' : '/api/ops/draft/list');
      if (!fresh()) return;
      const rows = Array.isArray(data) ? data : data.advices;
      if (!Array.isArray(rows)) throw new Error('父对象列表格式无效');
      const target = $('reminderTarget'), wanted = options.target ?? target.value;
      const listed = rows.filter(row => !row.simulated);
      target.innerHTML = listed.map(row => `<option value="${esc(row.advice_uid || row.draft_uid)}">${esc(row.topic || row.status_json?.business || row.advice_uid || row.draft_uid)}</option>`).join('');
      if (state.editing && ![...target.options].some(option => option.value === wanted)) target.innerHTML += `<option value="${esc(wanted)}">${esc(wanted)}（关联对象不可用）</option>`;
      if ([...target.options].some(option => option.value === wanted)) target.value = wanted;
      await loadSub({sub: options.sub, adopt: options.adopt, revision});
      if (fresh() && options.adopt) adoptBindingBaseline(revision);
    } catch (error) { if (fresh()) setError('父对象读取失败：' + error.message); }
  }
  async function loadSub(options = {}) {
    const seq = ++state.subSeq, session = state.session, kind = $('reminderKind').value, uid = $('reminderTarget').value;
    const fresh = () => session === state.session && seq === state.subSeq && kind === $('reminderKind').value && uid === $('reminderTarget').value;
    const sub = $('reminderSub');
    if (!uid) { sub.innerHTML = ''; return; }
    try {
      const data = await api((kind === 'advice_action' ? '/api/ops/advice?id=' : '/api/ops/draft?id=') + encodeURIComponent(uid));
      if (!fresh()) return;
      const wanted = options.sub ?? sub.value;
      const rows = kind === 'advice_action' ? (data.result_json?.week_actions || []).map(row => ({value:row.id, label:row.action || row.id})) :
        (data.versions || []).map(row => ({value:String(row.version), label:'v' + row.version}));
      sub.innerHTML = rows.map(row => `<option value="${esc(row.value)}">${esc(row.label)}</option>`).join('');
      if (state.editing && ![...sub.options].some(option => option.value === wanted)) sub.innerHTML += `<option value="${esc(wanted)}">${esc(wanted)}（原绑定）</option>`;
      if ([...sub.options].some(option => option.value === wanted)) sub.value = wanted;
      if (options.adopt) adoptBindingBaseline(options.revision);
    } catch (error) { if (fresh()) setError('动作/版本读取失败：' + error.message); }
  }
  async function edit(item) {
    if (dirty() && !confirm('当前提醒输入有未保存修改，切换会覆盖；继续？')) return;
    const before = field(), session = newSession();
    try {
      const detail = await api('/api/ops/reminders?id=' + encodeURIComponent(item.uid));
      if (session !== state.session) return;
      if (field() !== before && !confirm('等待期间有新的提醒编辑，打开该提醒会覆盖；继续？')) return;
      if (session !== state.session) return;
      state.editing = detail.uid; state.editVersion = detail.row_version;
      $('reminderTitle').value = detail.title; $('reminderNote').value = detail.note || '';
      $('reminderDue').value = localInput(detail.due_at); $('reminderKind').value = detail.target_kind;
      $('reminderTarget').innerHTML = `<option value="${esc(detail.target_uid)}">${esc(detail.target_uid)}</option>`;
      $('reminderSub').innerHTML = `<option value="${esc(detail.target_sub_id)}">${esc(detail.target_sub_id)}</option>`;
      ['reminderKind','reminderTarget','reminderSub'].forEach(id => { $(id).disabled = true; });
      previewTime(detail.due_at); state.savedDue = {value: $('reminderDue').value, occurrence: input().occurrence, epoch: detail.due_at};
      state.baseline = field(); setError('');
      $('reminderSave').textContent = '保存修改'; $('reminderCancelEdit').hidden = false;
      loadTargets({target: detail.target_uid, sub: String(detail.target_sub_id)});
    } catch (error) { if (session === state.session) setError(error.message + '；当前输入保留。'); }
  }
  function reset() {
    newSession(); state.editing = null; state.editVersion = 0; state.savedDue = null;
    $('reminderForm').reset(); $('reminderTarget').innerHTML = ''; $('reminderSub').innerHTML = '';
    ['reminderKind','reminderTarget','reminderSub'].forEach(id => { $(id).disabled = false; });
    $('reminderSave').textContent = '创建提醒'; $('reminderCancelEdit').hidden = true;
    previewTime(); state.baseline = field(); setError(''); loadTargets({adopt: true});
  }
  async function save(event) {
    event.preventDefault(); if (state.busy) return;
    previewTime(); const submittedInput = input(), time = selectedTime();
    if (!time.candidates.length) { setError('本地时间无效或在该时区不存在，请重新选择。'); return; }
    if (time.candidates.length > 1 && !confirm('该本地时间出现两次，本次使用：' + describeTime(time.epoch) + '。可取消后选择另一偏移；继续保存？')) return;
    const due = state.savedDue && state.savedDue.value === submittedInput.due && state.savedDue.occurrence === submittedInput.occurrence ? state.savedDue.epoch : time.epoch / 1000;
    if (due < 0 || due > 253402300799) { setError('到期时间超出允许范围'); return; }
    if (!submittedInput.title.trim() || [...submittedInput.title].length > 200 || [...submittedInput.note].length > 1000) { setError('标题需 1–200 字、备注至多 1000 字'); return; }
    const editing = state.editing, session = state.session, submitted = JSON.stringify(submittedInput);
    const payload = editing ? {uid: editing, expected_row_version: state.editVersion, title: submittedInput.title, note: submittedInput.note, due_at: due} :
      {title: submittedInput.title, note: submittedInput.note, due_at: due, target_kind: submittedInput.kind, target_uid: submittedInput.target,
        target_sub_id: submittedInput.kind === 'draft_version' ? Number(submittedInput.sub) : submittedInput.sub};
    const owner = ++state.requestSeq; setBusy(owner); setError('');
    try {
      const result = await api('/api/ops/reminders/' + (editing ? 'update' : 'create'), payload);
      if (!owns(owner, session)) { refresh(true); return; }
      state.baseline = submitted;
      if (field() === submitted) reset();
      else if (!editing && ['kind','target','sub'].some(key => input()[key] !== submittedInput[key])) {
        // A changed binding belongs to a new reminder, never to the acknowledged record.
        state.savedDue = null;
      }
      else {
        state.editing = result.uid; state.editVersion = result.row_version;
        state.savedDue = {value:submittedInput.due, occurrence:submittedInput.occurrence, epoch:due};
        ['reminderKind','reminderTarget','reminderSub'].forEach(id => { $(id).disabled = true; });
        $('reminderSave').textContent = '保存修改'; $('reminderCancelEdit').hidden = false;
      }
      await refresh(true);
    } catch (error) { if (owns(owner, session)) setError(error.status === 409 ? '提醒已被其他窗口更新，请重新打开并核对版本；当前输入保留。' : error.message); }
    finally { if (owns(owner, session)) setBusy(0); }
  }
  async function transition(item, status) {
    if (state.busy) return;
    const session = state.session, owner = ++state.requestSeq;
    const version = state.editing === item.uid ? state.editVersion : item.row_version;
    setBusy(owner); setError('');
    try {
      const result = await api('/api/ops/reminders/update', {uid:item.uid, expected_row_version:version, status});
      if (owns(owner, session) && state.editing === item.uid) state.editVersion = result.row_version;
      await refresh(true);
    } catch (error) { if (owns(owner, session)) setError(error.status === 409 ? '提醒已被其他窗口更新，请重新打开并核对版本；当前输入保留。' : error.message); }
    finally { if (owns(owner, session)) setBusy(0); }
  }
  $('reminderKind').onchange = () => { state.bindingEdit++; return loadTargets(); };
  $('reminderTarget').onchange = () => { state.bindingEdit++; return loadSub(); };
  $('reminderSub').onchange = () => { state.bindingEdit++; };
  $('reminderDue').oninput = () => previewTime(); $('reminderDue').onchange = () => previewTime();
  if ($('reminderOccurrence')) $('reminderOccurrence').onchange = () => previewTime();
  $('reminderForm').onsubmit = save;
  $('reminderCancelEdit').onclick = () => { if (!dirty() || confirm('当前提醒有未保存修改，取消编辑会丢弃；继续？')) reset(); };
  $('reminderRefresh').onclick = () => refresh();
  reset(); refresh();
})();

/* Read-only task/diagnosis evidence, using existing public responses only. */
(()=>{
 const main=document.getElementById('workbench');if(!main)return;
 const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const area=document.createElement('div');area.innerHTML='<div class="ice-home-grid"><section class="ice-card"><h2>账号诊断摘要</h2><div id="iceDiagnosis">读取中…</div><p class="ice-muted">自有指标由你提供，尚未经平台核实。</p></section><section class="ice-card"><h2>系统状态</h2><div id="iceSystem">读取中…</div></section></div><section class="ice-card"><h2>最近创作成果</h2><div id="iceArtifacts"></div></section>';
 main.querySelector('.wb-library').before(area);
 const read=async p=>{const r=await fetch(p);if(!r.ok)throw Error('资料读取失败');return r.json();};
 async function refresh(){try{
  const [account,tasks,state]=await Promise.all(['/api/agent/account','/api/agent/tasks','/api/state?mode=live'].map(read));
  const latest=tasks.length?await read('/api/agent/task?id='+encodeURIComponent(tasks[0].task_uid)):null;
  const strategy=account.strategy||{},data=strategy.data||{};
  document.getElementById('iceDiagnosis').innerHTML='<dl class="ice-info"><dt>定位表达</dt><dd>'+esc(data.direction||'资料缺口：请补充账号定位')+'</dd><dt>真实资源</dt><dd>'+esc(data.resources||'资料缺口：请补充拍摄资源')+'</dd><dt>作品表现比较</dt><dd>门槛待配置；暂不输出比较结论。</dd><dt>表现趋势</dt><dd>门槛待配置；暂不输出趋势结论。</dd></dl>';
  const access=state.access||{};
  document.getElementById('iceSystem').innerHTML='<dl class="ice-info"><dt>接口调用</dt><dd>'+(access.active?'开启':access.enabled?'已停止':'已关闭')+'</dd><dt>额度上限</dt><dd>'+esc(access.limit == null ? '—' : '$'+access.limit)+'</dd><dt>已用情况</dt><dd>'+esc(access.spent == null ? '—' : '$'+access.spent)+'</dd><dt>最近备份</dt><dd>—</dd><dt>数据位置</dt><dd>本机；具体目录未提供</dd></dl><p class="ice-muted">读取状态不触发探针或模型调用。</p>';
  if(latest){
   const a=latest.attempts.filter(a=>a.input_version===latest.version||(latest.result&&a.input_version<=latest.version)).at(-1),status={processing:'处理中',success:'成功',validation_failed:'失败',failed:'失败',result_unconfirmed:'结果未确认'}[a?.status]||'待补资料';
   document.getElementById('wbToday').innerHTML='<dl class="ice-info"><dt>自有账号</dt><dd>'+esc(latest.account.label)+'</dd><dt>运营目标</dt><dd>'+esc(latest.input.goal)+'</dd><dt>策略版本</dt><dd>v'+latest.strategy.version+' · '+(latest.strategy.confirmed?'已确认':'草稿')+'</dd></dl><div class="ice-home-stages">'+['账号诊断','选题与参考','视频资料','分析与创作','审核与反馈'].map((n,i)=>'<a href="'+['/strategy','/research','/creative','/creative','/feedback'][i]+'">'+n+'<br><span class="ice-tag">'+(i===3?status:i===2?'已关联':'未测')+'</span></a>').join('')+'</div><p class="ice-muted">接下来：查看已保存资料与成果，再决定是否补充或评审。未提供记录的阶段不推定已完成。</p><a class="primary" href="/creative?task='+latest.task_uid+'">继续：分析与创作</a>';
   const items=Object.keys(latest.result?.report?.deliverables||{});
   document.getElementById('iceArtifacts').innerHTML=items.length?'<div class="ice-table-scroll"><table class="ice-table"><thead><tr><th>标题</th><th>类型</th><th>版本</th><th>状态</th></tr></thead><tbody>'+items.map(k=>'<tr><td><a href="/creative?task='+latest.task_uid+'">'+esc(latest.input.product)+'</a></td><td>'+esc({shooting:'真人拍摄改编稿',video_prompt:'AI 视频提示词',writing_prompt:'写稿提示词'}[k])+'</td><td>v'+latest.version+'</td><td>已保存 · 模型推断</td></tr>').join('')+'</tbody></table></div>':'<p class="ice-muted">当前任务尚无生成成果，输入和历史版本已保留。</p>';
  }else{document.getElementById('wbToday').innerHTML='<p class="ice-muted">还没有保存的运营任务。从本地视频和真实业务资料开始。</p><a class="primary" href="/creative">新建任务</a>';document.getElementById('iceArtifacts').textContent='尚无创作成果。';}
 }catch(e){document.getElementById('iceDiagnosis').textContent='资料读取失败；请确认本机服务仍在运行。';document.getElementById('iceSystem').textContent='—';document.getElementById('wbToday').textContent='任务读取失败；请刷新重试。';document.getElementById('iceArtifacts').textContent='成果读取失败。';}}
 document.getElementById('wbRefresh').addEventListener('click',refresh);refresh();
})();
