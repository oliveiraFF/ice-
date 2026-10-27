(() => {
  const el = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  let token = '', pendingSnapshotKey = '';
  const initial = fetch('/api/state?mode=live').then(async r => {
    if (!r.ok) throw new Error('本机连接失败，请重新打开页面');
    token = (await r.json()).token;
  });
  initial.catch(error => { el('recordError').textContent = error.message; });

  async function post(path, body) {
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

  function localIso(value) { return value ? new Date(value).toISOString() : ''; }

  el('registerRecord').onclick = async () => {
    el('recordError').textContent = '';
    try {
      const data = await post('/api/feedback/register', {
        task_uid: el('recordTask').value.trim(),
        version: Number(el('recordVersion').value || 1),
        platform: el('recordPlatform').value,
        platform_post_id: el('recordPostId').value.trim(),
        url: el('recordUrl').value.trim(),
        published_at: localIso(el('recordPublishedAt').value),
      });
      await loadRecords();
      await openRecord(data.record_uid);
    } catch (error) { el('recordError').textContent = error.message; }
  };

  async function loadRecords() {
    try {
      const records = await getJson('/api/feedback/records');
      el('recordList').innerHTML = records.length ? records.map(r =>
        '<div class="script-task"><div><strong>' + esc(r.platform) + ' · ' + esc(r.platform_post_id) + '</strong>' +
        '<small>任务 ' + esc(r.task_uid) + ' · v' + r.version + ' · ' + esc(r.published_at) + '</small></div>' +
        '<button class="secondary" data-open="' + esc(r.record_uid) + '">查看</button></div>').join('')
        : '<p class="script-hint">还没有登记。</p>';
      el('recordList').querySelectorAll('[data-open]').forEach(button => {
        button.onclick = () => openRecord(button.dataset.open);
      });
    } catch (error) {
      el('recordList').innerHTML = '<p class="script-hint">读取失败：' + esc(error.message) + '</p>';
    }
  }

  async function openRecord(uid, reviewUid, suggestionId) {
    const snapshots = await getJson('/api/feedback/snapshots?record=' + encodeURIComponent(uid));
    el('recordDetail').hidden = false;
    el('recordDetail').innerHTML = '<h4>登记 ' + esc(uid) + '</h4>' +
      '<p class="script-hint">快照（按采集时间）：' + (snapshots.length ? snapshots.map(s =>
        esc(s.collected_at) + ' · ' + esc(JSON.stringify(s.metrics)) + '（来源 ' + esc(s.source || '') +
        ' / 口径 ' + esc(s.definition || '') + '）').join('；') : '尚无数据') + '</p>' +
      '<h4>录入指标快照</h4>' +
      '<div class="metric-grid">' + ['plays', 'likes', 'comments', 'favorites', 'inquiries'].map(key =>
        '<label>' + ({plays:'播放',likes:'点赞',comments:'评论',favorites:'收藏',inquiries:'咨询'}[key]) +
        '<input data-metric="' + key + '" inputmode="numeric"></label>').join('') + '</div>' +
      '<label>采集时间（本地）<input id="snapCollected" type="datetime-local"></label>' +
      '<label>快照标识<input id="snapKey" placeholder="例如 2026-10-17-1"></label>' +
      '<div class="script-actions"><button class="secondary" id="saveSnapshot" type="button">保存快照</button>' +
      '<button class="secondary" id="buildReview" type="button">生成复盘</button></div>' +
      '<p id="snapshotStatus" class="script-hint" role="status"></p>' +
      '<div id="reviewPanel"></div>' +
      '<h4>咨询摘录（人工记录）</h4><div id="consultPanel"></div>';
    el('saveSnapshot').onclick = () => saveSnapshot(uid);
    el('buildReview').onclick = () => buildReview(uid);
    loadReviews(uid, reviewUid, suggestionId);
    loadConsultations(uid);
  }

  async function loadReviews(uid, reviewUid, suggestionId) {
    try {
      const reviews = await getJson('/api/feedback/reviews?record=' + encodeURIComponent(uid));
      if (!reviews.length) {
        el('reviewPanel').textContent = reviewUid ? '复盘不存在或不属于该作品' : '暂无复盘';
        return;
      }
      const target = reviewUid ? reviews.find(item => item.review_uid === reviewUid) : reviews[0];
      if (!target) {
        el('reviewPanel').textContent = '复盘不存在或不属于该作品';
        return;
      }
      const suggestions = target.suggestions_json || [];
      const chosen = suggestionId ? suggestions.find(item => item.id === suggestionId) : null;
      if (suggestionId && !chosen) {
        el('reviewPanel').textContent = '建议不存在或不属于该复盘';
        return;
      }
      el('reviewPanel').innerHTML = '<h4>已保存复盘 · ' + esc(target.review_uid) + '</h4>' +
        (target.observations_json || []).map(text => '<p>' + esc(text) + '</p>').join('') +
        suggestions.map(item => '<p' + (chosen && item.id === chosen.id ? ' class="is-selected"' : '') + '>' +
          esc(item.text) + '<br><small>依据：' + esc(item.basis) + ' · 条件：' + esc(item.conditions) +
          ' · 待验证：' + esc(item.pending) + '</small> ' +
          '<button class="secondary compact" data-use="' + esc(item.id) + '">用于下一任务</button>' +
          '<button class="secondary compact" data-follow="' + esc(item.id) + '">用于运营跟进</button></p>').join('');
      el('reviewPanel').querySelectorAll('[data-use]').forEach(button => {
        button.onclick = () => {
          localStorage.setItem('radar_suggestion', button.dataset.use);
          location.href = '/script';
        };
      });
      el('reviewPanel').querySelectorAll('[data-follow]').forEach(button => {
        button.onclick = () => { location.href = '/advice?followup=' + encodeURIComponent(button.dataset.follow); };
      });
    } catch (error) {
      el('snapshotStatus').textContent = error.message;
    }
  }

  async function saveSnapshot(uid) {
    const metrics = {};
    let invalid = '';
    document.querySelectorAll('[data-metric]').forEach(input => {
      const value = input.value.trim();
      if (value === '') {
        metrics[input.dataset.metric] = null;
        return;
      }
      if (!/^\d+$/.test(value)) {
        invalid = input.dataset.metric;
        return;
      }
      metrics[input.dataset.metric] = Number(value);
    });
    if (invalid) {
      el('snapshotStatus').textContent = '指标必须是非负整数或留空：' + invalid + '（输入已保留）';
      return;
    }
    const key = pendingSnapshotKey || el('snapKey').value.trim() || ('snap-' + Date.now());
    pendingSnapshotKey = key;
    try {
      const data = await post('/api/feedback/metrics', {
        record_uid: uid,
        snapshot_key: key,
        metrics: metrics,
        collected_at: localIso(el('snapCollected').value),
      });
      pendingSnapshotKey = '';
      el('snapshotStatus').textContent = '已保存快照 ' + data.snapshot_key;
      await openRecord(uid);
    } catch (error) { el('snapshotStatus').textContent = error.message; }
  }

  async function buildReview(uid) {
    try {
      const review = await post('/api/feedback/review', { record_uid: uid });
      el('reviewPanel').innerHTML = '<h4>复盘</h4>' +
        (review.observations_json || []).map(text => '<p>' + esc(text) + '</p>').join('') +
        (review.suggestions_json || []).map(item => '<p>' + esc(item.text) +
          '<br><small>依据：' + esc(item.basis) + ' · 条件：' + esc(item.conditions) +
          ' · 待验证：' + esc(item.pending) + '</small> ' +
          '<button class="secondary compact" data-use="' + esc(item.id) + '">用于下一任务</button>' +
          '<button class="secondary compact" data-follow="' + esc(item.id) + '">用于运营跟进</button></p>').join('');
      el('reviewPanel').querySelectorAll('[data-use]').forEach(button => {
        button.onclick = () => {
          localStorage.setItem('radar_suggestion', button.dataset.use);
          location.href = '/script';
        };
      });
      el('reviewPanel').querySelectorAll('[data-follow]').forEach(button => {
        button.onclick = () => { location.href = '/advice?followup=' + encodeURIComponent(button.dataset.follow); };
      });
    } catch (error) { el('snapshotStatus').textContent = error.message; }
  }

  async function loadConsultations(uid) {
    try {
      const notes = await getJson('/api/feedback/consultations?record=' + encodeURIComponent(uid));
      el('consultPanel').innerHTML =
        (notes.length ? notes.map(item => '<p>' + esc(item.occurred_at ? new Date(item.occurred_at * 1000).toLocaleString('zh-CN') : '未记录时间') +
          ' · ' + esc(item.text) + ' <small>' + esc(item.source) + ' · ' + esc(item.note_key) + '</small></p>').join('')
          : '<p class="script-hint">还没有咨询摘录。</p>') +
        '<label>备注键<input id="consultKey" maxlength="80" placeholder="例如 2026-10-20-1"></label>' +
        '<label>咨询摘录<textarea id="consultText" rows="2" maxlength="2000"></textarea></label>' +
        '<label>来源说明<input id="consultSource" maxlength="40" value="manual"></label>' +
        '<div class="script-actions"><button class="secondary" id="saveConsult" type="button">保存咨询摘录</button></div>' +
        '<p class="script-hint">咨询摘录是独立样本数，与指标中的咨询次数不可相加；来源为用户手动记录。</p>' +
        '<p id="consultStatus" class="script-hint" role="status"></p>';
      el('saveConsult').onclick = () => saveConsultation(uid);
    } catch (error) {
      el('consultPanel').textContent = '咨询摘录读取失败：' + error.message;
    }
  }

  let pendingConsultAt = 0;

  async function saveConsultation(uid) {
    el('consultStatus').textContent = '';
    if (!pendingConsultAt) pendingConsultAt = Date.now() / 1000;
    try {
      await post('/api/feedback/consultation', {
        record_uid: uid, note_key: el('consultKey').value.trim(),
        text: el('consultText').value.trim(),
        source: el('consultSource').value.trim() || 'manual',
        occurred_at: pendingConsultAt,
      });
      pendingConsultAt = 0;
      el('consultStatus').textContent = '已保存咨询摘录';
      loadConsultations(uid);
    } catch (error) { el('consultStatus').textContent = error.message; }
  }

  loadRecords();
  const params = new URLSearchParams(location.search);
  if (params.get('record')) {
    openRecord(params.get('record'), params.get('review'), params.get('suggestion'))
      .catch(error => { el('recordError').textContent = error.message; });
  }
  if (params.get('task')) el('recordTask').value = params.get('task');
  if (params.get('version')) el('recordVersion').value = params.get('version');
})();

// FI-F2：指定快照的转化观察；只调用本机确定性规则接口。
(() => {
  const el = id => document.getElementById(id);
  if (!el('conversionPanel')) return;
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state = {session:0, sourceSeq:0, recordSeq:0, historySeq:0, request:0, busy:0,
    baseline:'', report:null, reportKey:'', token:null, errorSeq:0};
  const collect = () => ({record_uid:el('conversionRecord').value, snapshot_id:el('conversionSnapshot').value,
    consultation_ids:[...el('conversionConsultations').querySelectorAll('[data-consultation]')].filter(e => e.checked).map(e => e.dataset.consultation),
    comparable:el('conversionComparable').checked});
  const key = value => JSON.stringify({...value, snapshot_id:String(value.snapshot_id ?? ''), consultation_ids:[...value.consultation_ids].sort()});
  const currentKey = () => key(collect());
  const dirty = () => currentKey() !== state.baseline;
  function error(text) { state.errorSeq++; el('conversionError').textContent = text || ''; }
  function changed() {
    el('conversionDirty').hidden = !dirty();
    el('conversionStale').hidden = !state.report || currentKey() === state.reportKey;
  }
  function session() {
    if (state.busy) el('conversionStatus').textContent = '';
    state.session++; state.sourceSeq++; state.recordSeq++; state.busy = 0;
    el('conversionBuild').disabled = false;
    return state.session;
  }
  async function api(path, body) {
    let options = {};
    if (body !== undefined) {
      const serialized = JSON.stringify(body);
      if (new TextEncoder().encode(serialized).length > 65536) throw Error('请求超过 65536 字节；未发送，请减少选择。');
      if (!state.token) state.token = fetch('/api/state?mode=live').then(async r => {
        if (!r.ok) throw Error('本机连接失败');
        return (await r.json()).token;
      }).catch(e => {state.token = null; throw e;});
      options = {method:'POST', headers:{'Content-Type':'application/json','X-Radar-Token':await state.token}, body:serialized};
    }
    const response = await fetch(path, options), data = await response.json();
    if (!response.ok) throw Error(data.error || '读取或保存失败');
    return data;
  }
  async function sources(uid) {
    const [snapshots, notes] = await Promise.all([
      api('/api/feedback/snapshots?record=' + encodeURIComponent(uid)),
      api('/api/feedback/consultations?record=' + encodeURIComponent(uid))]);
    if (!Array.isArray(snapshots) || !Array.isArray(notes)) throw Error('可选资料格式无效');
    return {snapshots, notes};
  }
  function fillSources(rows, selected) {
    const select = el('conversionSnapshot'), wanted = String(selected.snapshot_id || '');
    select.innerHTML = '<option value="">请选择一份快照</option>' + rows.snapshots.map(s =>
      `<option value="${esc(s.id)}">#${esc(s.id)} · ${esc(s.collected_at || '')} · ${esc(s.source || '未提供来源')} · ${esc(s.definition ?? '口径未提供')}</option>`).join('');
    if (wanted && !rows.snapshots.some(s => String(s.id) === wanted)) select.innerHTML += `<option value="${esc(wanted)}">#${esc(wanted)}（已不可用，请重新选择）</option>`;
    select.value = wanted;
    const ids = new Set(selected.consultation_ids), notes = [...rows.notes];
    for (const uid of ids) if (!notes.some(n => n.note_uid === uid)) notes.push({note_uid:uid, text:'已不可用，请取消选择后重新核对'});
    el('conversionConsultations').innerHTML = notes.length ? notes.map(n =>
      `<label><input type="checkbox" data-consultation="${esc(n.note_uid)}" ${ids.has(n.note_uid) ? 'checked' : ''}> ${esc(n.text)} <small>UID ${esc(n.note_uid)} · ${esc(n.source || '未提供来源')}</small></label>`).join('') : '<p class="script-hint">没有咨询摘录；可不选。摘录条数不会补成咨询次数。</p>';
    el('conversionConsultations').querySelectorAll('[data-consultation]').forEach(box => { box.onchange = changed; });
  }
  async function loadSources() {
    const seq = ++state.sourceSeq, owner = state.session, uid = el('conversionRecord').value, errorSeq = state.errorSeq;
    const fresh = () => seq === state.sourceSeq && owner === state.session && uid === el('conversionRecord').value;
    if (!uid) return;
    try {
      const rows = await sources(uid);
      if (!fresh()) return;
      fillSources(rows, collect()); changed();
    } catch (e) { if (fresh() && errorSeq === state.errorSeq) error(e.message + '；当前选择保留。'); }
  }
  async function refreshChoices() {
    const seq = ++state.recordSeq, owner = state.session, errorSeq = state.errorSeq;
    try {
      const records = await api('/api/feedback/records');
      if (owner !== state.session || seq !== state.recordSeq) return;
      if (!Array.isArray(records)) throw Error('登记列表格式无效');
      const select = el('conversionRecord'), uid = select.value;
      select.innerHTML = '<option value="">请选择登记</option>' + records.filter(r => !r.simulated && !r.archived).map(r =>
        `<option value="${esc(r.record_uid)}">${esc(r.platform)} · ${esc(r.platform_post_id)} · ${esc(r.record_uid)}</option>`).join('');
      if (uid && !records.some(r => r.record_uid === uid)) select.innerHTML += `<option value="${esc(uid)}">${esc(uid)}（关联登记不可用）</option>`;
      select.value = uid;
      await loadSources();
      if (owner === state.session && seq === state.recordSeq) refreshHistory();
    } catch (e) { if (owner === state.session && seq === state.recordSeq && errorSeq === state.errorSeq) error(e.message); }
  }
  async function refreshHistory() {
    const seq = ++state.historySeq, uid = el('conversionRecord').value, owner = state.session, errorSeq = state.errorSeq;
    try {
      const rows = await api('/api/feedback/reviews' + (uid ? '?record=' + encodeURIComponent(uid) : ''));
      if (seq !== state.historySeq || uid !== el('conversionRecord').value || owner !== state.session) return;
      const reports = rows.filter(r => r.data_json?.kind === 'conversion_observation');
      el('conversionHistory').innerHTML = reports.length ? reports.map(r => `<button type="button" class="secondary" data-conversion="${esc(r.review_uid)}">${esc(r.review_uid)} · 登记 ${esc(r.record_uid)} · 快照 #${esc(r.data_json?.snapshot?.id ?? '')}</button>`).join('') : '<p class="script-hint">暂无转化观察报告。</p>';
      el('conversionHistory').querySelectorAll('[data-conversion]').forEach(button => { button.onclick = () => openReport(button.dataset.conversion); });
    } catch (e) { if (seq === state.historySeq && owner === state.session && errorSeq === state.errorSeq) error('历史读取失败：' + e.message); }
  }
  function renderReport(review, reportKey) {
    const d = review.data_json, r = d.result || {}, s = d.snapshot || {};
    state.report = review; state.reportKey = reportKey;
    const lines = [d.label || '转化观察（规则）', '报告 ' + review.review_uid,
      '冻结登记：' + (d.record?.record_uid || review.record_uid) + ' · ' + (d.record?.platform_post_id || ''),
      '指定快照：#' + (s.id ?? '') + ' · 来源 ' + (s.source || '未提供') + ' · 采集 ' + (s.collected_at || '未提供'),
      '口径：' + (s.definition || '未提供'), '可比声明：' + (d.comparable ? '是' : '未声明'),
      '播放：' + (d.counts?.plays ?? '未知') + '；咨询次数：' + (d.counts?.inquiries ?? '未知'),
      r.metric || '每100次播放的咨询事件数', '公式：' + (r.formula || ''),
      r.value == null ? '未计算：' + (r.gaps || []).join('、') : '规则结果：' + r.value,
      '咨询摘录 ' + (d.consultation_snapshot || []).length + ' 条（人工样本，独立于咨询次数）'];
    for (const n of d.consultation_snapshot || []) lines.push(`${n.text ?? ''}（UID ${n.note_uid}；来源 ${n.source ?? '未提供'}；时间 ${n.occurred_at ?? '未提供'}）`);
    lines.push(...(r.limits || []));
    el('conversionResult').textContent = lines.join('\n');
    el('conversionExport').href = '/api/ops/conversion/export?id=' + encodeURIComponent(review.review_uid);
    el('conversionExport').hidden = false;
    if (el('conversionFollowups')) el('conversionFollowups').innerHTML = (review.suggestions_json || []).map(s =>
      `<p>${esc(s.text)} <a href="/advice?followup=${encodeURIComponent(s.id)}">用于运营跟进</a></p>`).join('');
    changed();
  }
  async function openReport(uid) {
    if (dirty() && !confirm('当前转化观察选择有未保存修改，打开历史会覆盖；继续？')) return;
    const before = currentKey(), owner = session();
    try {
      const review = await api('/api/ops/conversion?id=' + encodeURIComponent(uid));
      if (owner !== state.session) return;
      const d = review.data_json, record = d.record?.record_uid || review.record_uid;
      const rows = await sources(record);
      if (owner !== state.session) return;
      if (currentKey() !== before && !confirm('等待期间有新的转化观察选择，打开历史会覆盖；继续？')) return;
      if (owner !== state.session) return;
      const select = el('conversionRecord');
      if (![...select.options].some(o => o.value === record)) select.innerHTML += `<option value="${esc(record)}">${esc(record)}（冻结登记）</option>`;
      select.value = record;
      fillSources(rows, {snapshot_id:d.snapshot?.id ?? review.snapshot_ids?.[0] ?? '', consultation_ids:d.consultation_ids || []});
      el('conversionComparable').checked = d.comparable === true;
      state.baseline = currentKey(); renderReport(review, state.baseline);
      error(''); el('conversionStatus').textContent = '已打开冻结报告'; refreshHistory();
    } catch (e) { if (owner === state.session) error(e.message + '；当前输入与结果保留。'); }
  }
  async function build() {
    if (state.busy) return;
    const selected = collect(), payload = {...selected, snapshot_id:Number(selected.snapshot_id)};
    if (!payload.record_uid || !Number.isSafeInteger(payload.snapshot_id) || payload.snapshot_id <= 0) {error('请明确选择登记和一份指标快照'); return;}
    if (payload.consultation_ids.length > 12) {error('最多选择 12 条咨询摘录'); return;}
    if (new TextEncoder().encode(JSON.stringify(payload)).length > 65536) {error('请求超过 65536 字节；未发送，请减少选择。'); return;}
    const owner = state.session, request = ++state.request, submitted = key(payload);
    state.busy = request; el('conversionBuild').disabled = true; error(''); el('conversionStatus').textContent = '正在保存规则报告…';
    try {
      const review = await api('/api/ops/conversion/build', payload);
      if (owner !== state.session || state.busy !== request) return;
      state.baseline = submitted; renderReport(review, submitted);
      el('conversionStatus').textContent = '已保存新的规则报告；未调用模型'; refreshHistory();
    } catch (e) {
      if (owner === state.session && state.busy === request) {
        error(e.message + '；输入保留。');
        el('conversionStatus').textContent = '保存未完成，请核对错误或刷新历史';
      }
    }
    finally { if (owner === state.session && state.busy === request) {state.busy = 0; el('conversionBuild').disabled = false;} }
  }
  el('conversionRecord').onchange = () => {
    session(); el('conversionSnapshot').innerHTML = '<option value="">请选择一份快照</option>';
    el('conversionSnapshot').value = ''; el('conversionConsultations').innerHTML = '';
    el('conversionComparable').checked = false; error(''); changed(); refreshHistory(); return loadSources();
  };
  el('conversionSnapshot').onchange = changed; el('conversionComparable').onchange = changed;
  el('conversionBuild').onclick = build; el('conversionRefresh').onclick = refreshChoices;
  state.baseline = currentKey(); changed(); refreshChoices();
})();
