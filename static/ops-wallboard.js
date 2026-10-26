/* finesse · register=product · A=ICE gray-green · B=system CJK + tabular numerals · C=11-item rail with 16:9 KPI/pipeline/evidence board · D=manual/60s refresh only · E=workspace provenance and freshness · preserve ICE identity; change board composition and evidence material */
(() => {
  const el = id => document.getElementById(id);
  const ALLOWED_ROUTES = new Set(['/','/dashboard','/research','/draft','/feedback','/script']);
  const SOURCE_LABELS = new Map([
    ['presentation/ops-dashboard.json','运营指标'],
    ['presentation/status.json','流程状态'],
    ['work/topics/selections/daily.json','选题记录'],
    ['data/benchmarks/current/reference-bank.json','参考资料'],
    ['work/plans/daily.json','内容计划'],
    ['data/feedback/raw/published-posts.json','发布记录'],
    ['data/feedback/current/learning.json','复盘资料']
  ]);
  let lastViewModel = null;
  let refreshing = false;

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
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return new Intl.DateTimeFormat('zh-CN', {month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(date);
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
  function render(model) {
    const workspace = model.workspace || {};
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
