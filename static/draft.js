(() => {
  const el = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const INDUSTRY_FALLBACK = [
    ['generic', '通用内容'], ['health_education', '健康与医学科普'],
    ['science_education', '自然科学与生活原理'], ['finance_education', '财经知识科普'],
    ['law_education', '法律知识科普'], ['education_learning', '教育与学习'],
    ['technology_digital', '科技与数码'], ['culture_history', '文化与历史'],
    ['career_skills', '职场与技能'], ['food_cooking', '美食与烹饪'],
    ['local_service', '本地服务'], ['physical_product', '实物产品'],
  ];
  let industryCatalog = [];
  let industryLoadSeq = 0;
  function fillIndustrySelect(id, value, inherit) {
    const select = el(id);
    if (!select) return;
    const items = industryCatalog.length ? industryCatalog
      : INDUSTRY_FALLBACK.map(([code, label]) => ({code, label}));
    select.innerHTML = '<option value="">' + (inherit
      ? '缺省（继承当前版本/通用）' : '通用内容（缺省/历史未保存模板）') + '</option>' +
      items.map(item => '<option value="' + esc(item.code) + '">' + esc(item.label) + '</option>').join('');
    select.value = value || '';
  }
  function fillWorkbenchIndustry(value) {
    const select = el('draftWorkbenchIndustry');
    if (!select) return;
    const items = industryCatalog.length ? industryCatalog
      : INDUSTRY_FALLBACK.map(([code, label]) => ({code, label}));
    select.innerHTML = '<option value="">' + (el('draftOperation').value === 'optimize'
      ? '缺省：继承当前版本' : '缺省：沿用当前模板或使用通用内容') + '</option>' +
      items.map(item => '<option value="' + esc(item.code) + '">' + esc(item.label) + '</option>').join('');
    select.value = value || '';
  }
  function industryLabel(context) {
    const raw = context && context.industry;
    if (raw && raw.code) return raw.label + '（' + raw.code + ' · v' + raw.template_version + '）';
    return '通用（历史未保存模板）';
  }
  function sourceLabel(source) {
    return source === 'demo' ? '演示' : source === 'llm' ? '真实模型' :
      source === 'manual' ? '人工' : source || '来源未记录';
  }
  function fillIndustryFrozen(version) {
    const context = (version || {}).context_json || {};
    const node = el('draftIndustryFrozen');
    if (!node) return;
    node.hidden = false;
    node.textContent = '该版本冻结模板：' + industryLabel(context) + '。模板只提供提问与表达约束，不是事实或依据。';
  }
  async function loadIndustryCatalog() {
    const loadId = ++industryLoadSeq;
    try {
      const rows = await request('/api/ops/industry/catalog', null);
      if (loadId !== industryLoadSeq) return;
      if (Array.isArray(rows) && rows.length) industryCatalog = rows;
    } catch (error) { /* 静态选项保留 */ }
    if (loadId !== industryLoadSeq) return;
    fillIndustrySelect('draftIndustry', el('draftIndustry').value, false);
    fillIndustrySelect('draftOptimizeIndustry', el('draftOptimizeIndustry').value, true);
    fillWorkbenchIndustry(el('draftWorkbenchIndustry').value);
    updateWorkbench();
  }
  let token = '', current = null, versions = [], selectedVersion = 0, busy = false, pageSeq = 0;
  let baseline = {topic: '', business: '', audience: '', goal: '', resources: '', capacity: '', selected: '|'};
  let optimizeBaseline = '';
  let busySeq = 0;
  let extrasLoadSeq = 0;
  let extraArtifacts = [];

  const initial = fetch('/api/state?mode=live').then(async r => {
    if (!r.ok) throw new Error('本机连接失败，请重新打开页面');
    token = (await r.json()).token;
  });
  initial.catch(error => { el('draftError').textContent = error.message; });

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

  const REQUEST_BYTES = 65536;
  function checkBytes(payload) {
    const size = new TextEncoder().encode(JSON.stringify(payload)).byteLength;
    return size > REQUEST_BYTES ? '本次请求约 ' + size + ' 字节，超过 65536 字节上限，请精简输入' : '';
  }

  function selectionKey() {
    const picked = selectedIds();
    return picked.pain_ids.join(',') + '|' + picked.reference_ids.join(',');
  }
  function collect() {
    return {
      topic: el('draftTopic').value.trim(),
      business: el('draftBusiness').value.trim(), audience: el('draftAudience').value.trim(),
      goal: el('draftGoal').value.trim(), resources: el('draftResources').value.trim(),
      capacity: el('draftCapacity').value.trim(), selected: selectionKey(),
      industry: el('draftIndustry') ? el('draftIndustry').value : '',
    };
  }
  function status() {
    const form = collect();
    return {business: form.business, audience: form.audience, goal: form.goal,
            resources: form.resources, capacity: form.capacity, question: ''};
  }
  function fill(values) {
    const form = values || {};
    el('draftBusiness').value = form.business || '';
    el('draftAudience').value = form.audience || '';
    el('draftGoal').value = form.goal || '';
    el('draftResources').value = form.resources || '';
    el('draftCapacity').value = form.capacity || '';
  }
  function sameForm(left, right) {
    return Object.keys(right).every(key => (left[key] || '') === (right[key] || ''));
  }
  function optimizeState() {
    return {
      baseVersion: selectedVersion,
      targets: [...document.querySelectorAll('[data-opt-target]:checked')].map(box => box.dataset.optTarget),
      instruction: el('draftInstruction').value,
      maxChars: el('draftMaxChars').value.trim(),
      extras: [...document.querySelectorAll('#draftExtraChoices [data-uid]:checked')].map(box => box.dataset.uid),
      industry: el('draftOptimizeIndustry') ? el('draftOptimizeIndustry').value : '',
    };
  }
  function optimizeKey() {
    const state = optimizeState();
    return JSON.stringify([state.baseVersion, state.targets, state.instruction,
                           state.maxChars, [...state.extras].sort(), state.industry]);
  }
  function dirty() {
    return !sameForm(collect(), baseline) || optimizeKey() !== optimizeBaseline;
  }
  function resetBaseline() { baseline = collect(); optimizeBaseline = optimizeKey(); }
  function syncWorkbenchTemplate() {
    const value = el('draftWorkbenchIndustry').value;
    el('draftIndustry').value = value;
    el('draftOptimizeIndustry').value = value;
  }
  function setDisclosure(toggleId, contentId, open) {
    const button = el(toggleId);
    const content = el(contentId);
    content.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
    button.parentElement.classList.toggle('is-open', open);
  }
  function bindDisclosure(toggleId, contentId) {
    el(toggleId).onclick = () => setDisclosure(toggleId, contentId, el(contentId).hidden);
  }
  function updateCounts() {
    const count = (selector) => document.querySelectorAll(selector + ':checked').length;
    el('draftPainCount').textContent = count('#draftPainChoices [data-pain-id]') + ' 已选';
    el('draftReferenceCount').textContent = count('#draftReferenceChoices [data-ref-id]') + ' 已选';
    updateSelectedMaterials();
  }
  function updateSelectedMaterials() {
    const chips = [];
    const add = (selector, kind, idName, keyName) => {
      document.querySelectorAll(selector + ':checked').forEach(box => {
        const label = (box.parentElement.textContent || '').trim().replace(/\s+/g, ' ');
        chips.push({kind, id: box.dataset[idName], key: keyName, label});
      });
    };
    add('#draftPainChoices [data-pain-id]', '痛点', 'painId', 'pain');
    add('#draftReferenceChoices [data-ref-id]', '参考', 'refId', 'reference');
    add('#draftExtraChoices [data-uid]', '资料', 'uid', 'extra');
    el('draftSelectedMaterials').innerHTML = chips.length
      ? '<p class="script-hint">已选资料（点 × 可移除）</p><div class="draft-chip-list">' + chips.map(item =>
          '<span class="draft-chip"><span>' + esc(item.kind + ' · ' + item.label) + '</span><button type="button" data-remove-kind="' +
          item.key + '" data-remove-id="' + esc(item.id) + '" aria-label="移除' + esc(item.kind + '：' + item.label) + '">×</button></span>'
        ).join('') + '</div>'
      : '<p class="script-hint">未选择资料，可跳过。</p>';
    const optionalFields = ['draftBusiness', 'draftAudience', 'draftGoal', 'draftResources', 'draftCapacity',
      'draftMaxChars', 'draftInstruction'].filter(id => el(id).value.trim()).length;
    const painCount = document.querySelectorAll('#draftPainChoices [data-pain-id]:checked').length;
    const referenceCount = document.querySelectorAll('#draftReferenceChoices [data-ref-id]:checked').length;
    const extraCount = document.querySelectorAll('#draftExtraChoices [data-uid]:checked').length;
    const total = optionalFields + painCount + referenceCount + extraCount;
    el('draftAdvancedSummary').textContent = total
      ? '已补充 ' + total + ' 项 · 痛点 ' + painCount + ' · 参考 ' + (referenceCount + extraCount)
      : '可选 · 默认收起 · 演示不会补造资料';
  }
  function ensureDefaultTargets() {
    if (document.querySelector('[data-opt-target]:checked')) return;
    ['hook', 'structure'].forEach(key => {
      const box = document.querySelector('[data-opt-target="' + key + '"]');
      if (box) box.checked = true;
    });
  }
  function updateSourceBar(version) {
    const item = version || versions.find(row => row.version === selectedVersion) ||
      (current && current.current_version) || null;
    if (!current) {
      el('draftSourceBar').textContent = '新研究稿：输入一个主题即可开始演示试跑。';
      return;
    }
    if (!item) {
      el('draftSourceBar').textContent = '正在查看：' + (current.topic || '未命名研究稿') + ' · 尚未生成版本';
      return;
    }
    const date = item.created_at ? new Date(item.created_at * 1000).toLocaleDateString('zh-CN') : '日期未记录';
    el('draftSourceBar').textContent = '正在查看：' + date + ' · ' +
      (item.topic || current.topic || '未命名研究稿') + ' · v' + (item.version || selectedVersion) + ' · ' + sourceLabel(item.source);
  }
  function updateWorkbench() {
    const hasVersion = !!(current && selectedVersion);
    const optimize = el('draftOperation').value === 'optimize' && hasVersion;
    el('draftOperation').querySelector('option[value="optimize"]').disabled = !hasVersion;
    if (el('draftOperation').value === 'optimize' && !hasVersion) el('draftOperation').value = 'generate';
    el('draftOptimizeTargets').hidden = !optimize;
    if (optimize) el('draftOptimizeBase').textContent = '基于哪一版修改：v' + selectedVersion + '（生成新版本，不改动原版）';
    fillWorkbenchIndustry(el('draftWorkbenchIndustry').value);
    syncWorkbenchTemplate();
    const real = el('draftExecutionMode').value === 'real';
    const verb = optimize ? '优化研究稿' : '生成研究稿';
    el('draftRun').textContent = optimize ? '开始优化' + (real ? '（真实调用）' : '（演示）')
      : verb + (real ? '（真实调用）' : '（演示）');
    el('draftRunNotice').textContent = real
      ? '真实模式会调用配置的模型服务并可能产生费用；每次执行前还会再次确认。'
      : '演示试跑不会调用模型；仅验证本地流程并保存演示版本。';
    el('draftIndustrySummary').textContent = el('draftOperation').value === 'optimize'
      ? '不选就继承当前版本 v' + selectedVersion + '；手动选择只影响本次。模板不提供业务事实。'
      : '新稿默认使用通用内容；手动选择只影响本次。模板只提供表达约束。';
    document.querySelectorAll('.draft-step-rail span').forEach((step, index) => {
      step.classList.toggle('active', index === (optimize ? 1 : 0));
    });
    updateCounts();
    updateSourceBar();
    const isDirty = dirty();
    el('draftDirty').textContent = isDirty ? '有未保存修改' : '当前输入与已保存内容一致';
    el('draftDirty').classList.toggle('is-dirty', isDirty);
  }
  function selectedIds() {
    const pain_ids = [...document.querySelectorAll('#draftPainChoices [data-pain-id]:checked')].map(box => Number(box.dataset.painId));
    const reference_ids = [...document.querySelectorAll('#draftReferenceChoices [data-ref-id]:checked')].map(box => Number(box.dataset.refId));
    return {pain_ids: pain_ids, reference_ids: reference_ids};
  }
  function setSelections(refs) {
    const pains = new Set((refs || []).filter(ref => String(ref.id || '').startsWith('pain:'))
      .map(ref => Number(String(ref.id).slice(5))));
    const references = new Set((refs || []).filter(ref => String(ref.id || '').startsWith('ref:'))
      .map(ref => Number(String(ref.id).slice(4))));
    document.querySelectorAll('#draftPainChoices [data-pain-id]').forEach(box => {
      box.checked = pains.has(Number(box.dataset.painId));
    });
    document.querySelectorAll('#draftReferenceChoices [data-ref-id]').forEach(box => {
      box.checked = references.has(Number(box.dataset.refId));
    });
  }
  function mode(real) {
    if (!real) return {model_mode: 'test', confirm: false};
    return {model_mode: 'real', confirm: true};
  }
  function setBusy(value, text) {
    busy = value;
    ['draftSave', 'draftRun']
      .forEach(id => { el(id).disabled = value; });
    if (text) el('draftStatus').textContent = text;
  }
  function newTopicNote() {
    if (!current) { el('draftNewTopic').hidden = true; return; }
    const topic = el('draftTopic').value.trim();
    const show = !!(topic && topic !== (current.topic || ''));
    el('draftNewTopic').hidden = !show;
    el('draftNewTopic').textContent = show ? '新主题：生成将创建一条新研究稿，不并入当前稿。' : '';
  }

  async function saveDraft() {
    if (busy) return;
    el('draftError').textContent = '';
    const snapshot = collect();
    const payload = {topic: el('draftTopic').value, status: status(), selected: selectedIds()};
    if (el('draftIndustry').value) payload.industry = el('draftIndustry').value;
    const tooLarge = checkBytes(payload);
    if (tooLarge) { el('draftError').textContent = tooLarge; return; }
    const seq = ++pageSeq;
    busySeq = seq;
    try {
      setBusy(true, '保存中…');
      const data = await request('/api/ops/draft/save', payload);
      if (seq !== pageSeq) { loadList(); return; }
      current = data.draft;
      versions = [];
      selectedVersion = 0;
      el('draftContent').hidden = true;
      el('draftEmptyState').hidden = false;
      el('draftVersionLabel').textContent = '已保存（未生成）';
      el('draftVersionInput').textContent = '';
      el('draftExport').href = '#';
      el('draftNewTopic').hidden = true;
      renderVersionList();
      baseline = snapshot;
      el('draftStatus').textContent = '已保存 ' + data.draft.draft_uid + '（未生成，资料已随稿保存）';
      updateWorkbench();
      loadList();
    } catch (error) {
      if (seq === pageSeq) { el('draftStatus').textContent = ''; el('draftError').textContent = error.message; }
    } finally {
      if (busySeq === seq) { busySeq = 0; setBusy(false); }
    }
  }

  async function generate(real) {
    if (busy) return;
    el('draftError').textContent = '';
    const snapshot = collect();
    const seq = ++pageSeq;
    try {
      const payload = Object.assign({topic: el('draftTopic').value, status: status(),
                                     selected: selectedIds()}, mode(real));
      if (el('draftIndustry').value) payload.industry = el('draftIndustry').value;
      if (current) payload.draft_uid = current.draft_uid;
      const tooLarge = checkBytes(payload);
      if (tooLarge) { el('draftError').textContent = tooLarge; return; }
      busySeq = seq;
      setBusy(true, real ? '生成中…' : '演示生成中…');
      const data = await request('/api/ops/draft/generate', payload);
      if (seq !== pageSeq) {
        loadList();
        return;
      }
      render(data.draft, {fillForm: false});
      baseline = snapshot;
      optimizeBaseline = optimizeKey();
      el('draftStatus').textContent = '生成完成（' + sourceLabel((data.draft.current_version || {}).source) + '）';
      updateWorkbench();
      loadList();
    } catch (error) {
      if (seq === pageSeq) { el('draftStatus').textContent = ''; el('draftError').textContent = error.message; }
    } finally {
      if (busySeq === seq) { busySeq = 0; setBusy(false); }
    }
  }

  async function optimize(real) {
    if (busy) return;
    el('draftError').textContent = '';
    el('draftOptimizeStatus').textContent = '';
    if (!current) { el('draftOptimizeStatus').textContent = '请先生成或打开一条研究稿'; return; }
    if (!selectedVersion) { el('draftOptimizeStatus').textContent = '请先选择一篇已有研究稿'; return; }
    const targets = [...document.querySelectorAll('[data-opt-target]:checked')].map(box => box.dataset.optTarget);
    if (!targets.length) { el('draftOptimizeStatus').textContent = '请至少选择一个优化目标'; return; }
    if (targets.length > 5) { el('draftOptimizeStatus').textContent = '优化目标最多 5 项'; return; }
    const maxText = el('draftMaxChars').value.trim();
    let maxChars = null;
    if (maxText) {
      if (!/^\d+$/.test(maxText)) {
        el('draftOptimizeStatus').textContent = '正文字符硬上限必须是整数';
        return;
      }
      maxChars = Number(maxText);
      if (maxChars < 50 || maxChars > 10000) {
        el('draftOptimizeStatus').textContent = '正文字符硬上限必须在 50–10000 之间';
        return;
      }
    }
    const extras = [...document.querySelectorAll('#draftExtraChoices [data-uid]:checked')]
      .map(box => box.dataset.uid);
    if (extras.length > 12) { el('draftOptimizeStatus').textContent = '参考与咨询记录最多选择 12 条'; return; }
    const optimizeSnapshot = optimizeKey();
    const startUid = current.draft_uid;
    const seq = ++pageSeq;
    try {
      const optimization = {targets: targets, additional_artifact_uids: extras};
      if (maxChars !== null) optimization.max_body_chars = maxChars;
      const payload = Object.assign({draft_uid: current.draft_uid, base_version: selectedVersion,
                                     instruction: el('draftInstruction').value,
                                     optimization: optimization}, mode(real));
      if (el('draftOptimizeIndustry').value) {
        payload.industry = el('draftOptimizeIndustry').value;
      }
      const tooLarge = checkBytes(payload);
      if (tooLarge) { el('draftError').textContent = tooLarge; return; }
      busySeq = seq;
      setBusy(true, real ? '优化中…' : '演示优化中…');
      el('draftOptimizeStatus').textContent = real ? '优化中…' : '演示优化中…';
      const data = await request('/api/ops/draft/optimize', payload);
      if (seq !== pageSeq) {
        loadList();
        if (current && current.draft_uid === startUid) {
          el('draftOptimizeStatus').textContent = '结果已保存到原稿；当前页面未变';
        }
        return;
      }
      render(data.draft, {fillForm: false});
      const savedVersion = (data.draft.current_version || {}).version || selectedVersion;
      const submitted = JSON.parse(optimizeSnapshot);
      // 只推进实际随请求保存的优化参数，并对应新结果版本；表单业务/主题基线不动。
      optimizeBaseline = JSON.stringify([savedVersion, submitted[1], submitted[2],
                                         submitted[3], submitted[4], submitted[5]]);
      const version = (data.draft.current_version || {});
      const meta = ((version.context_json || {}).draft_optimization) || {};
      el('draftOptimizeStatus').textContent = '优化完成，已保存为 v' + (version.version || '') +
        (version.base_version ? '（基于 v' + version.base_version + '）' : '') +
        (version.source === 'demo' ? '（演示：仅追加说明，未真正改写正文）' : '') +
        (meta.body_chars ? ' · 正文 ' + meta.body_chars + ' 码点' : '');
      el('draftStatus').textContent = el('draftOptimizeStatus').textContent;
      updateWorkbench();
      loadList();
    } catch (error) {
      if (seq !== pageSeq) return;
      el('draftStatus').textContent = '';
      el('draftOptimizeStatus').textContent = '';
      el('draftError').textContent = error.message;
    } finally {
      if (busySeq === seq) { busySeq = 0; setBusy(false); }
    }
  }

  function artifactLabel(item) {
    const kind = item.kind === 'adaptation' ? '参考' : '咨询';
    return kind + ' · ' + (item.topic || '（无主题）') + ' · ' + sourceLabel(item.source);
  }

  function renderExtraChoices(meta, preserve) {
    meta = meta || {};
    const selected = (meta.selected_artifacts || []).map(item => item.artifact_uid).filter(Boolean);
    const inherited = new Set((meta.inherited_artifacts || []).map(item => item.artifact_uid));
    const keep = new Set();
    if (preserve) {
      document.querySelectorAll('#draftExtraChoices [data-uid]').forEach(box => {
        if (box.checked) keep.add(box.dataset.uid);
      });
    }
    const items = extraArtifacts.slice();
    (meta.selected_artifacts || []).forEach(item => {
      if (item.artifact_uid && !items.some(row => row.artifact_uid === item.artifact_uid)) {
        items.push({artifact_uid: item.artifact_uid, kind: item.kind,
                    topic: item.topic, source: item.source});
      }
    });
    if (!items.length) {
      el('draftExtraChoices').innerHTML = '<p class="script-hint">暂无已分析的参考与咨询记录。</p>';
      return;
    }
    el('draftExtraChoices').innerHTML = items.map(item => {
      const known = inherited.has(item.artifact_uid);
      const checked = (preserve ? keep.has(item.artifact_uid)
                                : selected.includes(item.artifact_uid)) ? ' checked' : '';
      const disabled = known ? ' disabled' : '';
      const note = known ? '（已随当前版本包含）' : '';
      return '<label><input type="checkbox" data-uid="' + esc(item.artifact_uid) + '"' +
        checked + disabled + '> ' + esc(artifactLabel(item)) + esc(note) + '</label>';
    }).join('');
  }

  async function loadExtraChoices() {
    const loadId = ++extrasLoadSeq;
    try {
      const [research, adaptation] = await Promise.all([
        request('/api/ops/research/list?kind=research', null),
        request('/api/ops/research/list?kind=adaptation', null)]);
      if (loadId !== extrasLoadSeq) return;
      extraArtifacts = [...research, ...adaptation].filter(item => item.analyzed);
      const currentVersion = versions.find(version => version.version === selectedVersion) || {};
      renderExtraChoices(((currentVersion.context_json || {}).draft_optimization) || {}, true);
    } catch (error) {
      if (loadId !== extrasLoadSeq) return;
      const container = el('draftExtraChoices');
      if (!container.innerHTML || container.innerHTML.indexOf('读取中') >= 0) {
        container.innerHTML = '<p class="script-hint">参考与咨询记录读取失败：' + esc(error.message) + '</p>';
      }
    }
    updateWorkbench();
  }

  function applyOptimization(version) {
    const meta = ((version || {}).context_json || {}).draft_optimization || {};
    const targets = Array.isArray(meta.targets) ? meta.targets : [];
    document.querySelectorAll('[data-opt-target]').forEach(box => {
      box.checked = targets.includes(box.dataset.optTarget);
    });
    el('draftInstruction').value = meta.instruction || '';
    el('draftMaxChars').value = (meta.max_body_chars === null || meta.max_body_chars === undefined)
      ? '' : String(meta.max_body_chars);
    renderExtraChoices(meta);
    el('draftOptimizeBase').textContent = selectedVersion
      ? ('基于哪一版修改：v' + selectedVersion +
         (targets.length ? ' · 优化目标：' + (meta.target_labels || []).join('、') : ''))
      : '基于哪一版修改：未选择';
    optimizeBaseline = optimizeKey();
  }

  function renderChanges(content) {
    const changes = Array.isArray((content || {}).changes) ? content.changes : [];
    el('draftChanges').hidden = !changes.length;
    el('draftChangeList').innerHTML = changes.map(item =>
      '<li><strong>' + esc(item.text || '') + '</strong>' +
      '<div class="script-hint">为什么：' + esc(item.why || '') +
      '；依据：' + esc((item.basis || []).join('、') || '无') +
      '；条件：' + esc((item.conditions || []).join('；') || '无') +
      '；缺口：' + esc((item.gaps || []).join('；') || '无') +
      '；下一步：' + esc(item.next_step || '未提供') + '</div></li>').join('');
  }

  function renderResearchSource(context) {
    const box = el('draftResearchSource');
    const source = (context || {}).research_source;
    if (!source || (source.kind !== 'topics' && source.kind !== 'adaptation')) {
      box.hidden = true;
      el('draftSourceChain').innerHTML = '';
      el('draftSourceMeta').textContent = '';
      el('draftSourceCandidate').textContent = '';
      el('draftSourceNote').textContent = '';
      return;
    }
    box.hidden = false;
    if (source.kind === 'adaptation') {
      el('draftSourceHeading').textContent = '参考适配计划（M05-C，推断不是事实）';
      el('draftSourceMeta').textContent = 'C 记录：' + (source.artifact_uid || '') +
        ' · 父 B 记录：' + (source.parent_uid || '无') +
        ' · 候选 id：' + (source.candidate_id || '无') +
        ' · 来源：' + (source.source === 'llm' ? '真实模型' : source.source === 'demo' ? '演示' : '人工保存') +
        ' · 策略：v' + (((source.strategy || {}).version) || 0) +
        (((source.strategy || {}).confirmed) ? ' 已确认' : ' 未确认');
      const subject = source.subject || {};
      el('draftSourceCandidate').textContent = '目标主题：' + (source.topic || '') +
        '；摘要：' + (source.summary || '') +
        '；本次说明/限制（用户输入，未独立核实）：' +
        (source.instruction || '未填写');
      const chain = el('draftSourceChain');
      chain.innerHTML = '';
      const aspect = {hook: '开头', structure: '结构', proof: '证明方式', pacing: '节奏', cta: '承接'};
      (source.patterns || []).forEach(item => {
        const wrap = document.createElement('div');
        wrap.className = 'draft-source-row';
        const head = document.createElement('p');
        const strong = document.createElement('strong');
        strong.textContent = (item.id || '') + ' [' + (aspect[item.aspect] || item.aspect || '计划') + '] ';
        head.appendChild(strong);
        head.appendChild(document.createTextNode(item.text || ''));
        wrap.appendChild(head);
        const why = document.createElement('p');
        why.className = 'script-hint';
        why.textContent = '为什么/边界：' + (item.why || '') +
          '；依据：' + ((item.basis || []).join('、') || '无') +
          '；本业务依据：' + ((item.business_basis || []).join('、') || '无（本业务证明未提供）') +
          '；条件：' + ((item.conditions || []).join('；') || '无') +
          '；缺口：' + ((item.gaps || []).join('；') || '无') +
          '；下一步：' + (item.next_step || '未提供');
        wrap.appendChild(why);
        if (item.reference_excerpt) {
          const excerpt = document.createElement('p');
          excerpt.className = 'script-hint';
          excerpt.textContent = '参考短摘录：' + item.reference_excerpt;
          wrap.appendChild(excerpt);
        }
        chain.appendChild(wrap);
      });
      (source.non_transferable || []).forEach(item => {
        const wrap = document.createElement('div');
        wrap.className = 'draft-source-row';
        const head = document.createElement('p');
        const strong = document.createElement('strong');
        strong.textContent = (item.id || '') + ' [不能照搬] ';
        head.appendChild(strong);
        head.appendChild(document.createTextNode(item.text || ''));
        wrap.appendChild(head);
        const why = document.createElement('p');
        why.className = 'script-hint';
        why.textContent = '原因：' + (item.why || '') +
          '；依据：' + ((item.basis || []).join('、') || '无') +
          '；下一步：' + (item.next_step || '未提供');
        wrap.appendChild(why);
        chain.appendChild(wrap);
      });
      if ((source.cannot_judge || []).length) {
        const cannot = document.createElement('p');
        cannot.className = 'script-hint';
        cannot.textContent = '仍不能判断：' + source.cannot_judge.join('；');
        chain.appendChild(cannot);
      }
      (source.refs || []).forEach(ref => {
        const wrap = document.createElement('div');
        wrap.className = 'draft-source-row';
        const head = document.createElement('p');
        const strong = document.createElement('strong');
        strong.textContent = (ref.id || '') + ' [' + (ref.role || '来源') + '] ';
        head.appendChild(strong);
        head.appendChild(document.createTextNode('出处：' + (ref.source || '未提供')));
        wrap.appendChild(head);
        const text = document.createElement('p');
        text.className = 'draft-source-text';
        text.textContent = ref.text || '';
        wrap.appendChild(text);
        chain.appendChild(wrap);
      });
      el('draftSourceNote').textContent = (source.note || '来自 M05-C 的参考适配计划，推断不是事实；本稿尚未生成。') +
        ' 计划不是完整正文，本页不会自动生成，需你显式点击生成。';
      return;
    }
    el('draftSourceHeading').textContent = '研究建议来源（M05-B，非事实）';
    el('draftSourceMeta').textContent = 'B 记录：' + (source.artifact_uid || '') +
      ' · 父 A 记录：' + (source.parent_uid || '') + ' · 候选 id：' + (source.candidate_id || '') +
      ' · 研究状态：' + (source.state === 'research_candidate' ? '研究候选（未验证）' : '待验证') +
      ' · 来源：' + (source.source === 'llm' ? '真实模型' : source.source === 'demo' ? '演示' : '人工保存');
    const candidate = source.candidate || {};
    el('draftSourceCandidate').textContent = '候选主题：' + (candidate.topic || source.topic || '') +
      '；受众问题：' + (candidate.audience_problem || '') +
      (candidate.gaps && candidate.gaps.length ? '；缺口：' + candidate.gaps.join('；') : '');
    const chain = el('draftSourceChain');
    chain.innerHTML = '';
    (source.basis_chain || []).forEach(row => {
      const wrap = document.createElement('div');
      wrap.className = 'draft-source-row';
      const head = document.createElement('p');
      const strong = document.createElement('strong');
      strong.textContent = row.source_id + ' [' + (row.label || row.role || '来源') + '] ';
      head.appendChild(strong);
      head.appendChild(document.createTextNode('出处：' + (row.source || '未提供') +
        '；真实身份：' + JSON.stringify(row.origin || {})));
      wrap.appendChild(head);
      const text = document.createElement('p');
      text.className = 'draft-source-text';
      text.textContent = row.text || '';
      wrap.appendChild(text);
      if (row.declaration) {
        const note = document.createElement('p');
        note.className = 'script-hint';
        note.textContent = '人工声明需求角色：' + (row.declaration.role || '') + '（人工声明，未独立核实）';
        wrap.appendChild(note);
      }
      chain.appendChild(wrap);
    });
    el('draftSourceNote').textContent = (source.note || '来自 M05-B 的候选，非事实；本稿尚未生成。') +
      ' 本页不会自动生成，需你显式点击生成。';
  }

  function renderVersion(version, restore) {
    const content = (version || {}).content_json || {};
    const context = (version || {}).context_json || {};
    const meta = context.draft_optimization || {};
    selectedVersion = (version || {}).version || 0;
    if (restore && selectedVersion) el('draftOperation').value = 'optimize';
    el('draftEmptyState').hidden = true;
    el('draftContent').hidden = false;
    el('draftVersionLabel').textContent = 'v' + ((version || {}).version || 0) + ' · ' +
      sourceLabel((version || {}).source) + ((version || {}).model ? ' · ' + version.model : '') +
      ((version || {}).base_version ? '（基于 v' + version.base_version + '）' : '') +
      ((meta.target_labels && meta.target_labels.length)
        ? ' · 优化：' + meta.target_labels.join('、') : '') +
      ((version || {}).instruction ? ' · 说明：' + version.instruction : '');
    el('draftVersionInput').textContent = '该版本输入：主题「' + ((version || {}).topic || '未记录') +
      '」 · 业务「' + (((version || {}).status_json || {}).business || '未填写') + '」' +
      ((version || {}).legacy_snapshot ? '（旧记录：资料回退到稿件级）' : '') +
      (meta.max_body_chars ? ' · 正文硬上限 ' + meta.max_body_chars + ' 码点' : '') +
      (meta.body_chars ? ' · 实际 ' + meta.body_chars + ' 码点' : '');
    el('draftTitle').textContent = content.title || '';
    el('draftSummary').textContent = content.summary || '';
    el('draftFacts').innerHTML = (content.facts || []).map(item =>
      '<li>' + esc(item.text) + ' <small>' + esc('依据：' + ((item.basis || []).join('、') || '无') +
        (item.unverified ? '，待验证' : '')) + '</small></li>').join('') || '<li class="script-hint">（无）</li>';
    el('draftOutline').innerHTML = (content.outline || []).map(item => '<li>' + esc(item) + '</li>').join('')
      || '<li class="script-hint">（无）</li>';
    el('draftMarkdown').textContent = content.draft_markdown || '';
    el('draftGaps').innerHTML = (content.gaps || []).map(item => '<li>' + esc(item) + '</li>').join('')
      || '<li class="script-hint">（无）</li>';
    el('draftQuestions').innerHTML = (content.questions || []).map(item => '<li>' + esc(item) + '</li>').join('')
      || '<li class="script-hint">（无）</li>';
    renderChanges(content);
    el('draftExport').href = '/api/ops/draft/export?id=' + encodeURIComponent(current.draft_uid) +
      '&version=' + encodeURIComponent(selectedVersion);
    renderResearchSource((version || {}).context_json);
    fillIndustryFrozen(version);
    if (restore) {
      fillIndustrySelect('draftIndustry', '', false);
      fillIndustrySelect('draftOptimizeIndustry', '', true);
      fillWorkbenchIndustry('');
      el('draftIndustrySummary').textContent = '当前版本冻结模板：' + industryLabel(context) +
        '；重新生成时缺省沿用它，显式选择只影响新记录。';
      applyOptimization(version);
      el('draftTopic').value = (version || {}).topic || '';
      fill((version || {}).status_json || {});
      setSelections(((version || {}).context_json || {}).refs);
      ensureDefaultTargets();
      resetBaseline();
      newTopicNote();
      updateWorkbench();
    } else {
      el('draftOptimizeBase').textContent = '基于哪一版修改：v' + selectedVersion;
      ensureDefaultTargets();
      updateWorkbench();
    }
    updateSourceBar(version);
    renderVersionList();
  }
  function renderVersionList() {
    el('draftVersionList').innerHTML = versions.length ? versions.map(version => {
      const meta = ((version.context_json || {}).draft_optimization) || {};
      const label = 'v' + version.version +
        (version.base_version ? '（基于 v' + version.base_version + '）' : '') +
        ' · ' + sourceLabel(version.source) +
        ((meta.target_labels && meta.target_labels.length)
          ? ' · ' + meta.target_labels.join('、') : '');
      const title = label + (version.instruction ? ' · ' + version.instruction : '');
      return '<button class="draft-version-item' + (version.version === selectedVersion ? ' active' : '') +
        '" data-version="' + version.version + '" title="' + esc(title) + '">' +
        '<span class="draft-version-title">' + esc(label) + '</span>' +
        '<small>' + new Date((version.created_at || 0) * 1000).toLocaleString('zh-CN') + '</small></button>';
    }).join('')
      : '<p class="script-hint">还没有版本。</p>';
    el('draftVersionList').querySelectorAll('[data-version]').forEach(button => {
      button.onclick = () => {
        if (dirty() && !confirm('当前表单有未保存修改，切换版本会覆盖；继续？')) return;
        const hit = versions.find(version => String(version.version) === button.dataset.version);
        if (!hit) return;
        pageSeq += 1;
        renderVersion(hit, true);
      };
    });
  }
  function render(draft, options) {
    current = draft;
    versions = draft.versions || [];
    renderResearchSource((draft || {}).context_json);
    if (!options || options.fillForm !== false) {
      el('draftTopic').value = draft.topic || '';
      fill(draft.status_json || {});
      setSelections((draft.context_json || {}).refs);
      resetBaseline();
    }
    const currentVersion = draft.current_version;
    if (currentVersion) {
      if (options && options.fillForm === false && el('draftOperation').value === 'generate') {
        el('draftOperation').value = 'optimize';
      }
      renderVersion(currentVersion, !(options && options.fillForm === false));
    }
    else {
      selectedVersion = 0;
      el('draftOperation').value = 'generate';
      el('draftContent').hidden = true;
      el('draftEmptyState').hidden = false;
      el('draftVersionLabel').textContent = '已打开（未生成）';
      el('draftVersionInput').textContent = '';
      el('draftExport').href = '#';
      el('draftOptimizeBase').textContent = '基于哪一版修改：未选择';
      optimizeBaseline = optimizeKey();
      renderVersionList();
      updateWorkbench();
    }
    updateSourceBar();
    newTopicNote();
  }

  async function openDraft(uid) {
    if (dirty() && !confirm('当前研究稿有未保存修改。打开历史会覆盖这些输入，是否继续？')) return;
    const snapshot = collect();
    const optimizeSnapshot = optimizeKey();
    const seq = ++pageSeq;
    try {
      const data = await request('/api/ops/draft?id=' + encodeURIComponent(uid), null);
      if (seq !== pageSeq) return;
      if ((!sameForm(collect(), snapshot) || optimizeKey() !== optimizeSnapshot) &&
          !confirm('等待期间又有新的修改。打开历史会覆盖这些输入，是否继续？')) return;
      render(data, {fillForm: true});
      el('draftStatus').textContent = '已打开 ' + uid + '；可从版本列表切换与导出';
    } catch (error) {
      if (seq === pageSeq) el('draftError').textContent = error.message;
    }
  }

  async function loadChoices() {
    try {
      const pains = await request('/api/pain/list', null);
      el('draftPainChoices').innerHTML = pains.length ? pains.map(item =>
        '<label><input type="checkbox" data-pain-id="' + Number(item.id) + '"> ' +
        esc(String(item.pain || '').slice(0, 40)) + '</label>').join('') : '<p class="script-hint">暂无痛点</p>';
    } catch (error) { el('draftPainChoices').innerHTML = '<p class="script-hint">痛点读取失败</p>'; }
    try {
      const refs = await request('/api/reference/list', null);
      el('draftReferenceChoices').innerHTML = refs.length ? refs.map(item =>
        '<label><input type="checkbox" data-ref-id="' + Number(item.id) + '"> ' +
        esc(String(item.title || '').slice(0, 40)) + '</label>').join('') : '<p class="script-hint">暂无参考</p>';
    } catch (error) { el('draftReferenceChoices').innerHTML = '<p class="script-hint">参考读取失败</p>'; }
  }

  async function loadList() {
    try {
      const list = await request('/api/ops/draft/list', null);
      el('draftList').innerHTML = list.length ? list.map(item =>
        '<button class="draft-version-item" data-open="' + esc(item.draft_uid) + '" title="' +
        esc(item.topic || '（无主题）') + '">' +
        '<span class="draft-version-title">' + esc(item.topic || '（无主题）') + '</span>' +
        '<small>v' + (item.version_count || 0) + ' · ' +
        new Date((item.updated_at || 0) * 1000).toLocaleString('zh-CN') + '</small></button>').join('')
        : '<p class="script-hint">还没有研究稿。</p>';
      el('draftList').querySelectorAll('[data-open]').forEach(button => {
        button.onclick = () => openDraft(button.dataset.open);
      });
    } catch (error) { el('draftList').innerHTML = '<p class="script-hint">读取失败：' + esc(error.message) + '</p>'; }
  }

  async function runWorkbench() {
    if (busy) return;
    const real = el('draftExecutionMode').value === 'real';
    if (real && !confirm('将发起一次真实模型调用，可能产生费用。取消不会发送请求。确认继续吗？')) return;
    if (el('draftOperation').value === 'optimize') await optimize(real);
    else await generate(real);
  }

  function useExample() {
    el('draftTopic').value = '【合成示例】旧家具修复报价怎么讲清楚';
    el('draftBusiness').value = '旧家具修复服务（合成示例，不是本机经营资料）';
    el('draftAudience').value = '正在考虑修复旧家具的家庭用户（合成示例）';
    el('draftGoal').value = '说明报价需要哪些信息，并引导用户补充照片与尺寸（合成示例）';
    el('draftResources').value = '示例素材：修复前后照片、常见材料说明；不代表实际持有资源';
    el('draftCapacity').value = '每周可投入 4 小时（合成示例）';
    el('draftInstruction').value = '';
    el('draftMaxChars').value = '';
    el('draftOperation').value = 'generate';
    el('draftExecutionMode').value = 'test';
    document.querySelectorAll('[data-opt-target]').forEach(box => { box.checked = false; });
    document.querySelectorAll('#draftExtraChoices [data-uid], #draftPainChoices [data-pain-id], #draftReferenceChoices [data-ref-id]')
      .forEach(box => { box.checked = false; });
    newTopicNote();
    updateWorkbench();
    el('draftTopic').focus();
    el('draftTopic').scrollIntoView({block: 'center', behavior: 'smooth'});
  }

  bindDisclosure('draftAdvancedToggle', 'draftAdvancedContent');
  bindDisclosure('draftHistoryToggle', 'draftHistoryContent');
  el('draftSave').onclick = saveDraft;
  el('draftRun').onclick = runWorkbench;
  el('draftUseExample').onclick = useExample;
  el('draftOperation').addEventListener('change', () => {
    if (el('draftOperation').value === 'optimize' && !document.querySelector('[data-opt-target]:checked')) {
      ensureDefaultTargets();
    }
    updateWorkbench();
  });
  el('draftExecutionMode').addEventListener('change', updateWorkbench);
  el('draftWorkbenchIndustry').addEventListener('change', () => {
    syncWorkbenchTemplate();
    el('draftError').textContent = '';
    updateWorkbench();
  });
  el('draftTopic').addEventListener('input', () => {
    if (current && el('draftTopic').value.trim() !== (current.topic || '')) {
      el('draftOperation').value = 'generate';
    }
    newTopicNote();
    updateWorkbench();
  });
  ['draftTopic', 'draftBusiness', 'draftAudience', 'draftGoal', 'draftResources', 'draftCapacity']
    .forEach(id => el(id).addEventListener('input', () => {
      el('draftError').textContent = '';
      updateWorkbench();
    }));
  ['draftInstruction', 'draftMaxChars'].forEach(id => el(id).addEventListener('input', () => {
    el('draftError').textContent = '';
    el('draftOptimizeStatus').textContent = '';
    updateWorkbench();
  }));
  document.addEventListener('change', event => {
    if (event.target && event.target.closest &&
        (event.target.closest('#draftPainChoices') || event.target.closest('#draftReferenceChoices') ||
         event.target.closest('[data-opt-target]') || event.target.closest('#draftExtraChoices'))) {
      el('draftError').textContent = '';
      el('draftOptimizeStatus').textContent = '';
      if (event.target.matches('#draftExtraChoices [data-uid]:checked') &&
          document.querySelectorAll('#draftExtraChoices [data-uid]:checked').length > 12) {
        event.target.checked = false;
        el('draftOptimizeStatus').textContent = '最多选择 12 条参考与咨询记录，刚才的选择未添加。';
      }
      updateWorkbench();
    }
  });
  document.addEventListener('click', event => {
    const button = event.target.closest('[data-remove-kind]');
    if (!button) return;
    const selectors = {
      pain: '#draftPainChoices [data-pain-id]',
      reference: '#draftReferenceChoices [data-ref-id]',
      extra: '#draftExtraChoices [data-uid]'
    };
    const selector = selectors[button.dataset.removeKind];
    if (!selector) return;
    const input = [...document.querySelectorAll(selector)]
      .find(box => (box.dataset.painId || box.dataset.refId || box.dataset.uid) === button.dataset.removeId);
    if (!input || input.disabled) return;
    input.checked = false;
    updateWorkbench();
  });
  baseline = collect();
  optimizeBaseline = optimizeKey();
  fillIndustrySelect('draftIndustry', '', false);
  fillIndustrySelect('draftOptimizeIndustry', '', true);
  fillWorkbenchIndustry('');
  ['draftIndustry', 'draftOptimizeIndustry'].forEach(id => {
    el(id).addEventListener('change', () => { el('draftError').textContent = ''; });
  });
  loadIndustryCatalog();
  loadChoices().then(() => {
    loadExtraChoices();
    if (typeof location === 'undefined') return;
    const uid = new URLSearchParams(location.search).get('id');
    if (uid && /^[a-f0-9]{12}$/.test(uid)) openDraft(uid);
  });
  loadList();
  updateWorkbench();
})();
