(() => {
  const el = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fields = {
    direction: ['strategyDirection', '账号方向'],
    audience: ['strategyAudience', '受众'],
    resources: ['strategyResources', '真实资源 / 证明'],
    goal: ['strategyGoal', '阶段目标'],
    principles: ['strategyPrinciples', '内容原则'],
    exclusions: ['strategyExclusions', '排除项'],
    takeover: ['strategyTakeover', '承接方式'],
  };
  let token = '', strategy = null;
  const initial = fetch('/api/state?mode=live').then(async r => {
    if (!r.ok) throw new Error('本机连接失败，请重新打开页面');
    token = (await r.json()).token;
  });
  initial.catch(error => { el('strategyError').textContent = error.message; });

  async function request(path, body) {
    await initial;
    const response = await fetch(path, {
      method: body === null ? 'GET' : 'POST',
      headers: body === null ? {} : { 'Content-Type': 'application/json', 'X-Radar-Token': token },
      body: body === null ? undefined : JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '操作失败');
    return data;
  }

  function fill(data) {
    Object.entries(fields).forEach(([key, [id]]) => { el(id).value = (data || {})[key] || ''; });
    el('strategyExperiment').checked = (data || {}).experiment_allowed === true;
  }
  function collect() {
    const data = {};
    Object.entries(fields).forEach(([key, [id]]) => { data[key] = el(id).value.trim(); });
    data.experiment_allowed = el('strategyExperiment').checked;
    return data;
  }
  function render() {
    const data = (strategy && strategy.data) || {};
    fill(data);
    el('strategyStatus').textContent = strategy && strategy.confirmed
      ? '已确认 v' + strategy.version : '草稿 v' + ((strategy && strategy.version) || 0) + '（未确认）';
    el('confirmStrategy').disabled = !strategy || !strategy.version || !!strategy.confirmed;
  }
  async function load() {
    strategy = await request('/api/strategy', null);
    render();
  }
  el('saveStrategy').onclick = async () => {
    el('strategyError').textContent = '';
    try {
      strategy = await request('/api/strategy/save', { data: collect(), provenance: '页面填写',
                                                       expected_version: strategy ? strategy.version : 0 });
      render();
      el('strategyNotice').textContent = '已保存草稿 v' + strategy.version + '；确认后可用于正式任务。';
      el('strategyConfirmPanel').hidden = true;
    } catch (error) { el('strategyError').textContent = error.message; }
  };
  el('confirmStrategy').onclick = () => {
    if (!strategy) return;
    const data = strategy.data || {};
    el('strategyConfirmPanel').hidden = false;
    el('strategyConfirmPanel').innerHTML = '<h4>待确认内容 · v' + strategy.version + '</h4>' +
      Object.entries(fields).map(([key, [, label]]) =>
        '<p><strong>' + label + '</strong>：' + esc(data[key] || '') + '</p>').join('') +
      '<button id="confirmFinal" class="primary" type="button">确认以上内容</button>';
    el('confirmFinal').onclick = async () => {
      el('strategyError').textContent = '';
      try {
        strategy = await request('/api/strategy/confirm', { expected_version: strategy.version });
        render();
        el('strategyConfirmPanel').hidden = true;
        el('strategyNotice').textContent = '已确认 v' + strategy.version + '，正式任务门禁已打开。';
      } catch (error) {
        el('strategyConfirmPanel').hidden = true;
        el('strategyError').textContent = error.message;
      }
    };
  };
  load().catch(error => { el('strategyError').textContent = error.message; });
})();
