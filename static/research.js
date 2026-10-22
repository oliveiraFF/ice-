(() => {
  const el = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const cp = value => [...String(value ?? '')].length;
  const REQUEST_BYTES = 65536;
  const FIELDS = [
    ['researchBusiness', 'business'], ['researchAudience', 'audience'], ['researchGoal', 'goal'],
    ['researchResources', 'resources'], ['researchCapacity', 'capacity'], ['researchQuestionField', 'question'],
  ];
  const KEYS = ['business', 'audience', 'goal', 'resources', 'capacity', 'question'];
  const INDUSTRY_FALLBACK = [
    ['generic', '通用内容'], ['health_education', '健康与医学科普'],
    ['science_education', '自然科学与生活原理'], ['finance_education', '财经知识科普'],
    ['law_education', '法律知识科普'], ['education_learning', '教育与学习'],
    ['technology_digital', '科技与数码'], ['culture_history', '文化与历史'],
    ['career_skills', '职场与技能'], ['food_cooking', '美食与烹饪'],
    ['local_service', '本地服务'], ['physical_product', '实物产品'],
  ];
  let industryCatalog = [];
  function fillIndustrySelect(id, value, inherit) {
    const select = el(id);
    if (!select) return;
    const items = industryCatalog.length ? industryCatalog
      : INDUSTRY_FALLBACK.map(([code, label]) => ({code, label}));
    select.innerHTML = '<option value="">' + (inherit
      ? '缺省（继承来源/通用）' : '通用内容（缺省/历史未保存模板）') + '</option>' +
      items.map(item => '<option value="' + esc(item.code) + '">' + esc(item.label) + '</option>').join('');
    select.value = value || '';
  }
  function industryText(context) {
    const raw = context && context.industry;
    if (raw && raw.code) return raw.label + '（' + raw.code + ' · v' + raw.template_version + '）';
    return '通用（历史未保存模板）';
  }
  function applyIndustryFrozen(context, summaryId, frozenId) {
    const summary = el(summaryId);
    if (summary) {
      const source = (context && context.industry_source) || {};
      summary.textContent = '当前结果冻结模板：' + industryText(context) +
        (source.type ? '；来源：' + source.type : '');
    }
    const frozen = el(frozenId);
    if (frozen) {
      frozen.hidden = false;
      frozen.textContent = '冻结模板：' + industryText(context) + '。模板只提供提问、证据检查与表达约束，不是事实或依据。';
    }
  }
  function restoreIndustrySelect(context, selectId, inherit) {
    const raw = context && context.industry;
    fillIndustrySelect(selectId, raw && raw.code ? raw.code : '', !!inherit);
  }
  async function loadIndustryCatalog() {
    try {
      const rows = await request('/api/ops/industry/catalog', null);
      if (Array.isArray(rows) && rows.length) industryCatalog = rows;
    } catch (error) { /* 静态选项保留 */ }
    const a = el('researchIndustry') ? el('researchIndustry').value : '';
    const c = el('adaptationIndustry') ? el('adaptationIndustry').value : '';
    fillIndustrySelect('researchIndustry', a, false);
    fillIndustrySelect('adaptationIndustry', c, true);
  }
  let token = '', current = null, pageSeq = 0, busy = false, pending = false;
  let drafts = [], records = [], baseline = '', resultInput = null;
  let pendingRestore = null, recordGen = 0;
  let frozenSources = [], restoreState = null, restoreSeq = 0;
  let painsLoaded = false, refsLoaded = false, draftsLoaded = false, recordsLoaded = false;
  let currentTopics = null, topicsResult = null, topicsSeq = 0, topicsBusy = false;
  let topicsRoleParent = '', topicsRoleKey = '__init__', topicsRoleMap = {}, topicConvertButtons = [];
  let topicsRoleBaseline = {};
  let adaptationResultArtifact = null, adaptationSeq = 0, adaptationBusy = false;
  let adaptationFrozen = [], adaptationBaseline = '', adaptationParents = [];
  let adaptationCandidateUid = '', adaptationCandidateRows = [], adaptationCandidateGen = 0;
  const initial = fetch('/api/state?mode=live').then(async response => {
    if (!response.ok) throw new Error('本机连接失败，请重新打开页面');
    token = (await response.json()).token;
  });
  initial.catch(error => showError(error.message));

  async function request(path, body) {
    await initial;
    const response = await fetch(path, {
      method: body === null ? 'GET' : 'POST',
      headers: body === null ? {} : {'Content-Type': 'application/json', 'X-Radar-Token': token},
      body: body === null ? undefined : JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '操作失败');
    return data;
  }
  function showError(text) {
    el('researchError').textContent = text || '';
    el('researchError').hidden = !text;
  }
  function showStatus(text) {
    el('researchStatus').textContent = text || '';
  }
  function setSourceStatus(id, text, hidden) {
    const node = el(id);
    node.textContent = text || '';
    node.hidden = hidden !== false;
  }
  function setBusy(value) {
    busy = value;
    ['researchSave', 'researchDemo', 'researchReal'].forEach(id => { el(id).disabled = value; });
  }
  function nextPage() {
    const seq = ++pageSeq;
    busy = false;
    pending = false;
    setBusy(false);
    topicsSeq += 1;
    topicsBusy = false;
    setTopicsBusy(false);
    adaptationSeq += 1;
    adaptationBusy = false;
    if (el('adaptationSaveInput')) syncAdaptationButtons();
    return seq;
  }
  function checkBytes(payload) {
    const size = new TextEncoder().encode(JSON.stringify(payload)).byteLength;
    return size > REQUEST_BYTES ? '本次请求约 ' + size + ' 字节，超过 65536 字节上限，请减少资料或缩短正文' : '';
  }
  function modeFields(real) {
    return {model_mode: real ? 'real' : 'test', confirm: real === true};
  }
  function consumeConfirm(real) {
    if (!real) return;
    if (!el('researchConfirm').checked) throw new Error('真实调用需勾选本次确认');
    el('researchConfirm').checked = false;
  }
  function excerptRow(text, source) {
    const row = document.createElement('div');
    row.className = 'research-excerpt-row';
    row.innerHTML = '<textarea maxlength="6000" placeholder="粘贴摘录原文"></textarea>' +
      '<input maxlength="300" placeholder="出处说明（必填）">' +
      '<button type="button" class="text-button">移除此条</button>';
    row.querySelector('textarea').value = text || '';
    row.querySelector('input').value = source || '';
    row.querySelector('button').onclick = () => { row.remove(); markRestoreEdited(); updateCount(); updateStale(); };
    return row;
  }
  function addExcerpt(text, source) {
    el('researchExcerpts').appendChild(excerptRow(text, source));
    updateCount();
  }
  function formFields() {
    return {
      topic: el('researchTopic').value.trim(),
      question: el('researchQuestion').value.trim(),
      business: FIELDS.reduce((acc, pair) => { acc[pair[1]] = el(pair[0]).value.trim(); return acc; }, {}),
    };
  }
  function findCheckbox(selector, attribute, value) {
    return [...document.querySelectorAll(selector)].find(box => box.dataset[attribute] === value) || null;
  }
  function uniqueIds(values) {
    const seen = new Set();
    const result = [];
    values.forEach(value => {
      const normalized = typeof value === 'number' ? value : String(value);
      if (seen.has(normalized)) return;
      seen.add(normalized);
      result.push(value);
    });
    return result;
  }
  function frozenOf(kind) {
    return frozenSources.filter(entry => entry.kind === kind);
  }
  function pendingSelection() {
    return (restoreState && pendingRestore) ? pendingRestore : null;
  }
  function selectedIds() {
    const boxIds = (selector, attribute) =>
      [...document.querySelectorAll(selector)].map(box => box.dataset[attribute]);
    const pending = pendingSelection();
    const pendingIds = key => pending ? (pending[key] || []) : [];
    const pain_ids = uniqueIds(boxIds('#researchPains input[data-pain-id]:checked', 'painId')
      .map(Number).concat(frozenOf('pain').map(entry => Number(entry.id)))
      .concat(pendingIds('pain_ids').map(Number)));
    const reference_ids = uniqueIds(boxIds('#researchReferences input[data-ref-id]:checked', 'refId')
      .map(Number).concat(frozenOf('reference').map(entry => Number(entry.id)))
      .concat(pendingIds('reference_ids').map(Number)));
    const draftSelect = el('researchDraft').value;
    const frozenDraft = frozenOf('draft')[0];
    const pendingDraft = pending && pending.draft_uid
      ? {uid: pending.draft_uid, version: pending.draft_version || 0} : null;
    const draft_uid = draftSelect || (frozenDraft ? frozenDraft.uid || '' : '') ||
      (pendingDraft ? pendingDraft.uid : '');
    const draft_version = draftSelect ? Number(el('researchDraftVersion').value || 0)
      : (frozenDraft ? Number(frozenDraft.version || 0)
        : (pendingDraft ? Number(pendingDraft.version || 0) : 0));
    const recordSelect = el('researchRecord').value;
    const frozenRecord = frozenOf('record')[0];
    const record_uid = recordSelect || (frozenRecord ? frozenRecord.uid || '' : '') ||
      (pending && pending.record_uid ? pending.record_uid : '');
    const consultation_ids = uniqueIds(boxIds('#researchConsultations input[data-note-id]:checked', 'noteId')
      .concat(frozenOf('consultation').map(entry => entry.uid || ''))
      .concat(pendingIds('consultation_ids')));
    const review_uids = uniqueIds(boxIds('#researchReviews input[data-review-id]:checked', 'reviewId')
      .concat(frozenOf('review').map(entry => entry.uid || ''))
      .concat(pendingIds('review_uids')));
    const seen = new Set();
    const manual_excerpts = [];
    const collect = (text, source) => {
      text = String(text || '').trim();
      source = String(source || '').trim();
      const key = text + '\n' + source;
      if (!text || seen.has(key)) return;
      seen.add(key);
      manual_excerpts.push({text: text, source: source});
    };
    [...document.querySelectorAll('#researchExcerpts .research-excerpt-row')].forEach(row => {
      collect(row.querySelector('textarea').value, row.querySelector('input').value);
    });
    (pending ? pending.manual_excerpts || [] : []).forEach(item => collect(item.text, item.source));
    return {pain_ids, reference_ids, draft_uid, draft_version, record_uid,
            consultation_ids, review_uids, manual_excerpts};
  }
  function countSelected(selected) {
    return selected.pain_ids.length + selected.reference_ids.length
      + selected.consultation_ids.length + selected.review_uids.length
      + selected.manual_excerpts.length
      + (selected.draft_uid ? 1 : 0) + (selected.record_uid ? 1 : 0);
  }
  function updateCount() {
    const total = countSelected(selectedIds());
    el('researchSelectedCount').textContent = total + ' / 12 条';
    el('researchSelectedCount').className = 'script-hint' + (total > 12 ? ' research-over' : '');
  }
  function currentInput() {
    const fields = formFields();
    const input = {topic: fields.topic, question: fields.question,
                   business: fields.business, selected: selectedIds()};
    const industry = el('researchIndustry') ? el('researchIndustry').value : '';
    if (industry) input.industry = industry;
    return input;
  }
  function normalizedInput(input) {
    const data = input || {};
    const business = data.business || {};
    const selected = data.selected || {};
    return JSON.stringify({
      topic: data.topic || '', question: data.question || '',
      industry: data.industry || '',
      business: KEYS.reduce((acc, key) => { acc[key] = business[key] || ''; return acc; }, {}),
      selected: {
        pain_ids: (selected.pain_ids || []).map(Number).sort((a, b) => a - b),
        reference_ids: (selected.reference_ids || []).map(Number).sort((a, b) => a - b),
        draft_uid: selected.draft_uid || '', draft_version: selected.draft_version || 0,
        record_uid: selected.record_uid || '',
        consultation_ids: (selected.consultation_ids || []).slice().sort(),
        review_uids: (selected.review_uids || []).slice().sort(),
        manual_excerpts: (selected.manual_excerpts || []).map(item => ({
          text: item.text || '', source: item.source || ''})),
      },
    });
  }
  function snapshot() {
    return normalizedInput(currentInput());
  }
  function dirty() {
    return snapshot() !== baseline;
  }
  function normalizedRoles(map) {
    const data = {};
    Object.keys(map || {}).sort().forEach(key => { data[key] = map[key]; });
    return data;
  }
  function rolesSignature(map) {
    return JSON.stringify(normalizedRoles(map));
  }
  function rolesDirty() {
    return rolesSignature(topicsRoleMap) !== rolesSignature(topicsRoleBaseline);
  }
  function savedRolesOf(artifact) {
    const context = (artifact && artifact.context_json) || {};
    let rows = context.source_roles;
    if (!Array.isArray(rows) || !rows.length) {
      rows = ((artifact && artifact.input_json) || {}).source_roles;
    }
    const map = {};
    (Array.isArray(rows) ? rows : []).forEach(item => {
      if (item && typeof item.source_id === 'string' && item.role) {
        map[item.source_id] = item.role;
      }
    });
    return map;
  }
  function parentRoleKey(parent) {
    return parent && parent.uid
      ? parent.uid + '|' + (parent.refs || []).map(ref => ref.id).join(',') : '';
  }
  function syncTopicsRoles(parent, restore) {
    if (restore) topicsRoleMap = Object.assign({}, topicsRoleBaseline);
    topicsRoleParent = parent ? parent.uid || '' : '';
    topicsRoleKey = parentRoleKey(parent);
    renderTopicRoleRows((parent && parent.refs) || []);
  }
  function updateStale() {
    if (!current) {
      el('researchStale').hidden = true;
      return;
    }
    const differs = snapshot() !== normalizedInput(resultInput);
    el('researchStale').hidden = !differs;
    el('researchStale').textContent = differs
      ? '当前输入已改动：下面的结果基于旧输入，未重新分析。' : '';
    renderTopicsParent();
  }
  function validatePayload(payload) {
    const topic = payload.topic || '';
    if (!topic) return '请填写研究主题';
    if (cp(topic) > 200) return '研究主题超过 200 字符上限';
    if (cp(payload.question || '') > 1000) return '本次问题超过 1000 字符上限';
    for (const key of KEYS) {
      if (cp((payload.business || {})[key] || '') > 2000) {
        return '业务字段 ' + key + ' 超过 2000 字符上限';
      }
    }
    const selected = payload.selected || {};
    if (countSelected(selected) > 12) return '显式选择资料最多 12 条';
    if (selected.draft_uid && !(selected.draft_version > 0)) return '请选择研究稿版本';
    for (const item of selected.manual_excerpts || []) {
      if (!item.text) continue;
      if (!item.source) return '人工摘录需要填写出处';
      if (cp(item.text) > 6000) return '人工摘录正文超过 6000 字符上限';
    }
    return '';
  }
  function setMeta(text, kind) {
    el('researchMeta').textContent = text;
    el('researchMeta').className = 'script-badge' + (kind ? ' ' + kind : '');
  }
  function sourceLabel(source) {
    return {'demo': '演示（未真实分析）', 'llm': '真实模型', 'manual': '人工保存（未分析）'}[source] || '未知来源';
  }
  function basisLabel(basis, refs) {
    return (basis || []).map(ident => {
      const ref = refs[ident] || {};
      return esc(ident + '[' + (ref.label || '未知来源') + ']');
    }).join('；') || '无';
  }
  function rows(container, items, withSteps) {
    const refs = (current && current.context_json && current.context_json.refs
      ? Object.fromEntries(current.context_json.refs.map(ref => [ref.id, ref])) : {});
    container.innerHTML = items.length ? items.map(item =>
      '<div class="research-item"><p>' + esc(item.text || '') + '</p>' +
      (item.why ? '<p><small>理由：' + esc(item.why) + '</small></p>' : '') +
      '<p><small>依据：' + basisLabel(item.basis, refs) + '</small></p>' +
      (item.conditions && item.conditions.length ? '<p><small>条件：' + item.conditions.map(esc).join('；') + '</small></p>' : '') +
      (item.gaps && item.gaps.length ? '<p><small>缺口：' + item.gaps.map(esc).join('；') + '</small></p>' : '') +
      (withSteps && item.next_step ? '<p><small>下一步：' + esc(item.next_step) + '</small></p>' : '') +
      '</div>').join('') : '<p class="script-hint">（无）</p>';
  }
  function renderFrozen(artifact) {
    const context = artifact.context_json || {};
    const map = context.ref_map || {};
    const strategy = context.strategy || {};
    const parts = [];
    parts.push('<p><strong>策略边界（本报告冻结）</strong>：版本 v' + (strategy.version || 0) + ' · ' +
               (strategy.confirmed ? '已确认' : '未确认') + '</p>');
    const data = strategy.data || {};
    const keys = Object.keys(data);
    if (!keys.length) parts.push('<p class="script-hint">未提供策略内容</p>');
    keys.forEach(key => {
      const value = Array.isArray(data[key]) ? data[key].join('；') : data[key];
      parts.push('<p><small>' + esc(key) + '：' + esc(value) + '</small></p>');
    });
    parts.push('<p><strong>来源明细（可追溯）</strong></p>');
    (context.refs || []).forEach(ref => {
      const origin = map[ref.id] || {};
      const identity = [];
      if (origin.kind) identity.push('kind=' + origin.kind);
      if (origin.id !== undefined) identity.push('id=' + origin.id);
      if (origin.uid) identity.push('uid=' + origin.uid);
      if (origin.version) identity.push('version=' + origin.version);
      if (origin.index !== undefined) identity.push('index=' + origin.index);
      if (origin.legacy) identity.push('legacy=1');
      parts.push('<div class="research-item"><p><strong>' + esc(ref.id) + ' [' + esc(ref.label || '') +
                 ']</strong> ' + esc(ref.source || '出处未提供') + '</p>' +
                 '<p><small>真实身份：' + esc(identity.join('，') || '未提供') + '</small></p>' +
                 '<p><small>原文：' + esc(ref.text || '') + '</small></p></div>');
    });
    if (!(context.refs || []).length) parts.push('<p class="script-hint">无所选资料</p>');
    el('researchFrozen').innerHTML = parts.join('');
  }
  function topicNode(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function topicStateLabel(state) {
    return state === 'research_candidate' ? '研究候选（未验证）' : '待验证';
  }
  function sourceLabelForTopics(source) {
    return {'demo': '演示（未调用模型，未真实分析）', 'llm': '真实模型'}[source] || '人工保存';
  }
  function strategyBrief(strategy) {
    strategy = strategy || {};
    const data = strategy.data || {};
    const parts = ['v' + (strategy.version || 0), strategy.confirmed ? '已确认' : '未确认'];
    if (data.exclusions) {
      const text = Array.isArray(data.exclusions) ? data.exclusions.join('；') : String(data.exclusions);
      parts.push('排除项：' + text.slice(0, 120));
    }
    return parts.join(' · ');
  }
  function parentForTopics() {
    if (currentTopics && currentTopics.kind === 'topics') {
      const context = currentTopics.context_json || {};
      const parent = context.parent || {};
      return {uid: currentTopics.parent_uid || parent.artifact_uid || '',
              topic: (context.parent_input || {}).topic || parent.topic || '',
              strategy: context.strategy || {}, refs: context.refs || [],
              source: parent.source || '', analyzed: parent.analyzed,
              frozen: true, fromTopics: true};
    }
    if (current && current.kind === 'research') {
      const context = current.context_json || {};
      return {uid: current.artifact_uid || '', topic: (current.input_json || {}).topic || current.topic || '',
              strategy: context.strategy || {}, refs: context.refs || [],
              source: current.source || '', analyzed: !!(current.result_json && Object.keys(current.result_json).length),
              frozen: true, fromTopics: false};
    }
    return null;
  }
  function renderTopicsParent() {
    const parent = parentForTopics();
    const hasParent = !!(parent && parent.uid);
    if (!hasParent) {
      el('topicsParentUid').textContent = '当前 A：未选择已保存记录';
      el('topicsParentTopic').textContent = '';
      el('topicsStrategyState').textContent = '';
      el('topicsDirtyHint').hidden = true;
      el('topicsMeta').textContent = '待生成';
      el('topicsMeta').className = 'script-badge';
    } else {
      el('topicsParentUid').textContent = '当前 A：' + parent.uid +
        (parent.fromTopics ? '（来自已打开的选题记录）' : '');
      el('topicsParentTopic').textContent = '研究主题：' + (parent.topic || '（无主题）') +
        ' · ' + (parent.analyzed ? '父记录已分析' : '父记录未分析');
      el('topicsStrategyState').textContent = '保存时策略快照：' + strategyBrief(parent.strategy);
      const formEdited = dirty();
      const rolesEdited = rolesDirty();
      el('topicsDirtyHint').hidden = !(formEdited || rolesEdited);
      if (rolesEdited) {
        el('topicsDirtyHint').textContent = parent.fromTopics
          ? '需求角色声明有未保存修改：再次生成会使用新声明；当前显示的是已保存结果。'
          : '需求角色声明有未保存修改：再次生成会提交新声明；当前结果基于旧声明。';
      } else if (formEdited) {
        el('topicsDirtyHint').textContent = parent.fromTopics
          ? '当前显示已保存的选题记录；下方 A 表单的未保存编辑不会用于再次生成选题，父 A 仍用已保存冻结快照。'
          : '当前表单有未保存编辑：本次选题只使用已保存的 A 快照，不会包含这些编辑；如需使用请先保存或重新研究。';
      } else {
        el('topicsDirtyHint').textContent = '';
      }
      if (!topicsResult) {
        el('topicsMeta').textContent = '待生成';
        el('topicsMeta').className = 'script-badge';
      }
    }
    el('topicsBaseNote').textContent = hasParent
      ? '基于已保存记录（父记录冻结快照）；不自动重新分析父记录。'
      : '先保存或研究一条 A 记录，再生成选题建议。';
    const roleKey = parentRoleKey(parent);
    if (roleKey !== topicsRoleKey) {
      if (!hasParent || !parent.fromTopics) topicsRoleBaseline = {};
      topicsRoleMap = Object.assign({}, topicsRoleBaseline);
      syncTopicsRoles(hasParent ? parent : null, false);
    }
    setTopicsBusy(topicsBusy);
  }
  function renderTopicRoleRows(refs) {
    const box = el('topicsManualRoles');
    box.innerHTML = '';
    const manuals = (refs || []).filter(ref => ref && ref.role === 'manual');
    if (!manuals.length) {
      box.appendChild(topicNode('p', 'script-hint',
        '父记录没有人工摘录；source_roles 只能标注人工摘录，不能把参考/指标/推断改成需求。'));
      return;
    }
    manuals.forEach(ref => {
      const row = topicNode('div', 'topics-role-row');
      const info = topicNode('p', '', '');
      const strong = topicNode('strong', '', ref.id + ' · 人工摘录（人工提供，未独立核实）');
      info.appendChild(strong);
      info.appendChild(topicNode('span', '', ' 出处：' + (ref.source || '未提供') + '；原文：' +
        String(ref.text || '').slice(0, 80)));
      const select = document.createElement('select');
      select.setAttribute('aria-label', ref.id + ' 的需求角色声明');
      const none = document.createElement('option');
      none.value = '';
      none.textContent = '不声明需求角色';
      select.appendChild(none);
      [['audience_pain', '受众痛点/咨询'], ['search_interest', '搜索兴趣'],
       ['hot_topic', '热点话题'], ['industry_signal', '行业信号'],
       ['market_task', '市场任务'], ['content_gap', '内容缺口']].forEach(pair => {
        const option = document.createElement('option');
        option.value = pair[0];
        option.textContent = pair[1];
        select.appendChild(option);
      });
      select.value = topicsRoleMap[ref.id] || '';
      select.addEventListener('change', () => {
        if (select.value) topicsRoleMap[ref.id] = select.value;
        else delete topicsRoleMap[ref.id];
        el('topicsStatus').textContent = '需求角色声明已修改（人工声明，未独立核实）；下次生成时提交。';
        renderTopicsParent();
      });
      row.appendChild(info);
      row.appendChild(select);
      box.appendChild(row);
    });
  }
  function setTopicsBusy(value) {
    topicsBusy = value;
    const hasParent = !!parentForTopics();
    el('topicsDemo').disabled = value || !hasParent;
    el('topicsReal').disabled = value || !hasParent;
    topicConvertButtons.forEach(button => { button.disabled = value; });
  }
  function showTopicsError(text) {
    el('topicsError').textContent = text || '';
    el('topicsError').hidden = !text;
  }
  function showTopicsStatus(text) {
    el('topicsStatus').textContent = text || '';
  }
  function topicsPayload(real) {
    const parent = parentForTopics();
    if (!parent || !parent.uid) throw new Error('请先保存或打开一条已保存的 A 研究记录');
    if (!/^[a-f0-9]{12}$/.test(parent.uid)) throw new Error('父研究记录 UID 无效');
    const roles = Object.keys(topicsRoleMap).sort().map(sourceId => ({
      source_id: sourceId, role: topicsRoleMap[sourceId]}));
    const payload = {parent_uid: parent.uid, source_roles: roles,
                     model_mode: real ? 'real' : 'test', confirm: real === true};
    const size = new TextEncoder().encode(JSON.stringify(payload)).byteLength;
    if (size > REQUEST_BYTES) {
      throw new Error('本次请求约 ' + size + ' 字节，超过 65536 字节上限，请减少角色声明');
    }
    return payload;
  }
  async function topicsGenerate(real) {
    if (topicsBusy) return;
    showTopicsError('');
    showTopicsStatus('');
    const seq = ++topicsSeq;
    let payload;
    try {
      payload = topicsPayload(real);
      if (real && !el('topicsConfirm').checked) throw new Error('真实调用需勾选本次确认');
      if (real) el('topicsConfirm').checked = false;
    } catch (error) {
      if (seq === topicsSeq) showTopicsError(error.message);
      return;
    }
    setTopicsBusy(true);
    el('topicsMeta').textContent = real ? '生成中…' : '演示生成中…';
    el('topicsMeta').className = 'script-badge';
    try {
      const data = await request('/api/ops/research/topics', payload);
      if (seq !== topicsSeq) { loadTopicsHistory(); return; }
      renderTopicsArtifact(data.artifact);
      showTopicsStatus('已生成并保存选题建议 ' + data.artifact.artifact_uid + '（' +
        sourceLabelForTopics(data.artifact.source) + '）；不自动转稿。');
      loadTopicsHistory();
    } catch (error) {
      if (seq === topicsSeq) showTopicsError(error.message);
    } finally {
      if (seq === topicsSeq) setTopicsBusy(false);
    }
  }
  function renderTopicsArtifact(artifact, opts) {
    currentTopics = artifact;
    topicsResult = artifact;
    const restoreRoles = !!(opts && opts.restoreRoles);
    const saved = savedRolesOf(artifact);
    if (restoreRoles) {
      // 打开已保存 B：恢复它自己的 source_roles，并建立对应基线。
      topicsRoleBaseline = saved;
      topicsRoleMap = Object.assign({}, saved);
      syncTopicsRoles(parentForTopics(), false);
    } else {
      // 生成/转稿结果：基线改为本次提交快照；等待期间的编辑保留为未保存。
      topicsRoleBaseline = saved;
    }
    renderTopicsResult(artifact);
    renderTopicsParent();
  }
  function renderTopicsResult(artifact) {
    const result = artifact.result_json || {};
    const context = artifact.context_json || {};
    const refs = {};
    (context.refs || []).forEach(ref => { refs[ref.id] = ref; });
    const demand = context.demand_roles || {};
    const declarations = {};
    (context.source_roles || []).forEach(item => { declarations[item.source_id] = item; });
    el('topicsResult').hidden = false;
    el('topicsDraftResult').hidden = true;
    el('topicsSource').textContent = sourceLabelForTopics(artifact.source);
    el('topicsSummary').textContent = result.summary || '（无摘要）';
    el('topicsMeta').textContent = sourceLabelForTopics(artifact.source);
    el('topicsMeta').className = 'script-badge' + (artifact.source ? ' ' + artifact.source : '');
    const wrap = el('topicsCandidates');
    wrap.innerHTML = '';
    topicConvertButtons = [];
    const candidates = result.candidates || [];
    if (!candidates.length) {
      wrap.appendChild(topicNode('p', 'script-hint',
        '本次没有候选；请查看“仍不能判断”的具体问题，不要凑数生成。'));
    }
    candidates.forEach(candidate => {
      const card = topicNode('div', 'topics-candidate');
      const head = topicNode('div', 'topics-candidate-head');
      head.appendChild(topicNode('strong', '', '候选 ' + candidate.id));
      head.appendChild(topicNode('span', 'topics-state' + (candidate.state === 'needs_validation' ? ' needs_validation' : ''),
        topicStateLabel(candidate.state)));
      card.appendChild(head);
      const addField = (label, value) => {
        const row = topicNode('p', 'topics-field');
        row.appendChild(topicNode('b', '', label + '：'));
        row.appendChild(document.createTextNode(value || '（无）'));
        card.appendChild(row);
      };
      addField('主题', candidate.topic);
      addField('受众问题', candidate.audience_problem);
      addField('适配理由', candidate.fit_reason);
      addField('为什么', candidate.why);
      addField('条件', (candidate.conditions || []).join('；'));
      addField('缺口', (candidate.gaps || []).join('；'));
      addField('下一步', candidate.next_step);
      const details = topicNode('details', '', '');
      details.appendChild(topicNode('summary', '', '展开依据（真实来源与需求角色）'));
      (candidate.basis || []).forEach(sourceId => {
        const ref = refs[sourceId] || {};
        const origin = (context.ref_map || {})[sourceId] || {};
        const row = topicNode('div', 'topics-basis-row');
        const title = topicNode('p', '', '');
        title.appendChild(topicNode('strong', '', sourceId + ' [' + (ref.label || '未知来源') + '] '));
        title.appendChild(document.createTextNode('真实身份：kind=' + (origin.kind || '未提供') +
          (origin.id !== undefined ? '，id=' + origin.id : '') +
          (origin.uid ? '，uid=' + origin.uid : '') +
          (origin.version ? '，version=' + origin.version : '') +
          (origin.index !== undefined ? '，index=' + origin.index : '') +
          '；出处：' + (ref.source || '未提供')));
        row.appendChild(title);
        row.appendChild(topicNode('p', 'topics-basis-text', ref.text || '（原文未提供）'));
        const demandRole = demand[sourceId];
        if (demandRole) {
          const declared = declarations[sourceId];
          row.appendChild(topicNode('p', 'topics-declared',
            '服务端认定的需求角色：' + (declared && declared.role_label ? declared.role_label : demandRole) +
            (declared ? '（人工声明，未独立核实）' : '（原始摘录角色）')));
        } else {
          row.appendChild(topicNode('p', 'script-hint', '仅作背景依据，不是服务端认定的需求角色。'));
        }
        details.appendChild(row);
      });
      if (!(candidate.basis || []).length) {
        details.appendChild(topicNode('p', 'script-hint', '没有引用父记录来源。'));
      }
      const demandRow = topicNode('div', 'topics-basis-row');
      demandRow.appendChild(topicNode('strong', '', '需求依据（demand_basis）'));
      const demandText = (candidate.demand_basis || []).map(sourceId =>
        sourceId + '（' + (demand[sourceId] || '未认定') + '）').join('；');
      demandRow.appendChild(topicNode('p', '', demandText || '无——只能是待验证研究问题，不表示需求成立。'));
      details.appendChild(demandRow);
      card.appendChild(details);
      const convert = document.createElement('button');
      convert.type = 'button';
      convert.className = 'secondary compact topics-convert';
      convert.textContent = '转为研究稿输入';
      convert.dataset.convert = String(candidate.id);
      convert.addEventListener('click', () => { topicsToDraft(candidate.id); });
      topicConvertButtons.push(convert);
      card.appendChild(convert);
      wrap.appendChild(card);
    });
    const cannot = el('topicsCannot');
    cannot.innerHTML = '';
    const items = result.cannot_judge || [];
    if (!items.length) {
      cannot.appendChild(topicNode('p', 'script-hint', '（无）'));
    } else {
      const list = document.createElement('ul');
      items.forEach(item => {
        const li = document.createElement('li');
        li.textContent = item;
        list.appendChild(li);
      });
      cannot.appendChild(list);
    }
    el('topicsExport').href = '/api/ops/research/export?id=' +
      encodeURIComponent(artifact.artifact_uid);
    setTopicsBusy(topicsBusy);
  }
  function showTopicsDraftLink(uid, stale) {
    const box = el('topicsDraftResult');
    if (stale) {
      showTopicsStatus('转稿已保存：研究稿 ' + uid + '（当前页面未切换）。');
      return;
    }
    box.innerHTML = '';
    box.hidden = false;
    box.appendChild(document.createTextNode('已保存为 M02 研究稿（0 版本、未生成）：' + uid + ' '));
    const link = document.createElement('a');
    link.href = '/draft?id=' + encodeURIComponent(uid);
    link.className = 'text-button';
    link.textContent = '打开研究稿';
    box.appendChild(link);
    box.appendChild(document.createTextNode('（不会自动生成正文）'));
  }
  async function topicsToDraft(candidateId) {
    if (topicsBusy || !topicsResult) return;
    const artifactUid = topicsResult.artifact_uid;
    // R4：转稿只发字符串候选 id（旧整数记录也走字符串精确查的兼容分支）。
    const payload = {artifact_uid: artifactUid, candidate_id: String(candidateId)};
    const size = new TextEncoder().encode(JSON.stringify(payload)).byteLength;
    if (size > REQUEST_BYTES) { showTopicsError('转稿请求超过 65536 字节上限'); return; }
    showTopicsError('');
    showTopicsStatus('正在转为研究稿输入…');
    const seq = ++topicsSeq;
    setTopicsBusy(true);
    try {
      const data = await request('/api/ops/research/to-draft', payload);
      if (seq !== topicsSeq) {
        showTopicsDraftLink(data.draft.draft_uid, true);
        showTopicsStatus('转稿已保存：研究稿 ' + data.draft.draft_uid + '（当前页面未切换）。');
        return;
      }
      showTopicsDraftLink(data.draft.draft_uid, false);
      showTopicsStatus('已保存为研究稿输入（未生成、0 版本）；不会自动调用模型。');
      loadTopicsHistory();
      loadDrafts();
    } catch (error) {
      if (seq === topicsSeq) showTopicsError(error.message);
    } finally {
      if (seq === topicsSeq) setTopicsBusy(false);
    }
  }
  async function loadTopicsHistory() {
    try {
      const list = await request('/api/ops/research/list?kind=topics', null);
      const rows = Array.isArray(list) ? list : [];
      const box = el('topicsHistory');
      box.innerHTML = '';
      if (!rows.length) {
        box.appendChild(topicNode('p', 'script-hint', '还没有选题建议记录。'));
        return;
      }
      rows.forEach(item => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'topics-history-item' +
          (currentTopics && currentTopics.artifact_uid === item.artifact_uid ? ' active' : '');
        button.dataset.openTopics = item.artifact_uid;
        button.appendChild(document.createTextNode(item.topic || '（无主题）'));
        const small = document.createElement('small');
        small.textContent = 'B ' + item.artifact_uid + ' · 父 A ' + (item.parent_uid || '未记录') +
          ' · ' + sourceLabelForTopics(item.source) + ' · ' +
          (item.analyzed ? '有结果' : '未分析') +
          (item.summary ? ' · ' + String(item.summary).slice(0, 40) : '') +
          ' · ' + new Date((item.created_at || 0) * 1000).toLocaleString('zh-CN');
        button.appendChild(small);
        button.addEventListener('click', () => { openArtifact(item.artifact_uid); });
        box.appendChild(button);
      });
    } catch (error) {
      const box = el('topicsHistory');
      box.innerHTML = '';
      box.appendChild(topicNode('p', 'script-hint', '选题历史读取失败，可重试：' + error.message));
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'secondary compact';
      retry.textContent = '重试';
      retry.addEventListener('click', () => { loadTopicsHistory(); });
      box.appendChild(retry);
    }
  }
  // ---------------------------------------------------------------------
  // M05-C 参考适配：独立 C 区块；沿用 A/B 的 busy/序号/确认/转义规则。
  // ---------------------------------------------------------------------
  const ADAPT_FIELDS = [
    ['adaptationBusiness', 'business'], ['adaptationAudience', 'audience'],
    ['adaptationGoal', 'goal'], ['adaptationResources', 'resources'],
    ['adaptationCapacity', 'capacity'], ['adaptationQuestion', 'question'],
  ];
  function adaptationSourceLabel(source) {
    return {'demo': '演示（未调用模型，未真实分析）', 'llm': '真实模型',
            'manual': '人工保存（未分析）'}[source] || '未知来源';
  }
  function adaptationAspectLabel(aspect) {
    return {hook: '开头', structure: '结构', proof: '证明方式',
            pacing: '节奏', cta: '承接'}[aspect] || aspect || '计划';
  }
  function adaptationNode(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }
  function adaptationBusinessValues() {
    return ADAPT_FIELDS.reduce((acc, pair) => { acc[pair[1]] = el(pair[0]).value.trim(); return acc; }, {});
  }
  function adaptationSelectedIds() {
    const checkedPains = [...document.querySelectorAll('#adaptationPains input[data-pain-id]:checked')]
      .map(box => Number(box.dataset.painId));
    const pain_ids = uniqueIds(checkedPains.concat(
      adaptationFrozen.filter(entry => entry.kind === 'pain').map(entry => Number(entry.id))));
    const draftSelect = el('adaptationDraft').value;
    const frozenDraft = adaptationFrozen.filter(entry => entry.kind === 'draft')[0];
    const draft_uid = draftSelect || (frozenDraft ? frozenDraft.uid || '' : '');
    const draft_version = draftSelect ? Number(el('adaptationDraftVersion').value || 0)
      : (frozenDraft ? Number(frozenDraft.version || 0) : 0);
    const referenceSelect = el('adaptationReference').value;
    const frozenRef = adaptationFrozen.filter(entry => entry.kind === 'reference')[0];
    const reference_id = Number(referenceSelect || (frozenRef ? frozenRef.id : 0) || 0);
    const seen = new Set();
    const manual_excerpts = [];
    const collect = (text, source) => {
      text = String(text || '').trim();
      source = String(source || '').trim();
      if (!text) return;
      const key = text + '\n' + source;
      if (seen.has(key)) return;
      seen.add(key);
      manual_excerpts.push({text: text, source: source});
    };
    [...document.querySelectorAll('#adaptationExcerpts .research-excerpt-row')].forEach(row => {
      collect(row.querySelector('textarea').value, row.querySelector('input').value);
    });
    adaptationFrozen.filter(entry => entry.kind === 'excerpt')
      .forEach(entry => collect(entry.text, entry.source));
    return {reference_id, pain_ids, draft_uid, draft_version, manual_excerpts};
  }
  function adaptationCount(selected) {
    return (selected.reference_id ? 1 : 0) + selected.pain_ids.length
      + (selected.draft_uid ? 1 : 0) + selected.manual_excerpts.length;
  }
  function updateAdaptationCount() {
    const total = adaptationCount(adaptationSelectedIds());
    el('adaptationSelectedCount').textContent = total + ' / 12 条';
    el('adaptationSelectedCount').className = 'script-hint' + (total > 12 ? ' adaptation-over' : '');
    updateAdaptationStale();
  }
  function updateAdaptationStale() {
    if (!el('adaptationStale')) return;
    const differs = !!(adaptationResultArtifact && adaptationBaseline &&
      adaptationSnapshot() !== adaptationBaseline);
    el('adaptationStale').hidden = !differs;
    el('adaptationStale').textContent = differs
      ? '当前适配输入已改动：下方结果基于旧输入，未重新分析；再次生成会保存为新记录。' : '';
  }
  function adaptationFormInput() {
    const kind = el('adaptationSubjectKind').value === 'candidate' ? 'candidate' : 'manual';
    const subject = kind === 'candidate'
      ? {kind: kind, artifact_uid: el('adaptationParent').value,
         candidate_id: el('adaptationCandidate').value}
      : {kind: kind, topic: el('adaptationTopic').value.trim(),
         business: adaptationBusinessValues()};
    const selected = adaptationSelectedIds();
    const industry = el('adaptationIndustry') ? el('adaptationIndustry').value : '';
    return {subject: subject, reference_id: selected.reference_id,
            selected: {pain_ids: selected.pain_ids,
                       manual_excerpts: selected.manual_excerpts,
                       draft_uid: selected.draft_uid,
                       draft_version: selected.draft_version},
            industry: industry,
            instruction: el('adaptationInstruction').value.trim()};
  }
  function adaptationNormalized(input) {
    const data = input || {};
    const subject = data.subject || {};
    const selected = data.selected || {};
    const business = subject.business || {};
    return JSON.stringify({
      subject: subject.kind === 'candidate'
        ? {kind: 'candidate', artifact_uid: subject.artifact_uid || '',
           candidate_id: subject.candidate_id || ''}
        : {kind: 'manual', topic: subject.topic || '',
           business: KEYS.reduce((acc, key) => { acc[key] = business[key] || ''; return acc; }, {})},
      reference_id: Number(data.reference_id || 0),
      industry: data.industry || '',
      selected: {
        pain_ids: (selected.pain_ids || []).map(Number).sort((a, b) => a - b),
        manual_excerpts: (selected.manual_excerpts || []).map(item => ({
          text: item.text || '', source: item.source || ''})),
        draft_uid: selected.draft_uid || '',
        draft_version: Number(selected.draft_version || 0),
      },
      instruction: data.instruction || '',
    });
  }
  function adaptationSnapshot() {
    return adaptationNormalized(adaptationFormInput());
  }
  function adaptationDirty() {
    return !!adaptationBaseline && adaptationSnapshot() !== adaptationBaseline;
  }
  function validateAdaptationPayload(payload) {
    const subject = payload.subject || {};
    if (subject.kind === 'candidate') {
      if (!/^[a-f0-9]{12}$/.test(subject.artifact_uid || '')) return '请选择一条已保存的 B 选题记录';
      if (!/^[A-Za-z0-9_-]{1,20}$/.test(subject.candidate_id || '')) return '请选择 B 目标候选';
    } else {
      if (!subject.topic) return '请填写适配主题';
      if (cp(subject.topic) > 200) return '适配主题超过 200 字符上限';
      for (const key of KEYS) {
        if (cp((subject.business || {})[key] || '') > 2000) {
          return '业务字段 ' + key + ' 超过 2000 字符上限';
        }
      }
    }
    if (!(Number(payload.reference_id) > 0)) return '必须明确选择一条外部参考';
    const selected = payload.selected || {};
    if ((selected.draft_uid && !(selected.draft_version > 0))) return '请选择研究稿版本';
    if (adaptationCount({reference_id: payload.reference_id,
                         pain_ids: selected.pain_ids || [],
                         manual_excerpts: selected.manual_excerpts || [],
                         draft_uid: selected.draft_uid || ''}) > 12) {
      return '显式选择资料最多 12 条（含指定参考）';
    }
    for (const item of selected.manual_excerpts || []) {
      if (!item.text) continue;
      if (!item.source) return '人工摘录需要填写出处';
      if (cp(item.text) > 6000) return '人工摘录正文超过 6000 字符上限';
      if (cp(item.source) > 300) return '人工摘录出处超过 300 字符上限';
    }
    if (cp(payload.instruction || '') > 1000) return '本次说明超过 1000 字符上限';
    return '';
  }
  function adaptationPayload(real, forSave) {
    const input = adaptationFormInput();
    const payload = {
      subject: input.subject,
      reference_id: input.reference_id,
      selected: {pain_ids: input.selected.pain_ids,
                 manual_excerpts: input.selected.manual_excerpts},
      instruction: input.instruction,
    };
    if (input.industry) payload.industry = input.industry;
    if (input.selected.draft_uid) {
      payload.selected.draft_uid = input.selected.draft_uid;
      payload.selected.draft_version = input.selected.draft_version;
    }
    if (forSave) payload.kind = 'adaptation';
    else Object.assign(payload, {model_mode: real ? 'real' : 'test', confirm: real === true});
    const invalid = validateAdaptationPayload(payload);
    if (invalid) throw new Error(invalid);
    const tooLarge = checkBytes(payload);
    if (tooLarge) throw new Error(tooLarge);
    return payload;
  }
  function showAdaptationError(text) {
    el('adaptationError').textContent = text || '';
    el('adaptationError').hidden = !text;
  }
  function showAdaptationStatus(text) {
    el('adaptationStatus').textContent = text || '';
  }
  function syncAdaptationButtons() {
    el('adaptationSaveInput').disabled = adaptationBusy;
    el('adaptationDemo').disabled = adaptationBusy;
    el('adaptationReal').disabled = adaptationBusy;
    const analyzed = !!(adaptationResultArtifact &&
      adaptationResultArtifact.result_json &&
      Object.keys(adaptationResultArtifact.result_json).length);
    el('adaptationToDraft').disabled = adaptationBusy || !analyzed;
  }
  function setAdaptationBusy(value) {
    adaptationBusy = value;
    syncAdaptationButtons();
  }
  function adaptationReferenceDetail() {
    const value = el('adaptationReference').value;
    if (!value) {
      setSourceStatus('adaptationReferenceStatus', '', true);
      return;
    }
    request('/api/reference?id=' + encodeURIComponent(value), null).then(data => {
      // R4：参考详情异步返回后按实际目标身份重判，旧结果不写到新选择上。
      if (String(el('adaptationReference').value) !== String(value)) return;
      const report = data.report || {};
      const scope = data.scope || {};
      el('adaptationReferenceStatus').textContent =
        '参考：' + (data.title || '') + ' · 出处：' + (data.source_name || '未提供') +
        ' · 观察范围：' + (scope.limitation || '未提供') +
        ' · 摘要：' + String(report.summary || '').slice(0, 160);
      el('adaptationReferenceStatus').hidden = false;
    }).catch(error => {
      if (String(el('adaptationReference').value) !== String(value)) return;
      el('adaptationReferenceStatus').textContent = '参考详情读取失败，可重试：' + error.message;
      el('adaptationReferenceStatus').hidden = false;
    });
  }
  function renderAdaptationPains(pains) {
    const box = el('adaptationPains');
    box.innerHTML = pains.length ? pains.map(item =>
      '<label><input type="checkbox" data-pain-id="' + Number(item.id) + '"> ' +
      esc(String(item.pain || '').slice(0, 40)) + ' <small>' + esc(item.evidence_role || '') +
      '</small></label>').join('') : '<p class="script-hint">暂无痛点</p>';
  }
  function renderAdaptationReferences(refs) {
    const currentValue = el('adaptationReference').value;
    el('adaptationReference').innerHTML = '<option value="">（请选择一条外部参考）</option>' +
      refs.map(item => '<option value="' + Number(item.id) + '">' +
        esc(String(item.title || '未命名参考').slice(0, 60)) + ' · ' +
        esc(item.source_name || '未提供出处') + '</option>').join('');
    if (currentValue) el('adaptationReference').value = currentValue;
    adaptationReferenceDetail();
  }
  function renderAdaptationDrafts() {
    const currentValue = el('adaptationDraft').value;
    el('adaptationDraft').innerHTML = '<option value="">（不选研究稿）</option>' + drafts.map(item =>
      '<option value="' + esc(item.draft_uid) + '">' + esc(item.topic || '未命名研究稿') +
      '</option>').join('');
    if (currentValue) el('adaptationDraft').value = currentValue;
    renderAdaptationDraftVersions();
  }
  function renderAdaptationDraftVersions() {
    const uid = el('adaptationDraft').value;
    const draft = drafts.find(item => item.draft_uid === uid);
    const versions = draft ? (draft.versions || []) : [];
    const currentValue = el('adaptationDraftVersion').value;
    el('adaptationDraftVersion').innerHTML = '<option value="">—</option>' + versions.map(version =>
      '<option value="' + Number(version.version) + '">v' + Number(version.version) + ' · ' +
      esc(version.source || 'demo') + '</option>').join('');
    if (currentValue) el('adaptationDraftVersion').value = currentValue;
  }
  function renderAdaptationFrozenSources() {
    const box = el('adaptationFrozenSelected');
    const list = el('adaptationFrozenList');
    if (!adaptationFrozen.length) { box.hidden = true; list.innerHTML = ''; return; }
    box.hidden = false;
    list.innerHTML = adaptationFrozen.map((entry, index) =>
      '<div class="research-frozen-item"><strong>' + esc(entry.label || entry.kind) + '</strong> ' +
      esc(entry.identity || '') + ' <span class="research-frozen-status">' +
      esc(entry.status || '') + '</span><button type="button" class="text-button" data-adapt-frozen="' +
      index + '">移除该来源</button><div><small>出处：' + esc(entry.source || '未提供') +
      '；原文：' + esc(entry.text || '未提供') + '</small></div></div>').join('');
    list.querySelectorAll('[data-adapt-frozen]').forEach(button => {
      button.onclick = () => {
        adaptationFrozen.splice(Number(button.dataset.adaptFrozen), 1);
        renderAdaptationFrozenSources();
        updateAdaptationCount();
      };
    });
  }
  function addAdaptationFrozen(kind, data) {
    const key = kind + ':' + (data.uid || data.id || '');
    if (adaptationFrozen.some(entry => entry.key === key)) return;
    const labels = {reference: '指定外部参考', pain: '受众痛点', draft: '研究稿版本',
                    excerpt: '人工摘录'};
    adaptationFrozen.push({
      key: key, kind: kind, id: data.id, uid: data.uid, version: data.version,
      text: data.text || '', source: data.source || '',
      label: labels[kind] || kind,
      identity: kind + ' ' + (data.uid || data.id || '') +
        (data.version ? ' v' + data.version : ''),
      status: data.status || '列表未列出，重新分析时服务端校验',
    });
    renderAdaptationFrozenSources();
  }
  function adaptationExcerptRow(text, source) {
    const row = document.createElement('div');
    row.className = 'research-excerpt-row';
    row.innerHTML = '<textarea maxlength="6000" placeholder="粘贴摘录原文"></textarea>' +
      '<input maxlength="300" placeholder="出处说明（必填）">' +
      '<button type="button" class="text-button">移除此条</button>';
    row.querySelector('textarea').value = text || '';
    row.querySelector('input').value = source || '';
    row.querySelector('button').onclick = () => { row.remove(); updateAdaptationCount(); };
    return row;
  }
  function addAdaptationExcerpt(text, source) {
    el('adaptationExcerpts').appendChild(adaptationExcerptRow(text, source));
    updateAdaptationCount();
  }
  function adaptationCandidateStatus() {
    const parent = adaptationParents.find(item => item.artifact_uid === el('adaptationParent').value);
    const candidate = adaptationCandidateRows.find(row => String(row.id) === el('adaptationCandidate').value);
    if (!parent) {
      el('adaptationCandidateStatus').textContent = '请选择一条已保存的 B 选题记录；不会自动分析。';
      return;
    }
    if (!candidate) {
      el('adaptationCandidateStatus').textContent =
        'B ' + parent.artifact_uid + ' · ' + (parent.topic || '（无主题）') +
        '；请选择目标候选（不会自动分析）。';
      return;
    }
    el('adaptationCandidateStatus').textContent =
      'B ' + parent.artifact_uid + ' · 候选 ' + candidate.id + ' · ' + (candidate.topic || '') +
      ' · 状态：' + (candidate.state === 'research_candidate' ? '研究候选（未验证）' : '待验证') +
      '；服务端会加载该候选冻结链路。';
  }
  // R4：历史恢复/异步 loader 的归属 token：序号（页面或 C 记录）与目标父 UID 任一失效即放弃写 DOM。
  function adaptationRestoreFresh(view) {
    if (!view) return true;
    if (view.adapt !== undefined && view.adapt !== adaptationSeq) return false;
    if (view.page !== undefined && view.page !== pageSeq) return false;
    return true;
  }
  function adaptationRestoreToken(pageSeqValue) {
    return {adapt: adaptationSeq, page: pageSeqValue === undefined ? pageSeq : pageSeqValue};
  }
  async function prefetchAdaptationCandidates(uid, view) {
    const target = String(uid || '');
    if (!target) return [];
    const data = await request('/api/ops/research?id=' + encodeURIComponent(target), null);
    if (!adaptationRestoreFresh(view)) return null;
    if (!data || data.kind !== 'topics') return [];
    return (data.result_json || {}).candidates || [];
  }
  async function loadAdaptationCandidates(uid, view, preloaded) {
    const target = String(uid || '');
    const gen = ++adaptationCandidateGen;
    const owns = () => gen === adaptationCandidateGen &&
      String(el('adaptationParent').value || '') === target &&
      adaptationRestoreFresh(view);
    adaptationCandidateRows = [];
    el('adaptationCandidate').innerHTML = '<option value="">（请选择候选）</option>';
    adaptationCandidateStatus();
    if (!target) return;
    if (Array.isArray(preloaded)) {
      adaptationCandidateRows = preloaded;
      el('adaptationCandidate').innerHTML = '<option value="">（请选择候选）</option>' +
        preloaded.map(row => '<option value="' + esc(String(row.id)) + '">' +
          esc(row.id + ' · ' + String(row.topic || '').slice(0, 60)) + '</option>').join('');
      adaptationCandidateStatus();
      updateAdaptationCount();
      return;
    }
    try {
      const data = await request('/api/ops/research?id=' + encodeURIComponent(target), null);
      if (!owns()) return;
      if (data && data.kind === 'topics') {
        adaptationCandidateRows = (data.result_json || {}).candidates || [];
        el('adaptationCandidate').innerHTML = '<option value="">（请选择候选）</option>' +
          adaptationCandidateRows.map(row => '<option value="' + esc(String(row.id)) + '">' +
            esc(row.id + ' · ' + String(row.topic || '').slice(0, 60)) + '</option>').join('');
      }
    } catch (error) {
      // 旧失败不得把状态写到新父记录页面上。
      if (!owns()) return;
      el('adaptationCandidateStatus').textContent = '候选读取失败，可重试：' + error.message;
      return;
    }
    adaptationCandidateStatus();
    updateAdaptationCount();
  }
  async function loadAdaptationParents() {
    try {
      const rows = await request('/api/ops/research/list?kind=topics', null);
      adaptationParents = Array.isArray(rows) ? rows : [];
      const currentValue = el('adaptationParent').value;
      el('adaptationParent').innerHTML = '<option value="">（不选 B 记录）</option>' +
        adaptationParents.map(item => '<option value="' + esc(item.artifact_uid) + '">' +
          esc((item.topic || '（无主题）') + ' · ' + item.artifact_uid) + '</option>').join('');
      if (currentValue) el('adaptationParent').value = currentValue;
    } catch (error) {
      adaptationParents = [];
      el('adaptationParent').innerHTML = '<option value="">（B 列表读取失败，可重试）</option>';
    }
    adaptationCandidateStatus();
  }
  function adaptationSubjectBoxes() {
    const candidate = el('adaptationSubjectKind').value === 'candidate';
    el('adaptationManualBox').hidden = candidate;
    el('adaptationCandidateBox').hidden = !candidate;
  }
  function renderAdaptationReferenceInfo(context) {
    const box = el('adaptationReferenceInfo');
    box.innerHTML = '';
    const reference = (context || {}).reference || {};
    const title = adaptationNode('p', '', '');
    title.appendChild(adaptationNode('strong', '', '指定外部参考：'));
    title.appendChild(document.createTextNode(reference.title || '未提供'));
    box.appendChild(title);
    box.appendChild(adaptationNode('p', '', '出处：' + (reference.source || '未提供') +
      ' · 观察范围：' + (reference.scope || '未提供') +
      ' · 原记录时间：' + (reference.created_at || '未提供')));
    box.appendChild(adaptationNode('p', 'script-hint',
      '快照规则：' + (reference.snapshot_source === 'b_frozen'
        ? '该身份属于所选 B 候选冻结链路，按 B 冻结正文/出处；' : '本次明确选择，按原记录快照；') +
      (reference.note || '')));
  }
  function renderAdaptationPatterns(result, context) {
    const box = el('adaptationPatterns');
    box.innerHTML = '';
    const refs = Object.fromEntries(((context || {}).refs || []).map(ref => [ref.id, ref]));
    const refMap = (context || {}).ref_map || {};
    const chain = {};
    ((context || {}).basis_chain || []).forEach(row => {
      if (row && row.source_id) chain[row.source_id] = row;
    });
    const patterns = result.patterns || [];
    if (!patterns.length) {
      box.appendChild(adaptationNode('p', 'script-hint',
        '本次没有适配计划项；请查看“仍不能判断”，不要凑数生成。'));
      return;
    }
    patterns.forEach(item => {
      const card = adaptationNode('div', 'adaptation-pattern');
      const head = adaptationNode('div', 'adaptation-pattern-head');
      head.appendChild(adaptationNode('strong', '', '计划 ' + (item.id || '')));
      head.appendChild(adaptationNode('span', 'adaptation-aspect', adaptationAspectLabel(item.aspect)));
      card.appendChild(head);
      const addField = (label, value) => {
        const row = adaptationNode('p', 'adaptation-field');
        row.appendChild(adaptationNode('b', '', label + '：'));
        row.appendChild(document.createTextNode(value || '（无）'));
        card.appendChild(row);
      };
      addField('如何替换', item.text);
      addField('为什么 / 边界', item.why);
      addField('本业务依据（business_basis）', (item.business_basis || []).join('、') ||
        '无——本业务证明未提供');
      addField('条件', (item.conditions || []).join('；'));
      addField('缺口', (item.gaps || []).join('；'));
      addField('下一步', item.next_step || '未提供');
      if (item.reference_excerpt) addField('参考短摘录', item.reference_excerpt);
      const details = document.createElement('details');
      details.appendChild(adaptationNode('summary', '', '展开依据（真实来源与角色）'));
      (item.basis || []).forEach(sourceId => {
        const ref = refs[sourceId] || {};
        const origin = refMap[sourceId] || {};
        const chainRow = chain[sourceId] || {};
        const row = adaptationNode('div', 'adaptation-basis-row');
        row.appendChild(adaptationNode('strong', '',
          sourceId + ' [' + (ref.label || '未知来源') + '] '));
        row.appendChild(document.createTextNode('真实身份：kind=' + (origin.kind || '未提供') +
          (origin.id !== undefined ? '，id=' + origin.id : '') +
          (origin.uid ? '，uid=' + origin.uid : '') +
          (origin.version ? '，version=' + origin.version : '') +
          (origin.index !== undefined ? '，index=' + origin.index : '') +
          (origin.snapshot ? '，快照=' + origin.snapshot : '') +
          '；出处：' + (ref.source || '未提供') +
          (chainRow.parent_sid ? '；父路径：B 来源 ' + chainRow.parent_sid : '')));
        row.appendChild(adaptationNode('p', 'adaptation-basis-text',
          ref.text || '（原文未提供）'));
        details.appendChild(row);
      });
      if (!(item.basis || []).length) {
        details.appendChild(adaptationNode('p', 'script-hint', '没有引用本次冻结来源。'));
      }
      card.appendChild(details);
      box.appendChild(card);
    });
  }
  function renderAdaptationNon(result) {
    const box = el('adaptationNonTransferable');
    box.innerHTML = '';
    const rows = result.non_transferable || [];
    if (!rows.length) {
      box.appendChild(adaptationNode('p', 'script-hint',
        '本次未列出不能照搬项；不代表参考全部可复制。'));
      return;
    }
    rows.forEach(item => {
      const card = adaptationNode('div', 'adaptation-non');
      const head = adaptationNode('p', '', '');
      head.appendChild(adaptationNode('strong', '', (item.id || '') + ' · 不能照搬：'));
      head.appendChild(document.createTextNode(item.text || ''));
      card.appendChild(head);
      card.appendChild(adaptationNode('p', 'script-hint',
        '原因：' + (item.why || '') + '；依据：' + ((item.basis || []).join('、') || '无') +
        '；条件：' + ((item.conditions || []).join('；') || '无') +
        '；缺口：' + ((item.gaps || []).join('；') || '无') +
        '；下一步：' + (item.next_step || '未提供')));
      box.appendChild(card);
    });
  }
  function renderAdaptationCannot(result) {
    const box = el('adaptationCannot');
    box.innerHTML = '';
    const items = result.cannot_judge || [];
    if (!items.length) { box.appendChild(adaptationNode('p', 'script-hint', '（无）')); return; }
    const list = document.createElement('ul');
    items.forEach(item => list.appendChild(adaptationNode('li', '', item)));
    box.appendChild(list);
  }
  function renderAdaptationFrozenInfo(context) {
    const box = el('adaptationFrozen');
    box.innerHTML = '';
    const strategy = (context || {}).strategy || {};
    box.appendChild(adaptationNode('p', '', ''));
    const strategyLine = box.lastChild;
    strategyLine.appendChild(adaptationNode('strong', '', '冻结策略：'));
    strategyLine.appendChild(document.createTextNode('版本 v' + (strategy.version || 0) + ' · ' +
      (strategy.confirmed ? '已确认' : '未确认')));
    const data = strategy.data || {};
    Object.keys(data).forEach(key => {
      const value = Array.isArray(data[key]) ? data[key].join('；') : data[key];
      box.appendChild(adaptationNode('p', 'script-hint', key + '：' + value));
    });
    const refs = (context || {}).refs || [];
    const refMap = (context || {}).ref_map || {};
    const chain = {};
    ((context || {}).basis_chain || []).forEach(row => { if (row && row.source_id) chain[row.source_id] = row; });
    refs.forEach(ref => {
      const origin = refMap[ref.id] || {};
      const chainRow = chain[ref.id] || {};
      const item = adaptationNode('div', 'research-item');
      item.appendChild(adaptationNode('p', '', ''));
      const head = item.lastChild;
      head.appendChild(adaptationNode('strong', '',
        ref.id + ' [' + (ref.label || '') + '] '));
      head.appendChild(document.createTextNode(ref.source || '出处未提供'));
      item.appendChild(adaptationNode('p', 'script-hint',
        '真实身份：kind=' + (origin.kind || '未提供') +
        (origin.id !== undefined ? '，id=' + origin.id : '') +
        (origin.uid ? '，uid=' + origin.uid : '') +
        (origin.version ? '，version=' + origin.version : '') +
        (origin.index !== undefined ? '，index=' + origin.index : '') +
        (chainRow.parent_sid ? '；父路径：B 来源 ' + chainRow.parent_sid : '')));
      item.appendChild(adaptationNode('p', 'adaptation-basis-text', ref.text || ''));
      box.appendChild(item);
    });
  }
  function renderAdaptationArtifact(artifact) {
    adaptationResultArtifact = artifact;
    const result = (artifact && artifact.result_json) || {};
    const context = (artifact && artifact.context_json) || {};
    const analyzed = !!(artifact && artifact.result_json &&
      Object.keys(artifact.result_json).length);
    el('adaptationResult').hidden = false;
    el('adaptationSource').textContent = adaptationSourceLabel(artifact.source);
    el('adaptationMeta').textContent = adaptationSourceLabel(artifact.source);
    el('adaptationMeta').className = 'script-badge' + (artifact.source ? ' ' + artifact.source : '');
    el('adaptationSummary').textContent = analyzed
      ? (result.summary || '（无摘要）')
      : '（未分析：只保存了输入，未调用模型；下面不是适配计划）';
    renderAdaptationReferenceInfo(context);
    applyIndustryFrozen(context, 'adaptationIndustrySummary', 'adaptationIndustryFrozen');
    renderAdaptationPatterns(result, context);
    renderAdaptationNon(result);
    renderAdaptationCannot(result);
    renderAdaptationFrozenInfo(context);
    el('adaptationExport').href = '/api/ops/research/export?id=' +
      encodeURIComponent(artifact.artifact_uid);
    el('adaptationDraftResult').hidden = true;
    syncAdaptationButtons();
  }
  async function loadAdaptationHistory() {
    try {
      const list = await request('/api/ops/research/list?kind=adaptation', null);
      const rows = Array.isArray(list) ? list : [];
      const box = el('adaptationHistory');
      box.innerHTML = '';
      if (!rows.length) {
        box.appendChild(adaptationNode('p', 'script-hint', '还没有参考适配记录。'));
        return;
      }
      rows.forEach(item => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'adaptation-history-item' +
          (adaptationResultArtifact && adaptationResultArtifact.artifact_uid === item.artifact_uid
            ? ' active' : '');
        button.dataset.openAdaptation = item.artifact_uid;
        button.appendChild(document.createTextNode(item.topic || '（无主题）'));
        const small = document.createElement('small');
        small.textContent = 'C ' + item.artifact_uid + ' · 父 B ' + (item.parent_uid || '无') +
          ' · ' + adaptationSourceLabel(item.source) + ' · ' +
          (item.analyzed ? '有结果' : '未分析') +
          (item.summary ? ' · ' + String(item.summary).slice(0, 40) : '') +
          ' · ' + new Date((item.created_at || 0) * 1000).toLocaleString('zh-CN');
        button.appendChild(small);
        button.addEventListener('click', () => { openAdaptationArtifact(item.artifact_uid); });
        box.appendChild(button);
      });
    } catch (error) {
      const box = el('adaptationHistory');
      box.innerHTML = '';
      box.appendChild(adaptationNode('p', 'script-hint', '适配历史读取失败，可重试：' + error.message));
      const retry = document.createElement('button');
      retry.type = 'button';
      retry.className = 'secondary compact';
      retry.textContent = '重试';
      retry.addEventListener('click', () => { loadAdaptationHistory(); });
      box.appendChild(retry);
    }
  }
  async function adaptationAnalyze(real) {
    if (adaptationBusy) return;
    showAdaptationError('');
    const seq = ++adaptationSeq;
    let payload, submitted;
    try {
      payload = adaptationPayload(real, false);
      if (real) {
        if (!el('adaptationConfirm').checked) throw new Error('真实调用需勾选本次确认');
        el('adaptationConfirm').checked = false;
      }
      // R4：基线取请求前的提交快照，不取响应后的当前表单。
      submitted = adaptationSnapshot();
    } catch (error) {
      if (seq === adaptationSeq) showAdaptationError(error.message);
      return;
    }
    setAdaptationBusy(true);
    el('adaptationMeta').textContent = real ? '适配中…' : '演示适配中…';
    el('adaptationMeta').className = 'script-badge';
    try {
      const data = await request('/api/ops/research/adaptation', payload);
      if (seq !== adaptationSeq) { loadAdaptationHistory(); return; }
      renderAdaptationArtifact(data.artifact);
      adaptationBaseline = submitted;
      updateAdaptationStale();
      showAdaptationStatus('已生成并保存适配计划 ' + data.artifact.artifact_uid + '（' +
        adaptationSourceLabel(data.artifact.source) + '）；不会自动转稿。');
      loadAdaptationHistory();
    } catch (error) {
      if (seq === adaptationSeq) showAdaptationError(error.message);
    } finally {
      if (seq === adaptationSeq) setAdaptationBusy(false);
    }
  }
  async function adaptationSaveInput() {
    if (adaptationBusy) return;
    showAdaptationError('');
    const seq = ++adaptationSeq;
    let payload, submitted;
    try {
      payload = adaptationPayload(false, true);
      submitted = adaptationSnapshot();
    } catch (error) {
      if (seq === adaptationSeq) showAdaptationError(error.message);
      return;
    }
    setAdaptationBusy(true);
    try {
      const data = await request('/api/ops/research/save', payload);
      if (seq !== adaptationSeq) { loadAdaptationHistory(); return; }
      renderAdaptationArtifact(data.artifact);
      adaptationBaseline = submitted;
      updateAdaptationStale();
      showAdaptationStatus('已保存适配输入 ' + data.artifact.artifact_uid +
        '（未分析，未调用模型）。');
      loadAdaptationHistory();
    } catch (error) {
      if (seq === adaptationSeq) showAdaptationError(error.message);
    } finally {
      if (seq === adaptationSeq) setAdaptationBusy(false);
    }
  }
  function showAdaptationDraftLink(uid, stale) {
    const box = el('adaptationDraftResult');
    if (stale) {
      showAdaptationStatus('转稿已保存：研究稿 ' + uid + '（当前页面未切换）。');
      return;
    }
    box.innerHTML = '';
    box.hidden = false;
    box.appendChild(document.createTextNode('已保存为 M02 研究稿（0 版本、未生成）：' + uid + ' '));
    const link = document.createElement('a');
    link.href = '/draft?id=' + encodeURIComponent(uid);
    link.className = 'text-button';
    link.textContent = '打开研究稿';
    box.appendChild(link);
    box.appendChild(document.createTextNode('（不会自动生成正文，需你显式点击生成）'));
  }
  async function adaptationToDraft() {
    if (adaptationBusy || !adaptationResultArtifact) return;
    const artifact = adaptationResultArtifact;
    if (!artifact.result_json || !Object.keys(artifact.result_json).length) {
      showAdaptationError('适配记录未分析，不能转研究稿；请先生成适配计划。');
      return;
    }
    const payload = {artifact_uid: artifact.artifact_uid};
    const tooLarge = checkBytes(payload);
    if (tooLarge) { showAdaptationError('转稿请求超过 65536 字节上限'); return; }
    showAdaptationError('');
    showAdaptationStatus('正在转为研究稿输入…');
    const seq = ++adaptationSeq;
    setAdaptationBusy(true);
    try {
      const data = await request('/api/ops/research/adaptation-to-draft', payload);
      if (seq !== adaptationSeq) {
        showAdaptationDraftLink(data.draft.draft_uid, true);
        return;
      }
      showAdaptationDraftLink(data.draft.draft_uid, false);
      showAdaptationStatus('已保存为研究稿输入（0 版本、未生成）；不会自动调用模型。');
      loadAdaptationHistory();
      loadDrafts();
    } catch (error) {
      if (seq === adaptationSeq) showAdaptationError(error.message);
    } finally {
      if (seq === adaptationSeq) setAdaptationBusy(false);
    }
  }
  async function fillAdaptationForm(input, context, view) {
    const data = input || {};
    const subject = data.subject || {};
    const owns = () => adaptationRestoreFresh(view);
    const before = adaptationSnapshot();
    let prefetched = null;
    if (subject.kind === 'candidate') {
      prefetched = await prefetchAdaptationCandidates(subject.artifact_uid || '', view);
      if (prefetched === null) return false;
      if (adaptationSnapshot() !== before &&
          !confirm('等待期间有新的适配编辑，打开该历史会覆盖；继续？')) return false;
      if (!owns()) return false;
    }
    adaptationFrozen = [];
    el('adaptationSubjectKind').value = subject.kind === 'candidate' ? 'candidate' : 'manual';
    adaptationSubjectBoxes();
    el('adaptationTopic').value = subject.topic || '';
    FIELDS.forEach(pair => {
      const adaptId = ADAPT_FIELDS.find(item => item[1] === pair[1])[0];
      el(adaptId).value = ((subject.business) || {})[pair[1]] || '';
    });
    el('adaptationInstruction').value = data.instruction || '';
    // 主题来源（candidate）与参考。
    const parentUid = subject.artifact_uid || '';
    if (subject.kind === 'candidate') {
      const parentOptions = [...el('adaptationParent').options].map(option => option.value);
      if (parentUid && parentOptions.indexOf(parentUid) < 0) {
        const option = document.createElement('option');
        option.value = parentUid;
        option.textContent = (context.parent && context.parent.topic) ||
          ('B ' + parentUid + '（当前列表未列出）');
        el('adaptationParent').appendChild(option);
      }
      el('adaptationParent').value = parentUid;
      await loadAdaptationCandidates(parentUid, view, prefetched);
      // R4：内部 await 之后、任何 DOM/勾选/来源/基线写入之前重判归属。
      if (!owns()) return false;
      const candidateId = subject.candidate_id || '';
      const candidateOptions = [...el('adaptationCandidate').options].map(option => option.value);
      if (candidateId && candidateOptions.indexOf(candidateId) < 0) {
        const option = document.createElement('option');
        option.value = candidateId;
        option.textContent = '候选 ' + candidateId + '（当前列表未列出）';
        el('adaptationCandidate').appendChild(option);
        addAdaptationFrozen('candidate', {id: candidateId, status: '候选未列出，重新分析时服务端校验'});
      }
      el('adaptationCandidate').value = candidateId;
    } else {
      if (!owns()) return false;
      el('adaptationParent').value = '';
      el('adaptationCandidate').innerHTML = '<option value="">（请选择候选）</option>';
    }
    adaptationCandidateStatus();
    const referenceId = data.reference_id || 0;
    const referenceOptions = [...el('adaptationReference').options].map(option => option.value);
    if (referenceId && referenceOptions.indexOf(String(referenceId)) < 0) {
      const option = document.createElement('option');
      option.value = String(referenceId);
      option.textContent = '参考 ' + referenceId + '（当前列表未列出）';
      el('adaptationReference').appendChild(option);
      const reference = context.reference || {};
      addAdaptationFrozen('reference', {id: referenceId, text: reference.excerpt || '',
                                        source: reference.source || '',
                                        status: '参考未列出，重新分析时服务端校验'});
    }
    el('adaptationReference').value = referenceId ? String(referenceId) : '';
    adaptationReferenceDetail();
    // 痛点。
    document.querySelectorAll('#adaptationPains input[data-pain-id]').forEach(box => { box.checked = false; });
    (data.selected && data.selected.pain_ids || []).forEach(id => {
      if (findCheckbox('#adaptationPains input[data-pain-id]', 'painId', String(Number(id)))) {
        findCheckbox('#adaptationPains input[data-pain-id]', 'painId', String(Number(id))).checked = true;
      } else {
        addAdaptationFrozen('pain', {id: Number(id), status: '痛点未列出，重新分析时服务端校验'});
      }
    });
    // 稿件版本。
    const draftUid = (data.selected && data.selected.draft_uid) || '';
    if (draftUid) {
      const draftOptions = [...el('adaptationDraft').options].map(option => option.value);
      if (draftOptions.indexOf(draftUid) < 0) {
        const option = document.createElement('option');
        option.value = draftUid;
        option.textContent = '研究稿 ' + draftUid + '（当前列表未列出）';
        el('adaptationDraft').appendChild(option);
        addAdaptationFrozen('draft', {uid: draftUid, version: (data.selected || {}).draft_version,
                                      status: '稿件未列出，重新分析时服务端校验'});
      }
      el('adaptationDraft').value = draftUid;
      renderAdaptationDraftVersions();
      const version = String(((data.selected || {}).draft_version) || '');
      const versionOptions = [...el('adaptationDraftVersion').options].map(option => option.value);
      if (version && versionOptions.indexOf(version) < 0) {
        const option = document.createElement('option');
        option.value = version;
        option.textContent = 'v' + version;
        el('adaptationDraftVersion').appendChild(option);
      }
      el('adaptationDraftVersion').value = version;
    } else {
      el('adaptationDraft').value = '';
      renderAdaptationDraftVersions();
    }
    // 摘录。
    el('adaptationExcerpts').innerHTML = '';
    const excerpts = (data.selected && data.selected.manual_excerpts) || [];
    if (excerpts.length) excerpts.forEach(item => addAdaptationExcerpt(item.text, item.source));
    else addAdaptationExcerpt('', '');
    updateAdaptationCount();
    renderAdaptationFrozenSources();
    return true;
  }
  async function openAdaptationArtifact(uid) {
    if (adaptationBusy) return;
    if (adaptationDirty() &&
        !confirm('当前适配输入有未保存修改，打开历史会覆盖；继续？')) return;
    const before = adaptationSnapshot();
    const seq = ++adaptationSeq;
    const view = adaptationRestoreToken();
    setAdaptationBusy(true);
    try {
      const data = await request('/api/ops/research?id=' + encodeURIComponent(uid), null);
      if (seq !== adaptationSeq) return;
      if (adaptationSnapshot() !== before &&
          !confirm('等待期间有新的编辑，打开适配历史会覆盖；继续？')) return;
      if (data.kind !== 'adaptation') throw new Error('该记录不是参考适配记录');
      const filled = await fillAdaptationForm(data.input_json || {}, data.context_json || {},
                                             view);
      if (seq !== adaptationSeq || filled === false) return;
      // P1：表单/候选/等待期确认全部成功后才提交结果、来源、导出与基线。
      renderAdaptationArtifact(data);
      restoreIndustrySelect(data.context_json || {}, 'adaptationIndustry', true);
      adaptationBaseline = adaptationSnapshot();
      updateAdaptationStale();
      showAdaptationStatus('已打开适配记录 ' + data.artifact_uid +
        '（冻结快照；不重新分析，不自动转稿）');
      loadAdaptationHistory();
    } catch (error) {
      if (seq === adaptationSeq) showAdaptationError(error.message);
    } finally {
      if (seq === adaptationSeq) setAdaptationBusy(false);
    }
  }
  function renderResult(artifact) {
    currentTopics = null;
    topicsResult = null;
    topicsRoleBaseline = {};
    topicsRoleMap = {};
    topicsRoleKey = null;
    el('topicsResult').hidden = true;
    el('topicsDraftResult').hidden = true;
    current = artifact;
    resultInput = artifact.input_json || {};
    const result = artifact.result_json || {};
    const context = artifact.context_json || {};
    applyIndustryFrozen(context, 'researchIndustrySummary', 'researchIndustryFrozen');
    const refs = Object.fromEntries((context.refs || []).map(ref => [ref.id, ref]));
    el('researchResultCard').hidden = false;
    el('researchSource').textContent = sourceLabel(artifact.source);
    el('researchSummary').textContent = result.summary || '（未分析）';
    rows(el('researchObservations'), result.observations || [], false);
    rows(el('researchInferences'), result.inferences || [], true);
    rows(el('researchSuggestions'), result.suggestions || [], true);
    el('researchConflicts').innerHTML = (result.conflicts || []).length
      ? result.conflicts.map(row => '<div class="research-item"><p>' + esc(row.text) +
        '</p><p><small>依据：' + basisLabel(row.basis, refs) + '；说明：' + esc(row.why || '') +
        '</small></p></div>').join('')
      : '<p class="script-hint">（无）</p>';
    el('researchCannot').innerHTML = (result.cannot_judge || []).length
      ? '<ul>' + result.cannot_judge.map(item => '<li>' + esc(item) + '</li>').join('') + '</ul>'
      : '<p class="script-hint">（无）</p>';
    renderFrozen(artifact);
    el('researchExport').href = '/api/ops/research/export?id=' + encodeURIComponent(artifact.artifact_uid);
    setMeta(sourceLabel(artifact.source), artifact.source);
    renderTopicsParent();
    updateStale();
  }
  function fillForm(input) {
    const data = input || {};
    restoreSeq += 1;
    restoreState = {token: restoreSeq, savedSnapshot: normalizedInput(data), edited: false};
    frozenSources = [];
    renderFrozenSources();
    el('researchTopic').value = data.topic || '';
    el('researchQuestion').value = data.question || '';
    FIELDS.forEach(pair => { el(pair[0]).value = ((data.business) || {})[pair[1]] || ''; });
    document.querySelectorAll('#researchPains input[data-pain-id]').forEach(box => { box.checked = false; });
    document.querySelectorAll('#researchReferences input[data-ref-id]').forEach(box => { box.checked = false; });
    el('researchDraft').value = '';
    el('researchDraftVersion').innerHTML = '<option value="">—</option>';
    el('researchRecord').value = '';
    el('researchConsultations').innerHTML = '';
    el('researchReviews').innerHTML = '';
    el('researchExcerpts').innerHTML = '';
    pendingRestore = data.selected || {};
    applyPendingRestore();
  }
  function finishRestore() {
    if (!restoreState || !pendingRestore) return;
    const saved = restoreState.savedSnapshot;
    pendingRestore = null;
    restoreState = null;
    baseline = saved;
    updateCount();
    updateStale();
  }
  function materializePendingSelection() {
    if (!restoreState || !pendingRestore) return;
    const sel = pendingRestore;
    const status = '恢复等待中，已保留；分析时重校验';
    (sel.pain_ids || []).forEach(id => {
      if (!findCheckbox('#researchPains input[data-pain-id]', 'painId', String(Number(id)))) {
        addFrozen('pain', {id: Number(id)}, status, false);
      }
    });
    (sel.reference_ids || []).forEach(id => {
      if (!findCheckbox('#researchReferences input[data-ref-id]', 'refId', String(Number(id)))) {
        addFrozen('reference', {id: Number(id)}, status, false);
      }
    });
    if (sel.draft_uid && el('researchDraft').value !== sel.draft_uid) {
      addFrozen('draft', {uid: sel.draft_uid, version: sel.draft_version || 0}, status, false);
    }
    if (sel.record_uid && el('researchRecord').value !== sel.record_uid) {
      addFrozen('record', {uid: sel.record_uid}, status, false);
    }
    (sel.consultation_ids || []).forEach(uid => {
      if (!findCheckbox('#researchConsultations input[data-note-id]', 'noteId', uid)) {
        addFrozen('consultation', {uid: uid}, status, false);
      }
    });
    (sel.review_uids || []).forEach(uid => {
      if (!findCheckbox('#researchReviews input[data-review-id]', 'reviewId', uid)) {
        addFrozen('review', {uid: uid}, status, false);
      }
    });
    (sel.manual_excerpts || []).forEach(item => {
      const rows = [...document.querySelectorAll('#researchExcerpts .research-excerpt-row')];
      const exists = rows.some(row => row.querySelector('textarea').value.trim() === item.text &&
        row.querySelector('input').value.trim() === item.source);
      if (!exists) addExcerpt(item.text, item.source);
    });
  }
  function applyPendingRestore() {
    if (!pendingRestore) return;
    if (!restoreState || restoreState.token !== restoreSeq) {
      pendingRestore = null;
      return;
    }
    const sel = pendingRestore;
    if ((sel.pain_ids || []).length && !painsLoaded) return;
    if ((sel.reference_ids || []).length && !refsLoaded) return;
    if (sel.draft_uid && !draftsLoaded) return;
    if (sel.record_uid && !recordsLoaded) return;
    if (restoreState.edited) {
      if (!confirm('恢复历史尚未完成，继续会覆盖你在等待期间的编辑；继续？')) {
        finishRestore();
        return;
      }
      restoreState.edited = false;
    }
    document.querySelectorAll('#researchPains input[data-pain-id]').forEach(box => { box.checked = false; });
    (sel.pain_ids || []).forEach(id => {
      const box = findCheckbox('#researchPains input[data-pain-id]', 'painId', String(Number(id)));
      if (box) box.checked = true;
      else addFrozen('pain', {id: Number(id)});
    });
    document.querySelectorAll('#researchReferences input[data-ref-id]').forEach(box => { box.checked = false; });
    (sel.reference_ids || []).forEach(id => {
      const box = findCheckbox('#researchReferences input[data-ref-id]', 'refId', String(Number(id)));
      if (box) box.checked = true;
      else addFrozen('reference', {id: Number(id)});
    });
    const draftUid = sel.draft_uid || '';
    if (draftUid) {
      const options = [...el('researchDraft').options].map(option => option.value);
      if (options.indexOf(draftUid) >= 0) {
        el('researchDraft').value = draftUid;
        renderDraftVersions();
        el('researchDraftVersion').value = String(sel.draft_version || '');
      } else {
        addFrozen('draft', {uid: draftUid, version: sel.draft_version || 0});
      }
    } else {
      setSourceStatus('researchDraftStatus', '', true);
    }
    el('researchExcerpts').innerHTML = '';
    const excerpts = sel.manual_excerpts || [];
    if (excerpts.length) {
      excerpts.forEach(item => addExcerpt(item.text, item.source));
    } else {
      addExcerpt('', '');
    }
    const recordUid = sel.record_uid || '';
    if (recordUid) {
      const options = [...el('researchRecord').options].map(option => option.value);
      if (options.indexOf(recordUid) >= 0) {
        el('researchRecord').value = recordUid;
        loadRecordSources(sel);
        return;
      }
      addFrozen('record', {uid: recordUid});
    } else {
      setSourceStatus('researchRecordStatus', '', true);
    }
    (sel.consultation_ids || []).forEach(uid => {
      const box = findCheckbox('#researchConsultations input[data-note-id]', 'noteId', uid);
      if (box) box.checked = true;
      else addFrozen('consultation', {uid: uid});
    });
    (sel.review_uids || []).forEach(uid => {
      const box = findCheckbox('#researchReviews input[data-review-id]', 'reviewId', uid);
      if (box) box.checked = true;
      else addFrozen('review', {uid: uid});
    });
    finishRestore();
  }
  async function openArtifact(uid) {
    const wasDirty = dirty() || rolesDirty();
    const rolesBefore = rolesSignature(topicsRoleMap);
    restoreSeq += 1;
    pendingRestore = null;
    restoreState = null;
    const before = snapshot();
    const adaptationBefore = adaptationSnapshot();
    const seq = nextPage();
    try {
      const data = await request('/api/ops/research?id=' + encodeURIComponent(uid), null);
      if (seq !== pageSeq) return;
      const rolesChangedDuring = rolesSignature(topicsRoleMap) !== rolesBefore;
      if (data && data.kind === 'topics') {
        // R3：GET 等待期角色编辑也要在回填前重判；取消保持当前 A/B 输入与结果。
        if ((rolesDirty() || rolesChangedDuring) &&
            !confirm('需求角色声明有未保存修改，打开另一条记录会覆盖；继续？')) return;
        currentTopics = data;
        topicsResult = data;
        renderTopicsArtifact(data, {restoreRoles: true});
        showStatus('已打开选题建议 B ' + data.artifact_uid + '（冻结快照；不重新分析父记录或选题）');
        loadHistory();
        loadTopicsHistory();
        return;
      }
      if (data && data.kind === 'adaptation') {
        if (adaptationDirty() && !confirm('当前适配输入有未保存修改，打开另一条记录会覆盖；继续？')) return;
        if (adaptationSnapshot() !== adaptationBefore &&
            !confirm('等待期间有新的适配编辑，打开历史会覆盖；继续？')) return;
        const filled = await fillAdaptationForm(data.input_json || {}, data.context_json || {},
                                               adaptationRestoreToken(seq));
        if (seq !== pageSeq || filled === false) return;
        // P1：全部准备与确认成功后才提交结果、来源、导出与基线。
        renderAdaptationArtifact(data);
        restoreIndustrySelect(data.context_json || {}, 'adaptationIndustry', true);
        adaptationBaseline = adaptationSnapshot();
        updateAdaptationStale();
        showStatus('已打开适配记录 C ' + data.artifact_uid + '（冻结快照；不重新分析）');
        loadHistory();
        loadTopicsHistory();
        loadAdaptationHistory();
        return;
      }
      if ((wasDirty || rolesDirty() || rolesChangedDuring || snapshot() !== before) &&
          !confirm('当前输入或需求角色声明有未保存修改，打开历史会覆盖；继续？')) return;
      currentTopics = null;
      topicsResult = null;
      el('topicsResult').hidden = true;
      el('topicsDraftResult').hidden = true;
      current = data;
      fillForm(data.input_json || {});
      renderResult(data);
      restoreIndustrySelect(data.context_json || {}, 'researchIndustry', false);
      baseline = snapshot();
      showStatus('已打开历史研究 ' + data.artifact_uid + '（冻结快照）');
      loadHistory();
      loadTopicsHistory();
      renderTopicsParent();
    } catch (error) {
      if (seq === pageSeq) showError(error.message);
    }
  }
  async function save() {
    if (busy || pending) return;
    showError('');
    const seq = nextPage();
    materializePendingSelection();
    const payload = currentInput();
    restoreSeq += 1;
    pendingRestore = null;
    restoreState = null;
    const invalid = validatePayload(payload);
    if (invalid) { showError(invalid); return; }
    const tooLarge = checkBytes(payload);
    if (tooLarge) { showError(tooLarge); return; }
    const submitted = snapshot();
    const hadCurrent = !!current;
    pending = true;
    setBusy(true);
    try {
      const data = await request('/api/ops/research/save', payload);
      if (seq !== pageSeq) { loadHistory(); return; }
      baseline = submitted;
      current = data.artifact;
      currentTopics = null;
      topicsResult = null;
      topicsRoleBaseline = {};
      topicsRoleMap = {};
      topicsRoleKey = null;
      el('topicsResult').hidden = true;
      showStatus('已保存输入 ' + data.artifact.artifact_uid + '（未分析）；可稍后打开或演示研究。');
      if (!hadCurrent) setMeta('人工保存（未分析）', 'manual');
      renderTopicsParent();
      updateStale();
      loadHistory();
    } catch (error) {
      if (seq === pageSeq) showError(error.message);
    } finally {
      if (seq === pageSeq) { pending = false; setBusy(false); }
    }
  }
  async function analyze(real) {
    if (busy || pending) return;
    showError('');
    const seq = nextPage();
    materializePendingSelection();
    const payload = currentInput();
    restoreSeq += 1;
    pendingRestore = null;
    restoreState = null;
    try {
      Object.assign(payload, modeFields(real));
      const invalid = validatePayload(payload);
      if (invalid) { showError(invalid); return; }
      const tooLarge = checkBytes(payload);
      if (tooLarge) { showError(tooLarge); return; }
      consumeConfirm(real);
      const submitted = snapshot();
      pending = true;
      setBusy(true);
      setMeta(real ? '研究中…' : '演示研究…');
      const data = await request('/api/ops/research/analyze', payload);
      if (seq !== pageSeq) { loadHistory(); return; }
      renderResult(data.artifact);
      baseline = submitted;
      renderTopicsParent();
      showStatus('研究完成');
      loadHistory();
    } catch (error) {
      if (seq === pageSeq) {
        if (!current) setMeta('待研究');
        showError(error.message);
      }
    } finally {
      if (seq === pageSeq) { pending = false; setBusy(false); }
    }
  }
  function markRestoreEdited() {
    if (restoreState && pendingRestore) restoreState.edited = true;
  }
  function findFrozenRef(kind, origin) {
    const context = (current && current.context_json) || {};
    const map = context.ref_map || {};
    for (const ref of context.refs || []) {
      const entry = map[ref.id] || {};
      if (entry.kind !== kind) continue;
      if (origin.id !== undefined && entry.id === origin.id) return ref;
      if (origin.uid && entry.uid === origin.uid &&
          (origin.version === undefined || entry.version === origin.version)) return ref;
    }
    return null;
  }
  function renderFrozenSources() {
    const box = el('researchFrozenSelected');
    const list = el('researchFrozenList');
    if (!frozenSources.length) {
      box.hidden = true;
      list.innerHTML = '';
      return;
    }
    box.hidden = false;
    list.innerHTML = frozenSources.map((entry, index) =>
      '<div class="research-frozen-item"><strong>' + esc(entry.label || entry.kind) + '</strong> ' +
      esc(entry.identity || '') + ' <span class="research-frozen-status">' + esc(entry.status || '') +
      '</span><button type="button" class="text-button" data-frozen-remove="' + index +
      '">移除该来源</button><div><small>出处：' + esc(entry.source || '未提供') +
      '；原文：' + esc(entry.text || '未提供') + '</small></div></div>').join('');
    list.querySelectorAll('[data-frozen-remove]').forEach(button => {
      button.onclick = () => removeFrozen(Number(button.dataset.frozenRemove));
    });
  }
  function addFrozen(kind, origin, statusOverride, probe) {
    const identityKey = kind + ':' + (origin.uid || origin.id) +
      (origin.version ? ':' + origin.version : '');
    if (frozenSources.some(entry => entry.key === identityKey)) return;
    const ref = findFrozenRef(kind, origin);
    const labels = {pain: '受众痛点', reference: '外部参考', draft: '研究稿版本',
                    record: '本作品登记', consultation: '咨询摘录', review: '复盘'};
    const entry = {
      key: identityKey, kind, id: origin.id, uid: origin.uid, version: origin.version,
      label: (ref && ref.label) || labels[kind] || kind,
      text: (ref && ref.text) || '',
      source: (ref && ref.source) || '',
      identity: kind + ' ' + (origin.uid || origin.id) +
        (origin.version ? ' v' + origin.version : ''),
      status: statusOverride || (kind === 'pain' || kind === 'reference' || kind === 'draft'
        ? '确认中…' : '列表未列出，分析时重校验'),
    };
    frozenSources.push(entry);
    renderFrozenSources();
    if (probe !== false && (kind === 'pain' || kind === 'reference' || kind === 'draft')) {
      confirmFrozenAvailability(entry);
    }
  }
  async function confirmFrozenAvailability(entry) {
    try {
      if (entry.kind === 'pain' || entry.kind === 'reference') {
        const data = await request('/api/' + entry.kind + '?id=' + encodeURIComponent(entry.id), null);
        entry.status = data ? '详情可用（列表未列出）' : '未找到';
      } else if (entry.kind === 'draft') {
        await initial;
        const response = await fetch('/api/ops/draft/export?id=' + encodeURIComponent(entry.uid) +
          '&version=' + encodeURIComponent(entry.version || 0));
        entry.status = response.ok ? '版本详情可用（列表未列出）' : '已归档或不存在';
      }
    } catch (error) {
      entry.status = /不存在|归档|版本/.test(error.message) ? '已归档或不存在' : '读取失败，可重试';
    }
    renderFrozenSources();
  }
  function removeFrozen(index) {
    const entry = frozenSources[index];
    if (!entry) return;
    frozenSources.splice(index, 1);
    if (restoreState && pendingRestore) {
      const sel = pendingRestore;
      if (entry.kind === 'pain') {
        sel.pain_ids = (sel.pain_ids || []).filter(id => Number(id) !== Number(entry.id));
      } else if (entry.kind === 'reference') {
        sel.reference_ids = (sel.reference_ids || []).filter(id => Number(id) !== Number(entry.id));
      } else if (entry.kind === 'consultation') {
        sel.consultation_ids = (sel.consultation_ids || []).filter(uid => uid !== entry.uid);
      } else if (entry.kind === 'review') {
        sel.review_uids = (sel.review_uids || []).filter(uid => uid !== entry.uid);
      } else if (entry.kind === 'draft') {
        sel.draft_uid = '';
        sel.draft_version = 0;
      } else if (entry.kind === 'record') {
        sel.record_uid = '';
      }
    }
    markRestoreEdited();
    renderFrozenSources();
    updateCount();
    updateStale();
  }
  function clearFrozenKind() {
    const kinds = Array.prototype.slice.call(arguments);
    frozenSources = frozenSources.filter(entry => kinds.indexOf(entry.kind) < 0);
    renderFrozenSources();
  }
  function renderPains(pains) {
    el('researchPains').innerHTML = pains.length ? pains.map(item =>
      '<label><input type="checkbox" data-pain-id="' + Number(item.id) + '"> ' +
      esc(String(item.pain || '').slice(0, 40)) + ' <small>' + esc(item.evidence_role || '') + '</small></label>').join('')
      : '<p class="script-hint">暂无痛点</p>';
  }
  function renderReferences(refs) {
    el('researchReferences').innerHTML = refs.length ? refs.map(item =>
      '<label><input type="checkbox" data-ref-id="' + Number(item.id) + '"> ' +
      esc(String(item.title || '').slice(0, 40)) + ' <small>外部参考</small></label>').join('')
      : '<p class="script-hint">暂无参考</p>';
  }
  async function loadPains() {
    try {
      const pains = await request('/api/pain/list', null);
      painsLoaded = true;
      renderPains(pains);
      renderAdaptationPains(pains);
    } catch (error) {
      painsLoaded = true;
      el('researchPains').innerHTML = '<p class="script-hint">痛点读取失败，可重试</p>';
      el('adaptationPains').innerHTML = '<p class="script-hint">痛点读取失败，可重试</p>';
    }
    if (pendingRestore) applyPendingRestore();
  }
  async function loadReferences() {
    try {
      const refs = await request('/api/reference/list', null);
      refsLoaded = true;
      renderReferences(refs);
      renderAdaptationReferences(refs);
    } catch (error) {
      refsLoaded = true;
      el('researchReferences').innerHTML = '<p class="script-hint">参考读取失败，可重试</p>';
      el('adaptationReference').innerHTML = '<option value="">（参考读取失败，可重试）</option>';
    }
    if (pendingRestore) applyPendingRestore();
  }
  function renderDraftVersions() {
    const uid = el('researchDraft').value;
    const draft = drafts.find(item => item.draft_uid === uid);
    const versions = draft ? (draft.versions || []) : [];
    el('researchDraftVersion').innerHTML = '<option value="">—</option>' + versions.map(version =>
      '<option value="' + Number(version.version) + '">v' + Number(version.version) + ' · ' +
      esc(version.source || 'demo') + '</option>').join('');
  }
  async function loadDrafts() {
    try {
      drafts = await request('/api/ops/draft/list', null);
      draftsLoaded = true;
      setSourceStatus('researchDraftStatus', '', true);
      el('researchDraft').innerHTML = '<option value="">（不选研究稿）</option>' + drafts.map(item =>
        '<option value="' + esc(item.draft_uid) + '">' + esc(item.topic || '未命名研究稿') + '</option>').join('');
      renderDraftVersions();
      renderAdaptationDrafts();
    } catch (error) {
      draftsLoaded = true;
      drafts = [];
      el('researchDraft').innerHTML = '<option value="">（读取失败）</option>';
      setSourceStatus('researchDraftStatus', '研究稿读取失败，可重试', false);
      el('adaptationDraft').innerHTML = '<option value="">（读取失败）</option>';
    }
    if (pendingRestore) applyPendingRestore();
  }
  async function loadRecords() {
    try {
      records = await request('/api/feedback/records', null);
      recordsLoaded = true;
      setSourceStatus('researchRecordStatus', '', true);
      el('researchRecord').innerHTML = '<option value="">（不选作品登记）</option>' + records.map(item =>
        '<option value="' + esc(item.record_uid) + '">' + esc((item.platform || '') + ' · ' +
        (item.platform_post_id || '')) + '</option>').join('');
    } catch (error) {
      recordsLoaded = true;
      records = [];
      el('researchRecord').innerHTML = '<option value="">（读取失败）</option>';
      setSourceStatus('researchRecordStatus', '作品登记读取失败，可重试', false);
    }
    if (pendingRestore) applyPendingRestore();
    else loadRecordSources();
  }
  async function loadRecordSources(selectedOverride) {
    const uid = el('researchRecord').value;
    const gen = ++recordGen;
    const restoreToken = selectedOverride ? (restoreState ? restoreState.token : -1) : null;
    const restoreSel = selectedOverride || null;
    const restoreValid = () => !selectedOverride || (!!restoreState &&
      restoreState.token === restoreToken && restoreSeq === restoreToken &&
      pendingRestore === restoreSel);
    el('researchConsultations').innerHTML = '';
    el('researchReviews').innerHTML = '';
    if (!uid) {
      if (selectedOverride && restoreValid()) finishRestore();
      updateCount();
      return;
    }
    let notes = null;
    let notesFailed = false;
    try {
      notes = await request('/api/feedback/consultations?record=' + encodeURIComponent(uid), null);
    } catch (error) {
      notesFailed = true;
      if (gen === recordGen && el('researchRecord').value === uid &&
          (!selectedOverride || restoreValid())) {
        el('researchConsultations').innerHTML = '<p class="script-hint">咨询读取失败，可重试</p>';
      }
    }
    if (gen !== recordGen || el('researchRecord').value !== uid) return;
    if (selectedOverride && !restoreValid()) return;
    if (notes) {
      el('researchConsultations').innerHTML = notes.length ? notes.map(item =>
        '<label><input type="checkbox" data-note-id="' + esc(item.note_uid) + '"> ' +
        esc(String(item.text || '').slice(0, 40)) + ' <small>咨询摘录</small></label>').join('')
        : '<p class="script-hint">该登记暂无咨询</p>';
    }
    if (selectedOverride) {
      const wanted = new Set(selectedOverride.consultation_ids || []);
      if (notes) {
        document.querySelectorAll('#researchConsultations input[data-note-id]').forEach(box => {
          box.checked = wanted.has(box.dataset.noteId);
        });
      }
      wanted.forEach(wantedUid => {
        if (!findCheckbox('#researchConsultations input[data-note-id]', 'noteId', wantedUid)) {
          addFrozen('consultation', {uid: wantedUid},
                    notesFailed ? '读取失败，可重试' : '列表未列出，分析时重校验');
        }
      });
    }
    let reviews = null;
    let reviewsFailed = false;
    try {
      reviews = await request('/api/feedback/reviews?record=' + encodeURIComponent(uid), null);
    } catch (error) {
      reviewsFailed = true;
      if (gen === recordGen && el('researchRecord').value === uid &&
          (!selectedOverride || restoreValid())) {
        el('researchReviews').innerHTML = '<p class="script-hint">复盘读取失败，可重试</p>';
      }
    }
    if (gen !== recordGen || el('researchRecord').value !== uid) return;
    if (selectedOverride && !restoreValid()) return;
    if (reviews) {
      el('researchReviews').innerHTML = reviews.length ? reviews.map(item =>
        '<label><input type="checkbox" data-review-id="' + esc(item.review_uid) + '"> ' +
        '复盘 ' + esc(item.review_uid) + '</label>').join('')
        : '<p class="script-hint">该登记暂无复盘</p>';
    }
    if (selectedOverride) {
      const wanted = new Set(selectedOverride.review_uids || []);
      if (reviews) {
        document.querySelectorAll('#researchReviews input[data-review-id]').forEach(box => {
          box.checked = wanted.has(box.dataset.reviewId);
        });
      }
      wanted.forEach(wantedUid => {
        if (!findCheckbox('#researchReviews input[data-review-id]', 'reviewId', wantedUid)) {
          addFrozen('review', {uid: wantedUid},
                    reviewsFailed ? '读取失败，可重试' : '列表未列出，分析时重校验');
        }
      });
    }
    updateCount();
    if (selectedOverride && restoreValid()) finishRestore();
  }
  async function loadStrategy() {
    try {
      const strategy = await request('/api/strategy', null);
      const data = strategy.data || {};
      const entries = Object.keys(data).length
        ? Object.keys(data).map(key => '<p>' + esc(key) + '：' +
          esc(Array.isArray(data[key]) ? data[key].join('；') : data[key]) + '</p>').join('')
        : '<p class="script-hint">未提供策略内容；不得假设存在默认已确认策略。</p>';
      el('researchStrategyBody').innerHTML = entries;
      el('researchStrategyState').textContent = 'v' + (strategy.version || 0) + ' · ' +
        (strategy.confirmed ? '已确认' : '未确认') + '（当前策略；历史报告的冻结策略见结果区）';
    } catch (error) {
      el('researchStrategyBody').innerHTML = '<p class="script-hint">策略读取失败</p>';
      el('researchStrategyState').textContent = '读取失败';
    }
  }
  async function loadHistory() {
    try {
      const list = await request('/api/ops/research/list?kind=research', null);
      const rows = Array.isArray(list) ? list : [];
      el('researchHistory').innerHTML = rows.length ? rows.map(item =>
        '<button class="research-history-item' + (current && current.artifact_uid === item.artifact_uid ? ' active' : '') +
        '" data-open="' + esc(item.artifact_uid) + '">' + esc(item.topic || '（无主题）') +
        ' <small>' + esc(sourceLabel(item.source)) + ' · ' +
        (item.analyzed ? '有结果' : '未分析') + ' · ' +
        new Date((item.created_at || 0) * 1000).toLocaleString('zh-CN') +
        (item.summary ? ' · ' + esc(item.summary.slice(0, 40)) : '') + '</small></button>').join('')
        : '<p class="script-hint">还没有研究记录。</p>';
      el('researchHistory').querySelectorAll('[data-open]').forEach(button => {
        button.onclick = () => openArtifact(button.dataset.open);
      });
    } catch (error) {
      el('researchHistory').innerHTML = '<p class="script-hint">历史读取失败：' + esc(error.message) + '</p>';
    }
  }

  el('adaptationAddExcerpt').onclick = () => addAdaptationExcerpt('', '');
  el('adaptationSaveInput').onclick = () => { adaptationSaveInput(); };
  el('adaptationDemo').onclick = () => { adaptationAnalyze(false); };
  el('adaptationReal').onclick = () => { adaptationAnalyze(true); };
  el('adaptationToDraft').onclick = () => { adaptationToDraft(); };
  el('adaptationSubjectKind').addEventListener('change', () => {
    adaptationSubjectBoxes();
    adaptationCandidateStatus();
    updateAdaptationCount();
    showAdaptationStatus('主题来源已切换；不会自动分析。');
  });
  el('adaptationReference').addEventListener('change', () => {
    adaptationReferenceDetail();
    updateAdaptationCount();
    showAdaptationStatus('指定参考已切换；不会自动分析。');
  });
  el('adaptationParent').addEventListener('change', () => {
    el('adaptationCandidate').innerHTML = '<option value="">（请选择候选）</option>';
    loadAdaptationCandidates(el('adaptationParent').value);
    updateAdaptationCount();
    showAdaptationStatus('B 记录已切换；不会自动分析。');
  });
  el('adaptationCandidate').addEventListener('change', () => {
    adaptationCandidateStatus();
    updateAdaptationCount();
    showAdaptationStatus('候选已切换；不会自动分析。');
  });
  el('adaptationDraft').addEventListener('change', () => {
    renderAdaptationDraftVersions();
    updateAdaptationCount();
  });
  el('adaptationPains').addEventListener('change', () => { updateAdaptationCount(); });
  el('adaptationDraftVersion').addEventListener('change', () => { updateAdaptationCount(); updateAdaptationStale(); });
  el('adaptationExcerpts').addEventListener('input', () => { updateAdaptationCount(); });
  el('adaptationExcerpts').addEventListener('change', () => { updateAdaptationCount(); });
  ['adaptationTopic', 'adaptationInstruction'].concat(ADAPT_FIELDS.map(pair => pair[0]))
    .forEach(id => {
      el(id).addEventListener('input', () => { updateAdaptationCount(); });
      el(id).addEventListener('change', () => { updateAdaptationCount(); });
    });
  adaptationSubjectBoxes();
  adaptationBaseline = adaptationSnapshot();
  loadAdaptationParents();
  loadAdaptationHistory();
  syncAdaptationButtons();
  el('researchAddExcerpt').onclick = () => addExcerpt('', '');
  el('researchSave').onclick = save;
  el('researchDemo').onclick = () => analyze(false);
  el('researchReal').onclick = () => analyze(true);
  el('topicsDemo').onclick = () => topicsGenerate(false);
  el('topicsReal').onclick = () => topicsGenerate(true);
  el('researchDraft').addEventListener('change', () => {
    markRestoreEdited();
    clearFrozenKind('draft');
    renderDraftVersions();
    updateCount();
    updateStale();
  });
  el('researchRecord').addEventListener('change', () => {
    markRestoreEdited();
    if (restoreState && pendingRestore) {
      // 用户明确切换/清空登记：取消旧登记及旧咨询/复盘的待恢复意图，
      // 只固化与登记无关的痛点/参考/稿件/摘录，再结束旧恢复。
      pendingRestore.record_uid = '';
      pendingRestore.consultation_ids = [];
      pendingRestore.review_uids = [];
      materializePendingSelection();
      pendingRestore = null;
      restoreState = null;
      restoreSeq += 1;
    }
    clearFrozenKind('record', 'consultation', 'review');
    loadRecordSources();
    updateCount();
    updateStale();
  });
  ['researchTopic', 'researchQuestion', 'researchDraftVersion'].concat(FIELDS.map(pair => pair[0])).forEach(id => {
    el(id).addEventListener('input', () => { markRestoreEdited(); updateCount(); updateStale(); });
    el(id).addEventListener('change', () => { markRestoreEdited(); updateCount(); updateStale(); });
  });
  el('researchExcerpts').addEventListener('input', () => { markRestoreEdited(); updateCount(); updateStale(); });
  el('researchExcerpts').addEventListener('change', () => { markRestoreEdited(); updateCount(); updateStale(); });
  document.addEventListener('change', event => {
    if (event.target && event.target.type === 'checkbox') {
      markRestoreEdited();
      updateCount();
      updateStale();
    }
  });
  addExcerpt('', '');
  baseline = snapshot();
  fillIndustrySelect('researchIndustry', '', false);
  fillIndustrySelect('adaptationIndustry', '', true);
  ['researchIndustry', 'adaptationIndustry'].forEach(id => {
    el(id).addEventListener('change', () => {
      el(id).dataset.edited = '1';
      if (id === 'researchIndustry') updateStale();
      else updateAdaptationStale();
    });
  });
  loadIndustryCatalog();
  loadStrategy();
  loadPains();
  loadReferences();
  loadDrafts().then(loadRecords);
  loadHistory();
  loadTopicsHistory();
  renderTopicsParent();
  initial.then(() => {
    if (typeof location === 'undefined') return;
    const uid = new URLSearchParams(location.search).get('id');
    if (uid && /^[a-f0-9]{12}$/.test(uid)) openArtifact(uid);
  }).catch(() => {});
})();
