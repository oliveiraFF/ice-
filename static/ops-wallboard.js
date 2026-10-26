/* finesse · register=product · A=ICE gray-green · B=system CJK + tabular numerals · C=11-item rail with 16:9 KPI/pipeline/evidence board · D=manual/60s refresh only · E=workspace provenance and freshness · preserve ICE identity; change board composition and evidence material */
(() => {
  const el = id => document.getElementById(id);
  const ALLOWED_ROUTES = new Set(['/','/dashboard','/research','/draft','/feedback','/script']);
  const SOURCE_LABELS = new Map([
    ['presentation/ops-dashboard.json','运营指标'],
    ['presentation/status.json','流程状态'],
    ['work/topics/selections/daily.json','选题记录'],
    ['config/profile/account.profile.json','账号画像'],
    ['config/profile/audience.profile.json','受众画像'],
    ['config/profile/offer.profile.json','产品与承接'],
    ['config/strategy/strategy-brief.json','账号策略'],
    ['config/policies/topic-discovery.policy.json','策略门槛规则'],
    ['data/operations/current/account-snapshot.json','账号快照'],
    ['data/feedback/raw/post-metrics.json','作品指标'],
    ['data/topic-research/current/strategy-assessment.json','Agent 账号评估'],
    ['data/benchmarks/current/reference-bank.json','参考资料'],
    ['data/topic-research/current/pain-bank.json','痛点资料'],
    ['work/plans/daily.json','内容计划'],
    ['data/feedback/raw/published-posts.json','发布记录'],
    ['data/feedback/current/learning.json','复盘资料']
  ]);
  let lastViewModel = null;
  let refreshing = false;
  let workspaceTimeZone = 'UTC';

  function setText(node, value) {
    if (node) node.textContent = value == null ? '' : String(value);
  }
  function safeRoute(value) {
    return ALLOWED_ROUTES.has(value) ? value : null;
  }
  function friendlySource(value) {
    if (!value) return '来源未记录';
    const source = String(value);
    if (SOURCE_LABELS.has(source)) return SOURCE_LABELS.get(source);
    return /[/\\]/.test(source) || source.length > 60 ? '运营资料' : source;
  }
  function formatValue(value) {
    if (value === null || value === undefined) return '待接入';
    if (typeof value === 'number' && Number.isFinite(value)) return new Intl.NumberFormat('zh-CN').format(value);
    return '待接入';
  }
  function formatTime(value) {
    if (!value) return '时间未记录';
    const raw = String(value).trim();
    const sourceDate = raw.match(/^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2})(?::\d{2})?)?$/);
    if (sourceDate) return sourceDate[1] + (sourceDate[2] ? ' ' + sourceDate[2] : '');
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    try {
      return new Intl.DateTimeFormat('zh-CN', {year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',timeZone:workspaceTimeZone}).format(date);
    } catch (_) {
      return new Intl.DateTimeFormat('zh-CN', {year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',timeZone:'UTC'}).format(date);
    }
  }
  function create(tag, className, label) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (label !== undefined) node.textContent = label;
    return node;
  }
  function renderKpis(model) {
    const rows = Array.isArray(model.dashboard && model.dashboard.kpis) ? model.dashboard.kpis : [];
    for (const id of ['todo','in_progress','review','blocked']) {
      const row = rows.find(item => item.id === id);
      const value = row ? row.value : null;
      const valueNode = document.querySelector('[data-kpi="' + id + '"]');
      setText(valueNode, formatValue(value));
      if (valueNode) valueNode.classList.toggle('is-unavailable', value === null || value === undefined);
      const timeNode = document.querySelector('[data-kpi-updated="' + id + '"]');
      setText(timeNode, row && row.source
        ? friendlySource(row.source) + ' · ' + (row.updated_at ? formatTime(row.updated_at) : '时间未记录')
        : '来源时间待接入');
    }
  }
  function renderPipeline(model) {
    const pipeline = Array.isArray(model.dashboard && model.dashboard.pipeline) ? model.dashboard.pipeline : [];
    const list = el('pipelineList');
    list.replaceChildren();
    for (const item of pipeline) {
      const li = create('li','wallboard-pipeline-item');
      const label = create('span','',item.label || '运营环节');
      const heading = create('strong','',formatValue(item.value));
      heading.classList.toggle('is-unavailable', item.value === null || item.value === undefined);
      const detail = item.value === null || item.value === undefined
        ? (item.state === 'blocked' ? '流程未完成，暂无统计' : '数据源待接入')
        : (item.value === 0 ? '当前没有已记录条目' : '条已保存记录');
      const note = create('small','',detail);
      const href = safeRoute(item.href);
      if (href) {
        const link = create('a','wallboard-pipeline-link');
        link.href = href;
        link.append(label, heading, note);
        li.append(link);
      } else {
        li.append(label, heading, note);
      }
      list.append(li);
    }
    const stamp = model.dashboard && model.dashboard.freshness && model.dashboard.freshness.updated_at;
    setText(el('pipelineUpdated'), stamp ? '资料更新 ' + formatTime(stamp) : '数据时间待接入');
  }
  function renderAlerts(model) {
    const rows = Array.isArray(model.dashboard && model.dashboard.alerts) ? model.dashboard.alerts : [];
    const known = model.dashboard && model.dashboard.alerts_complete === true;
    const list = el('alertList');
    list.replaceChildren();
    setText(el('alertCount'), rows.length ? rows.length + ' 条提醒' : (known ? '已检查' : '待接入'));
    if (!rows.length) {
      const item = create('li','wallboard-empty',known ? '今日无阻塞' : '异常清单待接入；目前无法判断是否有阻塞');
      list.append(item);
      return;
    }
    for (const row of rows.slice(0,5)) {
      const item = create('li','wallboard-alert-item' + (/blocked|failed|error/i.test(row.state || '') ? ' is-blocked' : ''));
      item.append(create('span','wallboard-alert-mark',''));
      const content = create('div');
      content.append(create('strong','',row.title || '状态提醒'));
      if (row.detail) content.append(create('p','',row.detail));
      const href = safeRoute(row.href);
      if (href) {
        const link = create('a','', '查看详情');
        link.href = href;
        content.append(link);
      }
      item.append(content);
      list.append(item);
    }
  }
  function renderRecent(model) {
    const rows = Array.isArray(model.dashboard && model.dashboard.recent) ? model.dashboard.recent.slice(0,10) : [];
    const body = el('recentRows');
    body.replaceChildren();
    setText(el('recentCount'), rows.length ? '显示 ' + rows.length + ' 条' : '暂无活动记录');
    if (!rows.length) {
      const tr = create('tr');
      const td = create('td','wallboard-empty','暂无动态记录；有运行记录后会显示在这里。');
      td.colSpan = 5;
      tr.append(td);
      body.append(tr);
      return;
    }
    for (const row of rows) {
      const tr = create('tr');
      tr.append(create('td','',formatTime(row.time || row.updated_at)));
      tr.append(create('td','',row.title || row.run_id || '运营记录'));
      const statusCell = create('td');
      const state = create('span','wallboard-state' + (/blocked|failed|error/i.test(row.status || '') ? ' is-warning' : ''),row.status || '已记录');
      statusCell.append(state);
      tr.append(statusCell);
      tr.append(create('td','',friendlySource(row.source)));
      const actionCell = create('td');
      const href = safeRoute(row.href);
      if (href) {
        const link = create('a','', '查看');
        link.href = href;
        actionCell.append(link);
      } else {
        actionCell.textContent = '—';
      }
      tr.append(actionCell);
      body.append(tr);
    }
  }
  function appendFact(list, label, value, source, updatedAt, unavailableText = '待接入') {
    const item = create('div','wallboard-insight-fact');
    item.append(create('span','',label), create('strong','',value == null ? unavailableText : String(value)));
    item.append(create('small','',source ? friendlySource(source) + ' · ' + (updatedAt ? formatTime(updatedAt) : '时间未记录') : '来源时间待接入'));
    list.append(item);
  }
  function renderAccount(model) {
    const account = model.account || {};
    const profiles = Array.isArray(account.profiles) ? account.profiles : [];
    const strategy = account.strategy || {};
    const samples = Array.isArray(account.samples) ? account.samples : [];
    const blockers = Array.isArray(account.blockers) ? account.blockers : [];
    const ready = account.state === 'ready' && account.assessment && account.assessment.state === 'ready';
    const chip = el('accountState');
    setText(chip, ready ? '评估可读' : '资料待补');
    chip.classList.toggle('is-warning', !ready);
    setText(el('accountSummary'), ready
      ? '以下是 Agent 已保存、带证据引用的只读评估。页面不会重新推断或调整策略。'
      : '未满足确认或证据门槛时，只列出缺口，不展示表现结论，也不会自动运行 Agent。');

    const facts = el('accountFacts');
    facts.replaceChildren();
    const stateLabels = {confirmed:'已确认',needs_confirmation:'待人工确认',missing:'缺少资料'};
    for (const profile of profiles) {
      const state = stateLabels[profile.state] || '待接入';
      appendFact(facts, profile.label || '账号资料', state, profile.source, profile.updated_at);
    }
    appendFact(facts, '账号策略', stateLabels[strategy.state] || strategy.status || '待接入', strategy.source, strategy.updated_at);
    for (const sample of samples) {
      appendFact(facts, sample.label || '作品样本', sample.value == null ? null : formatValue(sample.value),
        sample.source, sample.updated_at);
    }

    const profileDetails = el('accountConfirmedProfile');
    profileDetails.replaceChildren();
    const confirmedItems = profiles.flatMap(profile => Array.isArray(profile.items) ? profile.items : [])
      .concat(Array.isArray(strategy.items) ? strategy.items : []);
    if (confirmedItems.length) {
      profileDetails.hidden = false;
      profileDetails.append(create('h3','', '已确认的账号与策略资料'));
      const list = create('ul');
      for (const item of confirmedItems) {
        const row = create('li','');
        row.textContent = (item.label || '資料') + '：' + (item.value || '—') + ' · ' +
          (item.source ? friendlySource(item.source) : '来源未记录') + ' · ' +
          (item.updated_at ? formatTime(item.updated_at) : '时间未记录');
        list.append(row);
      }
      profileDetails.append(list);
    } else {
      profileDetails.hidden = true;
    }

    const assessment = account.assessment || {};
    const assessmentPanel = el('accountAssessment');
    assessmentPanel.hidden = !(assessment.state === 'ready' && assessment.conclusion);
    if (!assessmentPanel.hidden) {
      setText(el('accountConclusion'), assessment.conclusion);
      const evidence = el('accountEvidence');
      evidence.replaceChildren();
      for (const item of (Array.isArray(assessment.evidence) ? assessment.evidence : [])) {
        const row = create('li','');
        row.textContent = [item.evidence_id, item.source_ref].filter(Boolean).join(' · ');
        evidence.append(row);
      }
    }

    const blockerList = el('accountBlockers');
    blockerList.replaceChildren();
    if (!blockers.length) {
      blockerList.append(create('li','wallboard-empty', ready ? '当前没有待补资料。' : 'Agent 尚未提供缺口清单。'));
    } else {
      for (const blocker of blockers.slice(0,8)) {
        const item = create('li','wallboard-blocker');
        item.append(create('strong','',blocker.message || '资料缺口'));
        if (blocker.required) item.append(create('p','',blocker.required));
        if (blocker.minimum != null) {
          item.append(create('small','',`当前 ${formatValue(blocker.current)} · 最低 ${formatValue(blocker.minimum)} · ${blocker.source ? friendlySource(blocker.source) : '来源未记录'} · ${blocker.updated_at ? formatTime(blocker.updated_at) : '时间未记录'}`));
        } else if (blocker.source) {
          item.append(create('small','',friendlySource(blocker.source) + ' · ' + (blocker.updated_at ? formatTime(blocker.updated_at) : '时间未记录')));
        }
        blockerList.append(item);
      }
    }
    const gate = account.strategy_adjustment_gate;
    setText(el('accountProvenance'), gate
      ? `策略调整门槛来自 ${gate.policy_id || 'Agent 策略规则'} ${gate.policy_version || ''}；最少可比公开作品 ${formatValue(gate.minimum_comparable_public_posts)}、执行版本 ${formatValue(gate.minimum_execution_variants)}。${gate.requires_persistent_weak_target_response ? '还需持续偏弱的目标反馈证据。' : ''}来源：${gate.source ? friendlySource(gate.source) : '来源未记录'} · ${gate.updated_at ? formatTime(gate.updated_at) : '时间未记录'}。`
      : '账号结论门槛未配置时，按规则只显示资料缺口。');
  }
  function renderWorkbench(model) {
    const workbench = model.workbench || {};
    const plan = workbench.plan || {};
    const state = workbench.state === 'ready';
    setText(el('workbenchState'), state ? '已连接' : '待接入');
    el('workbenchState').classList.toggle('is-warning', !state);
    const planStates = {ready:'可预览',blocked:'受阻',failed:'失败',not_generated:'未生成',draft:'草稿',complete:'已完成',completed:'已完成'};
    setText(el('workbenchPlanStatus'), planStates[plan.status] || plan.status || '待接入');
    setText(el('workbenchPlanSource'), plan.source
      ? friendlySource(plan.source) + ' · ' + (plan.updated_at ? formatTime(plan.updated_at) : '时间未记录')
      : '来源时间待接入');
    setText(el('workbenchPlanBlockers'), (Array.isArray(plan.blockers) ? plan.blockers : []).join('；'));

    const materials = el('workbenchMaterials');
    materials.replaceChildren();
    for (const material of (Array.isArray(workbench.materials) ? workbench.materials : [])) {
      const row = create('li','wallboard-material');
      row.append(create('span','',material.label || 'Agent 资料'));
      row.append(create('strong','',formatValue(material.value)));
      row.append(create('small','',material.source
        ? friendlySource(material.source) + ' · ' + (material.updated_at ? formatTime(material.updated_at) : '时间未记录')
        : '来源时间待接入'));
      materials.append(row);
    }
    if (!materials.children.length) materials.append(create('li','wallboard-empty','Agent 工作台资料待接入。'));

    const draft = workbench.draft;
    el('workbenchDraft').hidden = !(draft && typeof draft.text === 'string' && draft.text);
    if (!el('workbenchDraft').hidden) {
      setText(el('workbenchDraftText'), draft.text);
      setText(el('workbenchDraftSource'), draft.source
        ? friendlySource(draft.source) + ' · ' + (draft.updated_at ? formatTime(draft.updated_at) : '时间未记录')
        : '来源时间待接入');
    }

    const matches = Array.isArray(workbench.reference_matches) ? workbench.reference_matches : [];
    el('workbenchMatches').hidden = matches.length === 0;
    const matchList = el('workbenchMatchList');
    matchList.replaceChildren();
    for (const match of matches.slice(0,8)) {
      const row = create('li','');
      row.append(create('strong','',match.title || match.reference_id || '已保存参考'));
      row.append(create('span','',match.score == null ? '分数待接入' : formatValue(match.score)));
      const provenance = [match.platform, match.creator, match.source ? friendlySource(match.source) : '',
        match.updated_at ? formatTime(match.updated_at) : '时间未记录'].filter(Boolean).join(' · ');
      row.append(create('small','',provenance));
      matchList.append(row);
    }
    const lastRun = workbench.last_run;
    setText(el('workbenchEmpty'), lastRun
      ? `最近优化运行：${lastRun.run_id || '已记录'} · ${lastRun.updated_at ? formatTime(lastRun.updated_at) : '时间未记录'}`
      : '还没有可预览的优化运行记录；此页不会自动运行 Agent。');
    el('workbenchEmpty').hidden = Boolean(lastRun || draft || matches.length);
  }
  function render(model) {
    const workspace = model.workspace || {};
    if (typeof workspace.timezone === 'string' && workspace.timezone) workspaceTimeZone = workspace.timezone;
    const freshness = (model.dashboard || {}).freshness || {};
    lastViewModel = model;
    setText(el('connectionLabel'), workspace.connected ? '已连接' : '未连接');
    el('connectionDot').classList.toggle('is-connected', !!workspace.connected);
    el('connectionDot').classList.toggle('is-stale', freshness.state === 'incomplete');
    setText(el('lastRefresh'), '最近刷新 ' + formatTime(model.meta && model.meta.generated_at));
    const workspaceNotice = el('workspaceNotice');
    const notice = workspace.label === '合成演示数据'
      ? '当前显示合成演示数据，仅用于功能验收，不代表实际运营表现。'
      : (workspace.message || '');
    setText(workspaceNotice, notice);
    workspaceNotice.hidden = !notice;
    const freshnessNotice = el('freshnessNotice');
    const incomplete = workspace.connected && freshness.state !== 'ready';
    setText(freshnessNotice, incomplete
      ? '运营指标尚未就绪或部分资料缺失。页面只读取已有资料，不会自动生成指标或改写数据。'
      : '');
    freshnessNotice.hidden = !incomplete;
    renderKpis(model);
    renderPipeline(model);
    renderAlerts(model);
    renderRecent(model);
    renderAccount(model);
    renderWorkbench(model);
  }
  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    const button = el('refreshButton');
    button.disabled = true;
    setText(button, '刷新中…');
    try {
      const response = await fetch('/api/agent/view-model', {cache:'no-store',headers:{'Accept':'application/json'}});
      if (!response.ok) throw new Error('本地桥返回 ' + response.status);
      const model = await response.json();
      if (!model || typeof model !== 'object' || !model.dashboard || !model.workspace) {
        throw new Error('view model 格式无效');
      }
      render(model);
      el('connectionDot').classList.toggle('is-stale', !model.workspace.connected);
      if (!model.workspace.connected) setText(el('connectionLabel'), '未连接');
    } catch (_) {
      if (lastViewModel) {
        setText(el('connectionLabel'), '离线 · 显示上次数据');
        el('connectionDot').classList.remove('is-connected');
        el('connectionDot').classList.add('is-stale');
        setText(el('freshnessNotice'), '刷新失败，仍显示上次成功读取的数据；当前内容可能不是最新。');
        el('freshnessNotice').hidden = false;
      } else {
        render({workspace:{connected:false,label:'未连接',message:'本地数据桥暂时无法连接。'},
          dashboard:{kpis:[],pipeline:[],alerts:[],recent:[],freshness:{state:'not_connected'}},meta:{}});
        setText(el('connectionLabel'), '离线');
        el('connectionDot').classList.add('is-stale');
        setText(el('freshnessNotice'), '尚未读取到数据；请检查本机服务后重试。');
        el('freshnessNotice').hidden = false;
      }
    } finally {
      refreshing = false;
      button.disabled = false;
      setText(button, '刷新数据');
    }
  }
  el('refreshButton').addEventListener('click', refresh);
  document.addEventListener('agent-workspace-config-changed', refresh);
  el('fullscreenButton').addEventListener('click', async () => {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await document.documentElement.requestFullscreen();
      setText(el('fullscreenButton'), document.fullscreenElement ? '退出全屏' : '全屏');
    } catch (_) {
      setText(el('freshnessNotice'), '当前窗口不支持全屏显示。');
      el('freshnessNotice').hidden = false;
    }
  });
  document.addEventListener('fullscreenchange', () => {
    setText(el('fullscreenButton'), document.fullscreenElement ? '退出全屏' : '全屏');
  });
  refresh();
  window.setInterval(refresh, 60000);
})();
