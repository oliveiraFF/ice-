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

/* Read-only overview of existing records. Refresh never generates or collects. */
(() => {
  if (!document.getElementById('workbench')) return;
  const node = id => document.getElementById(id);
  const safe = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const icon = name => RadarIcons.svg(name);
  const empty = (text, path, label) => '<p class="wb-empty">' + text + (path ? ' <a href="' + path + '">' + label + ' →</a>' : '') + '</p>';
  const sourceLabel = item => item.source === 'llm' ? '模型生成' : item.source === 'demo' ? '演示' : '未分析';
  let entries = [], filter = 'all', sequence = 0;
  function renderCards() {
    const query = node('wbQuery').value.trim().toLowerCase();
    const shown = entries.filter(item => (filter === 'all' || item.kind === filter) && (item.title + ' ' + item.text).toLowerCase().includes(query));
    node('wbRecordCount').textContent = shown.length + ' 条记录 · 各类仅载入最近 30 条';
    node('wbCards').innerHTML = shown.length ? shown.map(item =>
      '<a class="wb-card" href="' + item.path + '?id=' + encodeURIComponent(item.uid) + '">' +
      '<div class="wb-preview ' + item.kind + '"><div class="wb-card-tags"><span>' + item.label + '</span><span class="demo">' + sourceLabel(item) + '</span></div>' +
      '<div class="wb-paper"><span>' + item.caption + '</span><h3>' + safe(item.title) + '</h3><p>' + safe(item.text || '打开查看输入、来源与历史记录。') + '</p></div></div>' +
      '<div class="wb-card-body"><strong title="' + safe(item.title) + '">' + safe(item.title) + '</strong><p><span>' + safe(item.meta) + '</span><span>查看记录 ↗</span></p></div></a>'
    ).join('') : empty(query || filter !== 'all' ? '没有匹配的记录，试试其他分类或关键词。' : '还没有内容记录。先从一个明确主题开始。', '/draft', '新建研究稿');
  }
  function row(path, title, detail, label, state, symbol) {
    return '<a class="wb-row" href="' + safe(path) + '"><span class="wb-row-icon">' + icon(symbol || 'file-text') + '</span><div><strong title="' + safe(title) + '">' + safe(title) + '</strong><small>' + safe(detail) + '</small></div><span class="wb-status ' + (state || '') + '">' + safe(label) + '</span></a>';
  }
  async function read(path) {
    const response = await fetch(path);
    if (!response.ok) throw new Error('读取失败：' + path);
    return response.json();
  }
  async function loadWorkbench() {
    const seq = ++sequence;
    const button = node('wbRefresh'); button.disabled = true;
    try {
      const paths = ['/api/ops/dashboard', '/api/ops/advice/list', '/api/ops/draft/list', '/api/ops/media-review/list'];
      const [operations, advices, drafts, reviews] = await Promise.all(paths.map(read));
      const latest = advices.find(item => item.result_json && (item.result_json.week_actions || []).length);
      const advice = latest ? await read('/api/ops/advice?id=' + encodeURIComponent(latest.advice_uid)) : null;
      if (seq !== sequence) return;
      const actions = advice ? (advice.result_json.week_actions || []).map(action => {
        const progress = (advice.actions || []).find(item => item.action_id === action.id);
        return {text:action.action, next:action.next || action.why || '打开建议查看条件与依据', state:progress ? progress.status : 'todo'};
      }) : [];
      const counts = operations.tasks.counts;
      const values = [actions.filter(item => item.state !== 'done').length, drafts.length, counts.pending_review, counts.approved_unpublished, operations.published.count];
      values.forEach((value, i) => { node('wbCount' + i).textContent = value; });
      if(node('iceTodoCount'))node('iceTodoCount').textContent=values[0];
      node('wbDate').textContent = '业务日 ' + operations.business_date;
      node('wbReadAt').textContent = '本地记录 · 刚刚刷新';
      const todo = [...(operations.actions || []).map(item => row(item.target, item.reason, '来自当前运营记录', '去处理', '', 'arrow'))];
      if (counts.pending_review) todo.push(row('/script', '审阅 ' + counts.pending_review + ' 个待审版本', '查看稿件内容、依据与待补资料', '待审核', '', 'file-text'));
      if (counts.approved_unpublished) todo.push(row('/feedback', '登记 ' + counts.approved_unpublished + ' 个已审任务', '仅登记你已经实际发布的作品', '待登记', '', 'calendar'));
      if (!operations.strategy.confirmed) todo.push(row('/strategy', operations.strategy.configured ? '检查并确认账号策略' : '补充业务与账号策略', '方向、受众、资源与排除项', '待确认', '', 'compass'));
      node('wbToday').dataset.followupCount = todo.length;
      node('wbWeek').innerHTML = actions.length ? actions.slice(0, 4).map(item => row('/advice?id=' + encodeURIComponent(advice.advice_uid), item.text, item.next, {todo:'待开始',doing:'进行中',done:'已完成'}[item.state] || '待开始', item.state, 'calendar')).join('') : empty('还没有行动建议。填写业务现状，建立下一步。', '/advice', '获取运营建议');
      node('wbWeekNote').textContent = advice ? '最近建议 · ' + new Date(advice.created_at * 1000).toLocaleDateString('zh-CN') + ' · 未提供周排期（按建议日期展示，不代表本周已排期）' : '建议仅供参考，不代表已经排进本周。';
      entries = [
        ...drafts.map(item => {
          const version = (item.versions || []).slice(-1)[0], content = version ? version.content_json : {};
          return {kind:'draft', label:'研究稿', caption:'RESEARCH DRAFT', path:'/draft', uid:item.draft_uid, title:item.topic || '未命名研究稿', text:content.draft_markdown || content.summary || '', meta:version ? 'v' + version.version + ' · 已保存' : '主题草稿 · 未生成', source:version ? version.source : 'draft', at:item.updated_at};
        }),
        ...reviews.map(item => ({kind:'review',label:'成片审阅',caption:'MEDIA REVIEW',path:'/media-review',uid:item.review_uid,title:item.goal || '未命名审阅',text:item.summary || '',meta:((item.scope_json || {}).frames || []).length + ' 张采样帧',source:item.source,at:item.created_at})),
        ...advices.map(item => ({kind:'advice',label:'运营建议',caption:'OPERATIONS NOTE',path:'/advice',uid:item.advice_uid,title:(item.status_json || {}).business || '业务现状草稿',text:((item.result_json || {}).week_actions || []).map(action => action.action).join('；'),meta:item.draft ? '现状草稿 · 未分析' : '建议与行动跟进',source:item.source,at:item.created_at}))
      ].sort((a,b) => b.at - a.at);
      renderCards(); node('wbError').hidden = true;
    } catch (error) {
      if (seq !== sequence) return;
      node('wbError').textContent = error.message + '。保留上次显示；尚未读取的统计显示为“—”，请重试。';
      node('wbError').hidden = false;
    } finally { if (seq === sequence) button.disabled = false; }
  }
  document.querySelectorAll('[data-wb-filter]').forEach(button => {
    button.onclick = () => {
      filter = button.dataset.wbFilter;
      document.querySelectorAll('[data-wb-filter]').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
      renderCards();
    };
  });
  node('wbQuery').addEventListener('input', renderCards);
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
