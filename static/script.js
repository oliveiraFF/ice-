(() => {
  const el = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let token = '', last = null, saved = null, strategy = null;
  let poolBatch = '', combo = null, pendingCandidate = null, planDirty = false, pendingSuggestion = null;
  const selectedRefs = new Set(), selectedPains = new Set();
  const initial = fetch('/api/state?mode=live').then(async r => {
    if (!r.ok) throw new Error('本机连接失败，请重新打开页面');
    token = (await r.json()).token;
  });
  initial.catch(error => { el('scriptError').textContent = error.message; });

  async function request(path, body) {
    await initial;
    const response = await fetch(path, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Radar-Token': token },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '操作失败');
    return data;
  }

  async function getJson(path) {
    await initial;
    const response = await fetch(path);
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '读取失败');
    return data;
  }

  function factRow(fact) {
    const data = fact || {};
    const row = document.createElement('div');
    row.className = 'script-fact-row';
    row.innerHTML = '<input class="fact-id" maxlength="20" placeholder="编号（可留空自动填）" value="' + esc(data.id || '') + '">' +
      '<input class="fact-content" maxlength="300" placeholder="事实内容" value="' + esc(data.content || '') + '">' +
      '<input class="fact-source" maxlength="120" placeholder="来源" value="' + esc(data.source || '') + '">' +
      '<button type="button" class="icon-button remove-fact" aria-label="删除这条事实">✕</button>';
    row.querySelector('.remove-fact').onclick = () => {
      if (el('scriptFacts').children.length > 1) row.remove();
    };
    return row;
  }

  function resetFacts() {
    el('scriptFacts').replaceChildren(factRow({}));
  }

  function nextFactId() {
    const used = new Set([...el('scriptFacts').querySelectorAll('.fact-id')]
      .map(input => input.value.trim()).filter(Boolean));
    let n = el('scriptFacts').children.length + 1;
    while (used.has('F' + n)) n++;
    return 'F' + n;
  }

  function collectFacts() {
    const rows = [...el('scriptFacts').querySelectorAll('.script-fact-row')];
    const used = new Set(rows.map(row => row.querySelector('.fact-id').value.trim()).filter(Boolean));
    let n = 1;
    const nextId = () => { while (used.has('F' + n)) n++; used.add('F' + n); return 'F' + n; };
    return rows.map(row => {
      const content = row.querySelector('.fact-content').value.trim();
      if (!content) return null;
      const id = row.querySelector('.fact-id').value.trim() || nextId();
      return { id: id, content: content, source: row.querySelector('.fact-source').value.trim() };
    }).filter(Boolean);
  }

  function dataMode() {
    return (document.querySelector('[name="dataMode"]:checked') || {}).value || 'radar';
  }
  function modelMode() {
    return (document.querySelector('[name="modelMode"]:checked') || {}).value || 'test';
  }

  function renderBeats(beats) {
    el('scriptBeats').innerHTML = beats.map(b =>
      '<div class="script-beat"><span class="script-beat-name">' + esc(b.beat) + '</span>' +
      '<p>' + esc(b.text) + '</p>' +
      (b.fact_ids && b.fact_ids.length ? '<small>引用：' + esc(b.fact_ids.join(', ')) + '</small>' : '') + '</div>'
    ).join('');
  }

  function clearResult() {
    last = null;
    saved = null;
    el('scriptResult').hidden = true;
    el('scriptBeats').replaceChildren();
    el('scriptFactIds').textContent = '';
    el('scriptMissing').textContent = '';
    el('scriptReferences').replaceChildren();
    el('scriptRunInfo').textContent = '';
    el('scriptWarning').textContent = '';
    el('scriptCopyStatus').textContent = '';
    el('saveTask').disabled = true;
    el('editTask').disabled = true;
    el('saveVersion').hidden = true;
    el('editPanel').hidden = true;
    el('approveTask').disabled = true;
    el('exportSaved').disabled = true;
  }

  function render(data) {
    last = data;
    last.suggestion_snapshot = data.suggestion_snapshot || [];
    const script = data.script || {};
    const beats = script.beats || [];
    const factIds = [...new Set(beats.flatMap(b => b.fact_ids || []))];
    el('scriptResult').hidden = false;
    el('scriptSource').textContent = '来源：' + (data.source || 'stub') + ' · 选题：' + (data.data_source === 'radar' ? '已收录作品' : '示例');
    el('scriptStatus').textContent = script.status === 'ready' ? '可审阅（事实齐全）' : '草案（缺事实，不可发布）';
    el('scriptStatus').className = 'script-status ' + (script.status === 'ready' ? 'is-ready' : 'is-draft');
    renderBeats(beats);
    el('scriptFactIds').textContent = factIds.length ? factIds.join(', ') : '（无）';
    el('scriptMissing').textContent = (data.missing && data.missing.length) ? data.missing.join('；') : '（无）';
    const refs = data.references || [];
    el('scriptReferences').innerHTML = refs.length ? refs.map(r =>
      '<a class="script-ref" href="/?post=' + encodeURIComponent(r.id) + '" target="_blank" rel="noopener">' +
      esc(r.title || ('作品 ' + r.id)) + '<small>播放 ' + (r.plays == null ? '未知' : Number(r.plays).toLocaleString('zh-CN')) +
      ' · 点赞 ' + (r.likes == null ? '未知' : Number(r.likes).toLocaleString('zh-CN')) + '</small></a>'
    ).join('') : '<p class="script-hint">示例模式无真实参考作品。</p>';
    el('scriptRunInfo').textContent = '模式：' + (data.model_mode === 'real' ? '真实模型' : '测试') +
      ' · run_id：' + (data.run_id || '未记录') + (data.model ? ' · 模型：' + data.model : '');
    el('scriptWarning').textContent = data.warning || '';
    el('scriptCopyStatus').textContent = '';
    renderPlan(data.plan);
    el('saveTask').disabled = true;
    el('editTask').disabled = true;
    el('saveVersion').hidden = true;
    el('editPanel').hidden = true;
    el('approveTask').disabled = true;
    el('exportSaved').disabled = true;
  }

  function renderPlan(plan) {
    if (!plan || !Object.keys(plan).length) {
      el('scriptPlan').hidden = true;
      return;
    }
    el('scriptPlan').hidden = false;
    el('scriptPlan').innerHTML = '<h4>执行计划（随稿件版本保存）</h4>' +
      '<p>选题：' + esc((plan.topic_snapshot || {}).topic || '待补') + '</p>' +
      '<label>镜头（每行一个）<textarea id="planShots" rows="2">' + esc((plan.shots || []).join('\n')) + '</textarea></label>' +
      '<label>素材 / 证明<textarea id="planProof" rows="2">' + esc(plan.proof || '') + '</textarea></label>' +
      '<label>下一动作<input id="planNext" value="' + esc(plan.next_action || '') + '"></label>' +
      (plan.video_prompt ? '<h4>AI 辅助画面提示词（随此版本保存）</h4><p>' + esc(plan.video_prompt) + '</p>' : '');
    ['planShots', 'planProof', 'planNext'].forEach(id => {
      el(id).oninput = () => {
        planDirty = true;
        el('approveTask').disabled = true;
        el('taskStatus').textContent = '计划有未保存修改，保存后才能批准';
      };
    });
  }

  function collectPlan() {
    if (!last || el('scriptPlan').hidden) return last ? (last.plan || null) : null;
    const plan = Object.assign({}, last.plan || {});
    plan.shots = el('planShots').value.split('\n').map(item => item.trim()).filter(Boolean);
    plan.proof = el('planProof').value.trim();
    plan.next_action = el('planNext').value.trim();
    return plan;
  }

  function markdown(data) {
    const script = data.script || {};
    const beats = script.beats || [];
    const factIds = [...new Set(beats.flatMap(b => b.fact_ids || []))];
    const facts = (data.snapshot || {}).facts || [];
    const refs = data.references || [];
    const usage = data.usage || {};
    const lines = ['# 脚本：' + (script.topic || ''), '',
      '任务 ID：' + (data.task_uid || '未保存'),
      '版本：' + (data.version ? 'v' + data.version : '未保存'),
      '状态：' + (script.status || ''), '数据来源：' + (data.data_source || ''),
      '模型模式：' + (data.model_mode || ''), '来源：' + (data.source || ''),
      'run_id：' + (data.run_id || ''),
      '用量：prompt ' + (usage.prompt_tokens == null ? '未知' : usage.prompt_tokens) +
      ' / completion ' + (usage.completion_tokens == null ? '未知' : usage.completion_tokens) +
      ' / total ' + (usage.total_tokens == null ? '未知' : usage.total_tokens),
      '耗时：' + (data.duration_ms == null ? '未知' : data.duration_ms + ' ms'), ''];
    lines.push('## 商品与事实', '商品：' + ((data.snapshot || {}).product || ''),
      '人群：' + ((data.snapshot || {}).audience || ''), '');
    facts.forEach(f => lines.push('- ' + f.id + '：' + f.content + '（来源：' + f.source + '）'));
    lines.push('');
    beats.forEach(b => {
      lines.push('## ' + b.beat);
      lines.push(b.text || '');
      if (b.fact_ids && b.fact_ids.length) lines.push('引用：' + b.fact_ids.join(', '));
      lines.push('');
    });
    lines.push('## 事实引用', factIds.length ? factIds.join(', ') : '（无）', '');
    lines.push('## 参考作品');
    refs.forEach(r => lines.push('- [' + (r.title || ('作品 ' + r.id)) + '](/?post=' + r.id + ') · 播放 ' + (r.plays == null ? '未知' : r.plays)));
    if (!refs.length) lines.push('（示例模式无真实参考作品）');
    const selection = data.selection || {};
    lines.push('', '## 选中参考（仅结构参考，不是本商品事实）');    (selection.references || []).forEach(item => {
      const scope = item.scope || {};
      lines.push('- #' + item.id + ' ' + (item.title || '') +
        (item.source_name ? '（来源：' + item.source_name + '）' : '') +
        (item.post_id ? '（作品：' + item.post_id + '）' : '') +
        '（范围：' + (scope.limitation || (scope.frames ? scope.frames + ' 张采样画面' : '范围未知')) + '）');
    });
    if (!(selection.references || []).length) lines.push('（未选择）');
    lines.push('## 选中痛点（线索，不是已验证需求）');
    (selection.pains || []).forEach(item => lines.push('- #' + item.id + ' ' + (item.pain || '') +
      '（来源：' + (item.source || '未知') + '，证据：' + (item.evidence_role || '未标注') + '）' +
      (item.evidence ? ' 原摘录：' + item.evidence : '')));
    if (!(selection.pains || []).length) lines.push('（未选择）');
    const plan = data.plan || {};
    lines.push('', '## 执行计划');
    lines.push('选题：' + ((plan.topic_snapshot || {}).topic || '待补'));
    lines.push('目标时长：' + (plan.duration_seconds == null ? '待补' : plan.duration_seconds + ' 秒'));
    lines.push('镜头：' + ((plan.shots || []).length ? plan.shots.join('；') : '待补'));
    lines.push('素材/证明：' + (plan.proof || '待补'));
    lines.push('下一动作：' + (plan.next_action || '待补'));
    if (plan.video_prompt) lines.push('', '## AI 辅助画面提示词', plan.video_prompt);
    const suggestions = data.suggestion_snapshot || [];
    lines.push('', '## 复盘建议（执行参考，不是商品事实）');
    suggestions.forEach(item => {
      const suggestion = item.suggestion || {};
      lines.push('- ' + (suggestion.text || '') + '（依据：' + (suggestion.basis || '未提供') +
        '；条件：' + (suggestion.conditions || '未提供') +
        '；待验证：' + (suggestion.pending || '未提供') + '）');
    });
    if (!suggestions.length) lines.push('（未选择）');
    lines.push('', '## 缺失项', (data.missing && data.missing.length) ? data.missing.join('；') : '（无）', '');
    return lines.join('\n');
  }

  function download(content) {
    const blob = new Blob(['\ufeff' + content], { type: 'text/markdown;charset=utf-8' });
    const href = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = href;
    link.download = '脚本-' + new Date().toISOString().slice(0, 10) + '.md';
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(href), 60000);
  }

  async function loadSources() {
    try {
      const refs = await getJson('/api/reference/list');
      el('referenceList').innerHTML = refs.length ? refs.map(item =>
        '<label class="script-source"><input type="checkbox" data-ref="' + item.id + '">' +
        '<span>#' + item.id + ' ' + esc(item.title || '未命名参考') + '</span>' +
        '<button type="button" class="text-button" data-view-ref="' + item.id + '">查看</button></label>'
      ).join('') : '<p class="script-hint">还没有保存的参考拆解。</p>';
      el('referenceList').querySelectorAll('[data-ref]').forEach(box => {
        box.checked = selectedRefs.has(Number(box.dataset.ref));
        box.onchange = () => {
          const id = Number(box.dataset.ref);
          if (box.checked) selectedRefs.add(id); else selectedRefs.delete(id);
        };
      });
      el('referenceList').querySelectorAll('[data-view-ref]').forEach(button => {
        button.onclick = () => viewSource('reference', button.dataset.viewRef);
      });
    } catch (error) {
      el('referenceList').innerHTML = '<p class="script-hint">参考读取失败：' + esc(error.message) + '</p>';
    }
    try {
      const pains = await getJson('/api/pain/list');
      el('painList').innerHTML = pains.length ? pains.map(item =>
        '<label class="script-source"><input type="checkbox" data-pain="' + item.id + '">' +
        '<span>#' + item.id + ' ' + esc(item.pain || '') + '</span>' +
        '<button type="button" class="text-button" data-view-pain="' + item.id + '">查看</button></label>'
      ).join('') : '<p class="script-hint">还没有保存的痛点线索。</p>';
      el('painList').querySelectorAll('[data-pain]').forEach(box => {
        box.checked = selectedPains.has(Number(box.dataset.pain));
        box.onchange = () => {
          const id = Number(box.dataset.pain);
          if (box.checked) selectedPains.add(id); else selectedPains.delete(id);
        };
      });
      el('painList').querySelectorAll('[data-view-pain]').forEach(button => {
        button.onclick = () => viewSource('pain', button.dataset.viewPain);
      });
    } catch (error) {
      el('painList').innerHTML = '<p class="script-hint">痛点读取失败：' + esc(error.message) + '</p>';
    }
  }

  async function viewSource(kind, id) {
    try {
      const data = await getJson('/api/' + kind + '?id=' + encodeURIComponent(id));
      el('sourceDetail').hidden = false;
      if (kind === 'reference') {
        const report = data.report || {};
        const scope = data.scope || {};
        const observations = (report.observations || []).map(row =>
          '<li>观察：' + esc(row.evidence || '') + '；建议：' + esc(row.advice || '') + '</li>').join('');
        el('sourceDetail').innerHTML = '<h4>参考 #' + data.id + '：' + esc(data.title || '') + '</h4>' +
          '<p>' + esc(report.summary || '（无摘要）') + '</p>' +
          (observations ? '<ul>' + observations + '</ul>' : '<p class="script-hint">没有视频观察，范围按报告标注。</p>') +
          '<p class="script-hint">来源：' + esc(data.source_name || data.source_type || '未知') +
          ' · 范围：' + esc(scope.limitation || (scope.frames ? scope.frames + ' 张采样画面' : '范围未知')) +
          ' · 模型：' + esc(data.model || '未知') + ' · 仅作结构与节奏参考，不是本商品事实。</p>';
      } else {
        el('sourceDetail').innerHTML = '<h4>痛点 #' + data.id + '</h4>' +
          '<p>' + esc(data.pain || '') + '</p>' +
          (data.evidence ? '<p class="script-hint">原摘录：' + esc(data.evidence) + '</p>' : '') +
          '<p class="script-hint">来源：' + esc(data.source || '未知') +
          ' · 证据：' + esc(data.evidence_role || '未标注') + ' · 线索，不是已验证需求或本商品事实。</p>';
      }
    } catch (error) {
      el('sourceDetail').hidden = false;
      el('sourceDetail').textContent = error.message;
    }
  }

  async function loadStrategy() {
    try {
      strategy = await getJson('/api/strategy');
    } catch (error) {
      strategy = null;
    }
    el('strategyBadge').textContent = strategy && strategy.confirmed
      ? '策略已确认 v' + strategy.version
      : '策略未确认（仅研究草稿）';
  }

  function renderPool(data) {
    poolBatch = data.batch_id || '';
    const candidates = data.candidates || [];
    const gap = data.gap || {};
    el('topicsStatus').textContent = (data.blocked || '') ||
      ('候选 ' + candidates.length + ' 条；缺口：保守 ' + (gap.conservative || 0) +
       ' / 实验 ' + (gap.experimental || 0) + (data.notes && data.notes.length ? '；' + data.notes.join('；') : ''));
    el('topicsPool').innerHTML = candidates.map(item =>
      '<label class="script-source"><input type="checkbox" data-cand="' + item.id + '" data-lane="' + item.lane + '">' +
      '<span>' + (item.lane === 'conservative' ? '保守' : '实验') + ' · ' + esc(item.topic || '') + '</span></label>'
    ).join('');
    el('saveCombo').disabled = candidates.length === 0;
  }

  el('buildTopics').onclick = async () => {
    try {
      renderPool(await request('/api/topics/build', { keyword: el('scriptKeyword').value.trim() }));
    } catch (error) {
      el('topicsStatus').textContent = error.message;
    }
  };

  el('saveCombo').onclick = async () => {
    const boxes = [...el('topicsPool').querySelectorAll('[data-cand]')];
    const conservative = boxes.filter(box => box.checked && box.dataset.lane === 'conservative')
      .map(box => Number(box.dataset.cand));
    const experimental = boxes.filter(box => box.checked && box.dataset.lane === 'experimental')
      .map(box => Number(box.dataset.cand));
    try {
      const data = await request('/api/topics/select', {
        batch_id: poolBatch, conservative_ids: conservative, experimental_ids: experimental,
        combo_uid: combo ? combo.combo_uid : '',
        expected_version: combo ? combo.version : 0,
      });
      combo = data.combo;
      renderCombo();
    } catch (error) {
      el('topicsStatus').textContent = error.message;
    }
  };

  function renderCombo() {
    el('comboPanel').hidden = false;
    el('comboPanel').innerHTML = '<h4>当日组合 · v' + combo.version + '（' + combo.business_date + '）</h4>' +
      (combo.snapshot_json || []).map(item =>
        '<p>' + (item.lane === 'conservative' ? '保守' : '实验') + ' · ' + esc(item.topic || '') +
        ' <button class="secondary compact" data-gen="' + item.id + '">为这条生成脚本</button></p>').join('');
    el('comboPanel').querySelectorAll('[data-gen]').forEach(button => {
      button.onclick = () => {
        pendingCandidate = { id: Number(button.dataset.gen), combo_uid: combo.combo_uid };
        generate();
      };
    });
  }

  async function loadCombo() {
    try {
      const data = await getJson('/api/topics/combo');
      if (data) {
        combo = data;
        renderCombo();
      }
    } catch (error) {
      // 组合读取失败不阻断页面
    }
  }

  function focusCandidate(comboUid, candidateId) {
    if (!combo) {
      el('topicsStatus').textContent = '未能读取当日组合，无法定位候选';
      return;
    }
    if (comboUid && combo.combo_uid !== comboUid) {
      el('topicsStatus').textContent = '组合不匹配：当前页面已不是该组合';
      return;
    }
    const item = (combo.snapshot_json || []).find(value => Number(value.id) === Number(candidateId));
    if (!item) {
      el('topicsStatus').textContent = '候选不属于当前组合或已失效';
      return;
    }
    pendingCandidate = { id: Number(candidateId), combo_uid: combo.combo_uid };
    el('topicsStatus').textContent = '已定位候选：' + (item.topic || '') +
      '（点击“生成脚本”才会调用，不会自动生成）';
  }

  async function loadSuggestion() {
    const id = localStorage.getItem('radar_suggestion');
    if (!id) return;
    try {
      const data = await getJson('/api/feedback/suggestion?id=' + encodeURIComponent(id));
      if (data.simulated) throw new Error('演练建议不能用于正式生成');
      pendingSuggestion = data;
      renderSuggestion();
    } catch (error) {
      el('suggestionPanel').hidden = false;
      el('suggestionPanel').textContent = error.message;
    }
  }

  function renderSuggestion() {
    if (!pendingSuggestion) {
      el('suggestionPanel').hidden = true;
      return;
    }
    const suggestion = pendingSuggestion.suggestion || {};
    el('suggestionPanel').hidden = false;
    el('suggestionPanel').innerHTML = '<p><strong>' + esc(suggestion.text || '') + '</strong></p>' +
      '<p class="script-hint">依据：' + esc(suggestion.basis || '') +
      ' · 条件：' + esc(suggestion.conditions || '') +
      ' · 待验证：' + esc(suggestion.pending || '') + '</p>' +
      '<button class="secondary compact" id="clearSuggestion" type="button">取消建议</button>';
    el('clearSuggestion').onclick = () => {
      localStorage.removeItem('radar_suggestion');
      pendingSuggestion = null;
      renderSuggestion();
    };
  }

  async function refreshTaskList() {
    try {
      const tasks = await getJson('/api/script/tasks');
      el('taskList').innerHTML = tasks.length ? tasks.map(t =>
        '<div class="script-task"><div><strong>' + esc(t.product) + '</strong>' +
        '<small>v' + t.current_version + ' · ' + (t.formal ? '正式 v' + t.strategy_version : '试用') +
        ' · ' + (t.approved_version ? '已批准 v' + t.approved_version : '未批准') +
        ' · ' + new Date(t.updated_at * 1000).toLocaleString('zh-CN') + '</small></div>' +
        '<button class="secondary" data-open="' + esc(t.task_uid) + '">打开</button></div>'
      ).join('') : '<p class="script-hint">还没有保存的任务。</p>';
      el('taskList').querySelectorAll('[data-open]').forEach(button => {
        button.onclick = () => openTask(button.dataset.open).catch(error => {
          el('taskStatus').textContent = '打开失败：' + error.message;
        });
      });
    } catch (error) {
      el('taskList').innerHTML = '<p class="script-hint">任务列表读取失败：' + esc(error.message) + '</p>';
    }
  }

  async function openTask(taskUid, wantVersion) {
    const query = '/api/script/task?id=' + encodeURIComponent(taskUid) +
      (wantVersion ? '&version=' + encodeURIComponent(wantVersion) : '');
    const data = await getJson(query);
    const task = data.task;
    const version = wantVersion
      ? (data.versions.find(item => item.version === Number(wantVersion)) || data.versions[data.versions.length - 1])
      : data.versions[data.versions.length - 1];
    saved = { task_uid: task.task_uid, version: task.current_version, displayVersion: version.version };
    const historical = version.version !== task.current_version;
    selectedRefs.clear(); selectedPains.clear();
    (version.reference_ids_json || []).forEach(id => selectedRefs.add(Number(id)));
    (version.pain_ids_json || []).forEach(id => selectedPains.add(Number(id)));
    el('scriptProduct').value = task.product || '';
    el('scriptAudience').value = task.audience || '';
    const facts = task.facts || [];
    el('scriptFacts').replaceChildren();
    if (facts.length) facts.forEach(fact => el('scriptFacts').append(factRow(fact)));
    else resetFacts();
    render({
      script: { beats: version.human_beats_json, status: task.status, topic: task.product },
      snapshot: { product: task.product, audience: task.audience, facts: task.facts },
      references: task.references,
      source: task.source, model: task.model, run_id: task.run_id,
      data_source: task.data_source, model_mode: task.model_mode,
      missing: version.missing_json,
      usage: task.usage, duration_ms: task.duration_ms,
      selection: { references: version.reference_snapshot_json || [],
                   pains: version.pain_snapshot_json || [] },
      plan: version.plan_json || {},
      suggestion_snapshot: version.suggestion_snapshot_json || [],
    });
    el('saveTask').disabled = true;
    el('editTask').disabled = historical;
    el('approveTask').disabled = historical;
    el('exportSaved').disabled = false;
    el('openCurrent').hidden = !historical;
    el('openCurrent').onclick = () => {
      openTask(task.task_uid).catch(error => { el('taskStatus').textContent = '打开失败：' + error.message; });
    };
    el('taskStatus').textContent = '已打开 ' + task.task_uid + ' · 展示 v' + version.version +
      '（当前 v' + task.current_version + '）' +
      (task.formal ? '（正式 v' + task.strategy_version + '）' : '（试用）') +
      (task.approved_version ? '（已批准 v' + task.approved_version + '）' : '（未批准）');
    loadSources();
  }

  function renderEditPanel() {
    const beats = (last && last.script && last.script.beats) || [];
    el('editPanel').innerHTML = beats.map((beat, index) =>
      '<label class="script-edit-row">' + esc(beat.beat) +
      '<textarea data-beat="' + index + '" rows="2">' + esc(beat.text) + '</textarea></label>'
    ).join('');
  }

  function collectEditBeats() {
    const beats = (last && last.script && last.script.beats) || [];
    return [...el('editPanel').querySelectorAll('textarea')].map((textarea, index) => ({
      beat: beats[index].beat,
      text: textarea.value.trim(),
      fact_ids: beats[index].fact_ids || [],
    }));
  }

  async function saveNewTask() {
    if (saved) {
      el('taskStatus').textContent = '该任务已保存，请使用「编辑 → 保存修改」';
      return;
    }
    if (!last || !last.script) return;
    el('saveTask').disabled = true;
    el('taskStatus').textContent = '正在保存…';
    try {
      const script = last.script;
      const data = await request('/api/script/task/save', {
        product: (last.snapshot || {}).product || '',
        audience: (last.snapshot || {}).audience || '',
        facts: (last.snapshot || {}).facts || [],
        references: last.references || [],
        model_beats: script.beats || [],
        human_beats: script.beats || [],
        fact_ids: [...new Set((script.beats || []).flatMap(b => b.fact_ids || []))],
        missing: last.missing || [],
        source: last.source || '', model: last.model || '',
        usage: last.usage || {}, duration_ms: last.script.duration_ms || last.duration_ms || null,
        run_id: last.run_id || '', data_source: last.data_source || '',
        model_mode: last.model_mode || '', status: script.status || 'draft',
        formal: el('formalTask').checked,
        strategy_version: strategy ? strategy.version : null,
        strategy_summary: strategy ? ((strategy.data.direction || '') + ' · ' + (strategy.data.audience || '')) : '',
        reference_ids: ((last.selection || {}).references || []).map(item => item.id),
        reference_snapshot: (last.selection || {}).references || [],
        pain_ids: ((last.selection || {}).pains || []).map(item => item.id),
        pain_snapshot: (last.selection || {}).pains || [],
        plan: collectPlan(),
        suggestion_ids: ((last.suggestion_snapshot || []) || []).map(item => item.id),
        suggestion_snapshot: last.suggestion_snapshot || [],
      });
      saved = { task_uid: data.task.task_uid, version: data.task.current_version,
                displayVersion: data.task.current_version };
      last.plan = data.versions[0].plan_json || {};
      renderPlan(last.plan);
      el('taskStatus').textContent = '已保存任务 ' + data.task.task_uid + ' · v' + data.task.current_version;
      el('saveTask').disabled = true;
      el('editTask').disabled = false;
      el('approveTask').disabled = false;
      el('exportSaved').disabled = false;
      refreshTaskList();
    } catch (error) {
      el('taskStatus').textContent = '保存失败：' + error.message + '（页面内容已保留）';
      el('saveTask').disabled = false;
    }
  }

  async function saveVersion() {
    if (!saved) return;
    el('saveVersion').disabled = true;
    try {
      const data = await request('/api/script/task/save', {
        task_uid: saved.task_uid,
        expected_version: saved.version,
        human_beats: collectEditBeats(),
        fact_ids: [...new Set((last.script.beats || []).flatMap(b => b.fact_ids || []))],
        missing: last.missing || [],
        run_id: last.run_id || '',
        reference_ids: ((last.selection || {}).references || []).map(item => item.id),
        reference_snapshot: (last.selection || {}).references || [],
        pain_ids: ((last.selection || {}).pains || []).map(item => item.id),
        pain_snapshot: (last.selection || {}).pains || [],
        plan: collectPlan(),
        suggestion_ids: ((last.suggestion_snapshot || []) || []).map(item => item.id),
        suggestion_snapshot: last.suggestion_snapshot || [],
      });
      const task = data.task;
      const item = data.versions[data.versions.length - 1];
      saved.version = task.current_version;
      saved.displayVersion = task.current_version;
      last.script.beats = item.human_beats_json;
      last.missing = item.missing_json;
      last.duration_ms = task.duration_ms;
      last.plan = item.plan_json || {};
      planDirty = false;
      renderPlan(last.plan);
      renderBeats(item.human_beats_json);
      el('editPanel').hidden = true;
      el('saveVersion').hidden = true;
      el('editTask').disabled = false;
      el('approveTask').disabled = false;
      el('taskStatus').textContent = '已保存 v' + task.current_version + '（旧批准已失效）';
      refreshTaskList();
    } catch (error) {
      el('taskStatus').textContent = '保存修改失败：' + error.message + '（编辑内容已保留）';
    } finally {
      el('saveVersion').disabled = false;
    }
  }

  async function approve() {
    if (!saved) return;
    try {
      const data = await request('/api/script/task/approve', {
        task_uid: saved.task_uid, version: saved.displayVersion,
      });
      el('taskStatus').textContent = '已批准 v' + data.task.approved_version + '（仅该版本）';
      refreshTaskList();
    } catch (error) {
      el('taskStatus').textContent = '批准失败：' + error.message;
    }
  }

  async function exportSaved() {
    if (!saved) return;
    const taskUid = saved.task_uid;
    const version = saved.displayVersion;
    try {
      const data = await getJson('/api/script/task?id=' + encodeURIComponent(taskUid) + '&version=' + version);
      const task = data.task;
      const item = data.versions[0];
      if (task.current_version > version) {
        el('taskStatus').textContent = '服务器已有 v' + task.current_version + '，本次导出仍为 v' + version;
      } else {
        el('taskStatus').textContent = '已导出 v' + version;
      }
      download(markdown({
        task_uid: task.task_uid,
        version: item.version,
        script: { beats: item.human_beats_json, status: task.status, topic: task.product },
        snapshot: { product: task.product, audience: task.audience, facts: task.facts },
        references: task.references,
        source: task.source, model: task.model, run_id: item.run_id || task.run_id,
        data_source: task.data_source, model_mode: task.model_mode,
        missing: item.missing_json,
        usage: task.usage, duration_ms: task.duration_ms,
        selection: { references: item.reference_snapshot_json || [],
                     pains: item.pain_snapshot_json || [] },
        plan: item.plan_json || {},
        suggestion_snapshot: item.suggestion_snapshot_json || [],
      }));
    } catch (error) {
      el('taskStatus').textContent = '导出失败：' + error.message;
    }
  }

  async function generate() {
    el('scriptError').textContent = '';
    el('generateScript').disabled = true;
    try {
      const body = {
        keyword: el('scriptKeyword').value.trim(),
        product: el('scriptProduct').value.trim(),
        audience: el('scriptAudience').value.trim(),
        facts: collectFacts(),
        data_mode: dataMode(),
        model_mode: modelMode(),
        confirm: el('modelConfirm').checked,
        reference_ids: [...selectedRefs],
        pain_ids: [...selectedPains],
      };
      if (pendingCandidate) {
        body.candidate_id = pendingCandidate.id;
        body.combo_uid = pendingCandidate.combo_uid;
      }
      if (pendingSuggestion) {
        body.suggestion_ids = [pendingSuggestion.id];
      }
      const data = await request('/api/script/prepare', body);
      if (!data.ok) throw new Error(data.error || '生成失败');
      saved = null;
      render(data);
      el('saveTask').disabled = false;
      refreshTaskList();
    } catch (error) {
      clearResult();
      el('scriptError').textContent = error.message;
    } finally {
      el('generateScript').disabled = false;
    }
  }

  function toggleConfirm() {
    el('confirmField').hidden = modelMode() !== 'real';
  }

  el('addFact').onclick = () => el('scriptFacts').append(factRow({ id: nextFactId() }));
  el('generateScript').onclick = generate;
  el('saveTask').onclick = saveNewTask;
  el('editTask').onclick = () => {
    if (!last || !last.script) return;
    renderEditPanel();
    el('editPanel').hidden = false;
    el('saveVersion').hidden = false;
    el('editTask').disabled = true;
    el('approveTask').disabled = true;
  };
  el('saveVersion').onclick = saveVersion;
  el('approveTask').onclick = approve;
  el('exportSaved').onclick = exportSaved;
  document.querySelectorAll('[name="modelMode"]').forEach(radio => { radio.onchange = toggleConfirm; });
  el('copyScript').onclick = async () => {
    if (!last || !last.script) return;
    const text = (last.script.beats || []).map(b => b.text).join('\n');
    try {
      await navigator.clipboard.writeText(text);
      el('scriptCopyStatus').textContent = '已复制';
    } catch {
      el('scriptCopyStatus').textContent = '复制失败，请手动选中脚本';
    }
  };
  el('exportScript').onclick = () => {
    if (!last || !last.script) return;
    const data = Object.assign({}, last);
    if (saved) {
      data.task_uid = saved.task_uid;
      data.version = saved.displayVersion;
    }
    download(markdown(data));
  };

  resetFacts();
  toggleConfirm();
  refreshTaskList();
  loadSources();
  loadStrategy();
  loadCombo().then(() => {
    const params = new URLSearchParams(location.search);
    if (params.get('candidate')) focusCandidate(params.get('combo'), params.get('candidate'));
  });
  loadSuggestion();
  const urlParams = new URLSearchParams(location.search);
  if (urlParams.get('task')) {
    openTask(urlParams.get('task'), urlParams.get('version')).catch(error => {
      el('taskStatus').textContent = '打开失败：' + error.message;
    });
  }
})();
