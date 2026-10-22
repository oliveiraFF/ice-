(() => {
  const el = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const REQUEST_BYTES = 65536;
  let token = '', current = null, currentActions = [], currentStatus = null, busy = false, pending = false;
  let followupCancelled = false, openedSuggestions = [];
  let pageSeq = 0;
  function nextPage() {
    const seq = ++pageSeq;
    busy = false;
    pending = false;
    setBusy(false);
    el('saveStatus').disabled = false;
    return seq;
  }
  const emptySelection = () => ({pain_ids: '', reference_ids: '', suggestion_ids: ''});
  let baseline = {business: {business: '', audience: '', goal: '', resources: '', capacity: '', question: ''},
                  selection: emptySelection()};

  const initial = fetch('/api/state?mode=live').then(async r => {
    if (!r.ok) throw new Error('本机连接失败，请重新打开页面');
    token = (await r.json()).token;
  });
  initial.catch(error => { el('adviceError').textContent = error.message; });

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

  function checkBytes(payload) {
    const size = new TextEncoder().encode(JSON.stringify(payload)).byteLength;
    return size > REQUEST_BYTES ? '本次请求约 ' + size + ' 字节，超过 65536 字节上限，请精简输入' : '';
  }

  function collect() {
    return {
      business: el('adviceBusiness').value.trim(),
      audience: el('adviceAudience').value.trim(),
      goal: el('adviceGoal').value.trim(),
      resources: el('adviceResources').value.trim(),
      capacity: el('adviceCapacity').value.trim(),
      question: el('adviceQuestion').value.trim(),
    };
  }
  function businessForm(source) {
    const data = source || {};
    return {business: data.business || '', audience: data.audience || '', goal: data.goal || '',
            resources: data.resources || '', capacity: data.capacity || '', question: data.question || ''};
  }
  function sameForm(left, right) {
    return Object.keys(left).every(key => (left[key] || '') === (right[key] || ''));
  }
  function normalizeIds(values, numeric) {
    return (values || []).map(value => numeric ? Number(value) : String(value))
      .sort((a, b) => numeric ? a - b : String(a).localeCompare(String(b))).join(',');
  }
  function selectionForm(source) {
    const data = source || {};
    return {pain_ids: normalizeIds(data.pain_ids, true),
            reference_ids: normalizeIds(data.reference_ids, true),
            suggestion_ids: normalizeIds(data.suggestion_ids, false)};
  }
  function snapshot() {
    return {business: collect(), selection: selectionForm(selected())};
  }
  function snapshotEqual(left, right) {
    return !!left && !!right && sameForm(left.business, right.business) &&
      sameForm(left.selection, right.selection);
  }
  function dirty() {
    return !snapshotEqual(snapshot(), baseline);
  }
  function setBaseline(business, selection) {
    baseline = {business: businessForm(business), selection: selectionForm(selection)};
  }
  function fill(status) {
    el('adviceBusiness').value = (status || {}).business || '';
    el('adviceAudience').value = (status || {}).audience || '';
    el('adviceGoal').value = (status || {}).goal || '';
    el('adviceResources').value = (status || {}).resources || '';
    el('adviceCapacity').value = (status || {}).capacity || '';
    el('adviceQuestion').value = (status || {}).question || '';
  }
  function adviceSelection(advice) {
    const refs = ((advice || {}).context_json || {}).refs || [];
    const pick = kind => refs.filter(ref => String(ref.id || '').startsWith(kind + ':'))
      .map(ref => String(ref.id).slice(kind.length + 1));
    return {pain_ids: pick('pain'), reference_ids: pick('ref'), suggestion_ids: pick('suggestion')};
  }
  function staleNote() {
    if (!current || !currentStatus) {
      el('adviceStale').hidden = true;
      return;
    }
    const differs = !sameForm(businessForm(collect()), businessForm(currentStatus)) ||
      !sameForm(selectionForm(selected()), selectionForm(adviceSelection(current)));
    el('adviceStale').hidden = !differs;
    el('adviceStale').textContent = differs
      ? '当前输入（含痛点/参考/复盘来源选择）已改动：下面这条建议基于旧输入，未重新分析。' : '';
  }
  function setBusy(value, text) {
    busy = value;
    ['analyzeDemo', 'analyzeReal', 'askDemo', 'askReal', 'saveStatus'].forEach(id => { el(id).disabled = value; });
    if (text) el('adviceStatus').textContent = text;
  }
  function modeFields(real) {
    return {model_mode: real ? 'real' : 'test', confirm: real === true};
  }
  function consumeConfirm(real) {
    if (!real) return;
    if (!el('realConfirm').checked) throw new Error('真实调用需勾选本次确认');
    el('realConfirm').checked = false;
  }
  function urlFollowupIds() {
    if (followupCancelled) return [];
    return (new URLSearchParams(location.search).get('followup') || '')
      .split(',').map(item => item.trim()).filter(Boolean).slice(0, 3);
  }
  function followupIds() {
    const fromUrl = urlFollowupIds();
    return (fromUrl.length ? fromUrl : openedSuggestions).slice(0, 3);
  }
  function syncFollowupCard() {
    const ids = followupIds();
    el('adviceFollowup').hidden = !ids.length;
    if (!ids.length) { el('adviceFollowupText').textContent = ''; return; }
    loadFollowup();
  }
  async function loadFollowup() {
    const ids = followupIds();
    if (!ids.length) { el('adviceFollowup').hidden = true; return; }
    el('adviceFollowup').hidden = false;
    const lines = [];
    for (const id of ids) {
      try {
        const item = await request('/api/feedback/suggestion?id=' + encodeURIComponent(id), null);
        lines.push('作品 ' + (item.record_uid || '') + ' · 复盘 ' + (item.review_uid || '') + ' · 建议：' +
                   ((item.suggestion || {}).text || ''));
      } catch (error) {
        lines.push(id + '（无法读取：' + error.message + '）');
      }
    }
    el('adviceFollowupText').textContent = lines.join('；');
  }
  function selected() {
    const pain_ids = [...document.querySelectorAll('#painChoices [data-pain-id]:checked')].map(box => Number(box.dataset.painId));
    const reference_ids = [...document.querySelectorAll('#referenceChoices [data-ref-id]:checked')].map(box => Number(box.dataset.refId));
    return {pain_ids: pain_ids, reference_ids: reference_ids, suggestion_ids: followupIds()};
  }
  function restoreSelection(advice) {
    const refs = ((advice || {}).context_json || {}).refs || [];
    const pains = new Set(refs.filter(ref => String(ref.id || '').startsWith('pain:'))
      .map(ref => String(ref.id).slice(5)));
    const refIds = new Set(refs.filter(ref => String(ref.id || '').startsWith('ref:'))
      .map(ref => String(ref.id).slice(4)));
    document.querySelectorAll('#painChoices [data-pain-id]').forEach(box => {
      box.checked = pains.has(String(box.dataset.painId));
    });
    document.querySelectorAll('#referenceChoices [data-ref-id]').forEach(box => {
      box.checked = refIds.has(String(box.dataset.refId));
    });
  }

  async function saveStatus() {
    if (busy || pending) return;
    el('adviceError').textContent = '';
    const seq = nextPage();
    const submit = collect();
    const payload = {status: submit};
    const tooLarge = checkBytes(payload);
    if (tooLarge) { el('adviceError').textContent = tooLarge; return; }
    pending = true;
    el('saveStatus').disabled = true;
    try {
      const data = await request('/api/ops/advice/save', payload);
      if (seq !== pageSeq) { loadHistory(); return; }
      baseline = {business: businessForm(submit), selection: baseline.selection};
      el('adviceStatus').textContent = '已保存现状 ' + data.advice.advice_uid + '（未分析；来源选择不随现状保存）';
      loadHistory();
    } catch (error) { if (seq === pageSeq) el('adviceError').textContent = error.message; }
    finally { if (seq === pageSeq) { pending = false; el('saveStatus').disabled = false; } }
  }

  async function analyze(real) {
    if (busy || pending) return;
    el('adviceError').textContent = '';
    const seq = nextPage();
    try {
      const submitted = collect();
      const payload = {status: submitted, selected: selected()};
      Object.assign(payload, modeFields(real));
      const tooLarge = checkBytes(payload);
      if (tooLarge) { el('adviceError').textContent = tooLarge; return; }
      consumeConfirm(real);
      pending = true;
      setBusy(true, '分析中…');
      const data = await request('/api/ops/advice/analyze', payload);
      if (seq !== pageSeq) { loadHistory(); return; }
      const unchanged = sameForm(submitted, collect());
      if (unchanged) fill(data.advice.status_json);
      render(data.advice, false);
      setBaseline(data.advice.status_json || submitted, adviceSelection(data.advice));
      staleNote();
      el('adviceStatus').textContent = '分析完成';
      loadHistory();
    } catch (error) { if (seq === pageSeq) { el('adviceStatus').textContent = ''; el('adviceError').textContent = error.message; } }
    finally { if (seq === pageSeq) { pending = false; setBusy(false); } }
  }

  async function ask(real) {
    if (busy || pending) return;
    if (!current) { el('askStatus').textContent = '请先打开一条建议'; return; }
    const question = el('followQuestion').value.trim();
    if (!question) { el('askStatus').textContent = '请填写追问'; return; }
    const target = current.advice_uid;
    const seq = nextPage();
    try {
      const payload = {advice_uid: target, question};
      Object.assign(payload, modeFields(real));
      const tooLarge = checkBytes(payload);
      if (tooLarge) { el('adviceError').textContent = tooLarge; return; }
      consumeConfirm(real);
      pending = true;
      setBusy(true);
      el('askStatus').textContent = '追问中…';
      const data = await request('/api/ops/advice/ask', payload);
      if (seq !== pageSeq || !current || current.advice_uid !== target) { loadHistory(); return; }
      render(data.advice, false);
      el('followQuestion').value = '';
      el('askStatus').textContent = '追问完成；原建议保留';
      loadHistory();
    } catch (error) { if (seq === pageSeq) { el('askStatus').textContent = ''; el('adviceError').textContent = error.message; } }
    finally { if (seq === pageSeq) { pending = false; setBusy(false); } }
  }

  async function updateAction(index, status) {
    if (pending) return;
    const action = currentActions[index];
    if (!action || !current) return;
    const state = (current.actions || []).find(row => row.action_id === action.id) || {version: 0};
    const note = (document.querySelector('[data-note="' + index + '"]') || {}).value || '';
    const target = current.advice_uid;
    const seq = nextPage();
    pending = true;
    try {
      const data = await request('/api/ops/advice/action', {
        advice_uid: target, action_id: action.id, status: status,
        note: note, expected_version: state.version,
      });
      if (seq !== pageSeq || !current || current.advice_uid !== target) { loadHistory(); return; }
      render(data.advice, false);
      loadHistory();
    } catch (error) {
      if (seq === pageSeq) el('adviceError').textContent = error.message + '（服务端未保存；你的状态选择/备注仍保留在表单）';
    } finally { if (seq === pageSeq) pending = false; }
  }

  function refText(id) {
    const refs = ((current || {}).context_json || {}).refs || [];
    const hit = refs.find(ref => ref.id === id);
    return hit ? (hit.text || '').slice(0, 60) : id;
  }

  function render(advice, resetForm) {
    current = advice;
    currentStatus = advice.status_json || null;
    currentActions = (((advice || {}).result_json || {}).week_actions) || [];
    if (resetForm && currentStatus) fill(currentStatus);
    if (resetForm) el('adviceStale').hidden = true;
    const result = advice.result_json || {};
    el('adviceResult').hidden = false;
    el('adviceSource').textContent = (advice.source || 'demo') + (advice.model ? ' · ' + advice.model : '');
    el('adviceModeBadge').textContent = advice.source === 'llm' ? '真实模型' : (advice.draft ? '未分析' : '演示');
    el('adviceCurrent').textContent = '建议 ID ' + advice.advice_uid + ' · ' +
      new Date((advice.created_at || 0) * 1000).toLocaleString('zh-CN') +
      (advice.question ? ' · 追问：' + advice.question : '');
    el('adviceCanJudge').innerHTML = (result.can_judge || []).map(t => '<li>' + esc(t) + '</li>').join('') || '<li class="script-hint">（无）</li>';
    el('adviceCannotJudge').innerHTML = (result.cannot_judge || []).map(t => '<li>' + esc(t) + '</li>').join('') || '<li class="script-hint">（无）</li>';
    el('advicePriorities').innerHTML = (result.priorities || []).map(p =>
      '<p>' + esc(p.text) + ' <small>' + esc((p.basis || []).map(refText).join('；')) +
      (p.confidence ? ' · ' + esc(p.confidence) : '') + '</small>' +
      (p.unverified ? '<br><small class="advice-warn">无有效依据，待验证</small>' : '') + '</p>').join('') || '<p class="script-hint">（无）</p>';
    el('adviceDirections').innerHTML = (result.directions || []).map(d =>
      '<p>' + esc(d.text) + '<br><small>理由：' + esc(d.why || '未填') + ' · 条件：' + esc(d.conditions || '未填') +
      ' · 依据：' + esc((d.basis || []).map(refText).join('；') || '无') + '</small>' +
      (d.unverified ? '<br><small class="advice-warn">无有效依据，待验证</small>' : '') + '</p>').join('') || '<p class="script-hint">（无）</p>';
    const actionState = {};
    (advice.actions || []).forEach(row => { actionState[row.action_id] = row; });
    el('adviceActions').innerHTML = currentActions.map((a, index) => {
      const state = actionState[a.id] || {status: 'todo', version: 0, note: ''};
      return '<div class="advice-action" data-action-index="' + index + '"><p><strong>' + esc(a.action) + '</strong>' +
        (a.unverified ? ' <small class="advice-warn">无有效依据，待验证</small>' : '') +
        '<br><small>理由：' + esc(a.why || '未填') + ' · 证明：' + esc(a.proof || '未填') +
        ' · 条件：' + esc(a.conditions || '未填') + ' · 缺口：' + esc(a.gaps || '未填') +
        ' · 下一步：' + esc(a.next || '未填') + ' · 依据：' + esc((a.basis || []).map(refText).join('；') || '无') + '</small></p>' +
        '<label class="advice-note">备注<input data-note="' + index + '" maxlength="500" value="' + esc(state.note || '') + '"></label>' +
        '<div class="script-actions">' +
        ['todo', 'doing', 'done'].map(s => '<button class="secondary compact" data-act-index="' + index + '" data-status="' + s + '">' +
          ({todo: '待办', doing: '进行中', done: '完成'}[s]) + '</button>').join('') +
        '<span class="script-hint">当前：' + esc(state.status) + ' · v' + state.version + '</span></div></div>';
    }).join('') || '<p class="script-hint">（无）</p>';
    el('adviceActions').querySelectorAll('[data-act-index]').forEach(button => {
      button.onclick = () => updateAction(Number(button.dataset.actIndex), button.dataset.status);
    });
    el('adviceDecisions').innerHTML = (result.decisions || []).map(t => '<li>' + esc(t) + '</li>').join('') || '<li class="script-hint">（无）</li>';
    el('adviceContinue').innerHTML = (result.continue_without || []).map(t => '<li>' + esc(t) + '</li>').join('') || '<li class="script-hint">（无）</li>';
    staleNote();
  }

  async function openAdvice(uid) {
    if (dirty() && !confirm('当前表单有未保存修改（含痛点/参考/复盘来源选择），打开历史会覆盖；继续？')) return;
    const before = snapshot();
    const seq = nextPage();
    try {
      const data = await request('/api/ops/advice?id=' + encodeURIComponent(uid), null);
      if (seq !== pageSeq) return;
      if (!snapshotEqual(snapshot(), before) &&
          !confirm('等待期间有新的编辑，打开历史会覆盖；继续？')) return;
      followupCancelled = true;
      openedSuggestions = data.draft ? [] : adviceSelection(data).suggestion_ids;
      restoreSelection(data);
      syncFollowupCard();
      fill(data.status_json);
      if (data.draft) {
        current = data;
        currentStatus = data.status_json || null;
        currentActions = [];
        el('adviceResult').hidden = true;
        setBaseline(data.status_json, selectionForm(selected()));
        el('adviceStale').hidden = true;
        el('adviceStatus').textContent = '已恢复草稿（未分析）';
        return;
      }
      render(data, false);
      setBaseline(data.status_json, adviceSelection(data));
      staleNote();
      el('adviceStatus').textContent = '已打开历史建议';
    } catch (error) { if (seq === pageSeq) el('adviceError').textContent = error.message; }
  }

  async function loadChoices() {
    try {
      const pains = await request('/api/pain/list', null);
      el('painChoices').innerHTML = pains.length ? pains.map(item =>
        '<label><input type="checkbox" data-pain-id="' + Number(item.id) + '"> ' +
        esc(String(item.pain || '').slice(0, 40)) + ' <small>' + esc(item.evidence_role || '') + '</small></label>').join('')
        : '<p class="script-hint">暂无痛点</p>';
    } catch (error) { el('painChoices').innerHTML = '<p class="script-hint">痛点读取失败</p>'; }
    try {
      const refs = await request('/api/reference/list', null);
      el('referenceChoices').innerHTML = refs.length ? refs.map(item =>
        '<label><input type="checkbox" data-ref-id="' + Number(item.id) + '"> ' +
        esc(String(item.title || '').slice(0, 40)) + '</label>').join('')
        : '<p class="script-hint">暂无参考</p>';
    } catch (error) { el('referenceChoices').innerHTML = '<p class="script-hint">参考读取失败</p>'; }
  }

  async function loadHistory() {
    try {
      const list = await request('/api/ops/advice/list', null);
      el('adviceHistory').innerHTML = list.length ? list.map(item =>
        '<button class="advice-history-item" data-open="' + esc(item.advice_uid) + '" data-draft="' + (item.draft ? '1' : '0') + '">' +
        esc((item.result_json && item.result_json.priorities && item.result_json.priorities[0] &&
          item.result_json.priorities[0].text) || (item.draft ? '未分析：' + (item.status_json.business || '业务现状') : '（建议）')) +
        ' <small>' + (item.draft ? '草稿' : esc(item.source)) + ' · ' +
        new Date((item.created_at || 0) * 1000).toLocaleString('zh-CN') + '</small></button>').join('')
        : '<p class="script-hint">还没有保存的分析。</p>';
      el('adviceHistory').querySelectorAll('[data-open]').forEach(button => {
        button.onclick = () => openAdvice(button.dataset.open);
      });
    } catch (error) {
      el('adviceHistory').innerHTML = '<p class="script-hint">历史读取失败：' + esc(error.message) + '</p>';
    }
  }

  if (followupIds().length) {
    el('adviceStatus').textContent = '已选择复盘建议来源；点击下方“取消该来源”可移除';
  }
  el('adviceFollowupClear').onclick = () => {
    followupCancelled = true;
    openedSuggestions = [];
    el('adviceFollowup').hidden = true;
    el('adviceStatus').textContent = '已取消复盘建议来源（不影响已有建议）';
    staleNote();
  };
  syncFollowupCard();
  ['adviceBusiness', 'adviceAudience', 'adviceGoal', 'adviceResources', 'adviceCapacity', 'adviceQuestion'].forEach(id => {
    el(id).addEventListener('input', staleNote);
  });
  el('painChoices').addEventListener('change', staleNote);
  el('referenceChoices').addEventListener('change', staleNote);
  el('saveStatus').onclick = saveStatus;
  el('analyzeDemo').onclick = () => analyze(false);
  el('analyzeReal').onclick = () => analyze(true);
  el('askDemo').onclick = () => ask(false);
  el('askReal').onclick = () => ask(true);
  loadChoices().then(() => {
    if (typeof location === 'undefined') return;
    const uid = new URLSearchParams(location.search).get('id');
    if (uid && /^[a-f0-9]{12}$/.test(uid)) openAdvice(uid);
  });
  loadHistory();
})();
