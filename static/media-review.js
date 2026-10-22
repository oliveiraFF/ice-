(() => {
  const el = id => document.getElementById(id);
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
  const MAX_BYTES = 20 * 1024 * 1024;
  const MAX_SECONDS = 180;
  const MAX_FRAMES = 16;
  let token = '', frames = [], videoInfo = null, drafts = [], current = null, busy = false;
  let pageSeq = 0, materialSeq = 0;
  let baseline = {goal: '', business: '', audience: '', resources: '', transcript: '', source: 'none',
                  complete: false, manuscript: '', material: ''};

  const initial = fetch('/api/state?mode=live').then(async r => {
    if (!r.ok) throw new Error('本机连接失败，请重新打开页面');
    token = (await r.json()).token;
  });
  initial.catch(error => { el('mrError').textContent = error.message; });

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

  function setBusy(value, text) {
    busy = value;
    ['mrAnalyzeDemo', 'mrAnalyzeReal'].forEach(id => { el(id).disabled = value; });
    if (text) el('mrStatus').textContent = text;
  }

  function materialKey() {
    return videoInfo
      ? [videoInfo.name, videoInfo.size, videoInfo.duration, frames.map(item => item.at).join(',')].join('|')
      : '';
  }
  function manuscriptValue() {
    return el('mrDraft').value ? el('mrDraft').value + ':' + (el('mrDraftVersion').value || '') : '';
  }
  function collectInput() {
    return {
      goal: el('mrGoal').value.trim(), business: el('mrBusiness').value.trim(),
      audience: el('mrAudience').value.trim(), resources: el('mrResources').value.trim(),
      transcript: el('mrTranscript').value.trim(), source: el('mrTranscriptSource').value,
      complete: el('mrTranscriptComplete') ? el('mrTranscriptComplete').checked : false,
      manuscript: manuscriptValue(), material: materialKey(),
    };
  }
  function sameInput(left, right) {
    return Object.keys(right).every(key => (left[key] || '') === (right[key] || ''));
  }
  function dirty() { return !sameInput(collectInput(), baseline); }
  function resetBaseline() { baseline = collectInput(); }
  function fillInput(input, scope) {
    const data = input || {};
    const range = scope || {};
    el('mrGoal').value = data.goal || '';
    el('mrBusiness').value = data.business || '';
    el('mrAudience').value = data.audience || '';
    el('mrResources').value = data.resources || '';
    const transcript = data.transcript || range.transcript || {};
    el('mrTranscriptSource').value = transcript.source === 'manual' ? 'manual' : 'none';
    el('mrTranscript').value = typeof transcript.text === 'string' ? transcript.text : '';
    const complete = typeof data.transcript_complete === 'boolean' ? data.transcript_complete
      : (typeof range.transcript_complete === 'boolean' ? range.transcript_complete : false);
    if (el('mrTranscriptComplete')) el('mrTranscriptComplete').checked = complete;
  }

  function clearReport(text) {
    el('mrResult').hidden = true;
    ['mrSummary', 'mrScope', 'mrObservations', 'mrChanges', 'mrCannot', 'mrGaps', 'mrNext'].forEach(id => {
      const node = el(id);
      if (node) { node.innerHTML = ''; node.textContent = ''; }
    });
    if (text) el('mrStatus').textContent = text;
  }

  function jpegBytes(dataUrl) {
    const base64 = String(dataUrl || '').slice(String(dataUrl || '').indexOf(',') + 1);
    const padded = base64.endsWith('==') ? 2 : base64.endsWith('=') ? 1 : 0;
    return Math.floor(base64.length * 3 / 4) - padded;
  }

  async function loadVideo(file) {
    el('mrError').textContent = '';
    const seq = ++materialSeq;
    frames = [];
    videoInfo = null;
    el('mrFrames').innerHTML = '';
    el('mrVideoInfo').textContent = '未选择素材。';
    clearReport(file ? '素材已更换：旧报告已隐藏，请重新采样并分析。' : '');
    if (!file) return;
    if (file.size > MAX_BYTES) { el('mrError').textContent = '视频超过 20MB 上限'; return; }
    const url = URL.createObjectURL(file);
    try {
      const video = document.createElement('video');
      video.preload = 'auto';
      video.muted = true;
      video.src = url;
      await new Promise((resolve, reject) => {
        video.onloadedmetadata = () => resolve();
        video.onerror = () => reject(new Error('无法读取视频'));
      });
      if (seq !== materialSeq) return;
      let duration = Number(video.duration);
      if (!isFinite(duration)) {
        video.currentTime = 1e101;
        await new Promise(resolve => { video.ontimeupdate = () => { video.ontimeupdate = null; resolve(); }; });
        if (seq !== materialSeq) return;
        duration = Number(video.duration);
        video.currentTime = 0;
      }
      if (!isFinite(duration) || duration <= 0 || duration > MAX_SECONDS) {
        el('mrError').textContent = '视频时长需在 0–180 秒内';
        return;
      }
      const localFrames = [];
      const count = Math.min(MAX_FRAMES, Math.max(2, Math.floor(duration) + 1));
      const canvas = document.createElement('canvas');
      const context = canvas.getContext('2d');
      for (let index = 0; index < count; index += 1) {
        if (seq !== materialSeq) return;
        const at = Math.min(duration - 0.05, Math.max(0.05, (duration - 0.1) * index / Math.max(1, count - 1) + 0.05));
        video.currentTime = at;
        await new Promise(resolve => { video.onseeked = () => resolve(); });
        if (seq !== materialSeq) return;
        canvas.width = 320;
        canvas.height = Math.max(1, Math.round(320 * (video.videoHeight || 9) / (video.videoWidth || 16)));
        context.drawImage(video, 0, 0, canvas.width, canvas.height);
        const image = canvas.toDataURL('image/jpeg', 0.6);
        const bytes = jpegBytes(image);
        if (image.length > 280000 || bytes > 204800) {
          el('mrError').textContent = '采样帧解码后超过 200KB 限制（' + bytes + ' 字节），请缩短时长或降低分辨率';
          continue;
        }
        localFrames.push({frame: localFrames.length + 1, at: Math.round(at * 100) / 100, image: image});
        if (seq !== materialSeq) return;
        const thumb = document.createElement('figure');
        thumb.innerHTML = '<img alt="帧" src="' + image + '"><figcaption>帧' + localFrames.length + ' · ' + at.toFixed(2) + '秒</figcaption>';
        el('mrFrames').appendChild(thumb);
      }
      if (seq !== materialSeq) return;
      videoInfo = {name: file.name, size: file.size, duration: duration};
      frames = localFrames;
      el('mrVideoInfo').textContent = file.name + ' · ' + duration.toFixed(1) + ' 秒 · ' +
        (file.size / 1048576).toFixed(1) + ' MB（本机读取，未上传整段视频）';
      el('mrStatus').textContent = '已采样 ' + frames.length + ' 帧；仍在本机，未上传。';
    } catch (error) {
      if (seq !== materialSeq) return;
      el('mrError').textContent = '无法读取视频：' + error.message;
    } finally {
      URL.revokeObjectURL(url);
    }
  }

  async function loadDrafts() {
    try {
      drafts = await request('/api/ops/draft/list', null);
      el('mrDraft').innerHTML = '<option value="">不关联</option>' + drafts.map(item =>
        '<option value="' + esc(item.draft_uid) + '">' + esc(item.topic || '（无主题）') + '</option>').join('');
    } catch (error) { el('mrManuscriptInfo').textContent = '研究稿列表读取失败'; }
  }

  function renderDraftVersions() {
    const draft = drafts.find(item => item.draft_uid === el('mrDraft').value);
    el('mrDraftVersion').innerHTML = draft && draft.versions && draft.versions.length
      ? draft.versions.map(version => '<option value="' + version.version + '">v' + version.version + ' · ' + esc(version.source || 'demo') + '</option>').join('')
      : '<option value="">（无版本）</option>';
    el('mrManuscriptInfo').textContent = draft
      ? '关联仅用于对照；该版本的主题/业务/资料按当时冻结内容进入审阅，不改研究稿身份或批准状态。' : '';
  }

  function transcript() {
    const source = el('mrTranscriptSource').value;
    const text = el('mrTranscript').value;
    return {source: source === 'manual' && text.trim() ? 'manual' : 'none', text: text.trim(),
            complete: el('mrTranscriptComplete') ? el('mrTranscriptComplete').checked : false};
  }

  async function analyze(real) {
    el('mrError').textContent = '';
    if (!videoInfo || !frames.length) { el('mrError').textContent = '请先选择视频并完成采样'; return; }
    if (!el('mrGoal').value.trim()) { el('mrError').textContent = '请填写审阅目标'; return; }
    if (el('mrGoal').value.trim().length > 2000) { el('mrError').textContent = '审阅目标超过 2000 字上限'; return; }
    const pendingTranscript = transcript();
    if (pendingTranscript.source === 'manual' && pendingTranscript.text.length > 5000) {
      el('mrError').textContent = '人工台词超过 5000 字上限，请精简后再提交';
      return;
    }
    if (real && !el('mrRealConfirm').checked) { el('mrError').textContent = '真实调用需勾选本次确认'; return; }
    const payload = {
      goal: el('mrGoal').value.trim(), business: el('mrBusiness').value.trim(),
      audience: el('mrAudience').value.trim(), resources: el('mrResources').value.trim(),
      duration: videoInfo.duration,
      frames: frames.map(item => ({frame: item.frame, at: item.at, image: item.image})),
      transcript: pendingTranscript,
      model_mode: real ? 'real' : 'test', confirm: real,
    };
    if (el('mrDraft').value) {
      const version = Number(el('mrDraftVersion').value);
      if (!version) { el('mrError').textContent = '请选择研究稿版本'; return; }
      payload.draft_uid = el('mrDraft').value;
      payload.draft_version = version;
    }
    const submitted = collectInput();
    const seq = ++pageSeq;
    const material = materialSeq;
    try {
      setBusy(true, real ? '审阅中…' : '演示审阅中…');
      const data = await request('/api/ops/media-review/analyze', payload);
      if (seq !== pageSeq || material !== materialSeq) {
        el('mrStatus').textContent = '结果已保存；当前素材已更换，未作为新素材结果展示';
        loadHistory();
        return;
      }
      render(data.review);
      baseline = submitted;
      el('mrStatus').textContent = '审阅完成（' + (data.review.source || 'demo') + '）';
      loadHistory();
    } catch (error) { el('mrStatus').textContent = ''; el('mrError').textContent = error.message; }
    finally { el('mrRealConfirm').checked = false; setBusy(false); }
  }

  function render(review) {
    current = review;
    const result = review.result_json || {};
    const scope = review.scope_json || {};
    el('mrResult').hidden = false;
    el('mrSummary').textContent = result.summary || '';
    el('mrScope').textContent = '本次范围：时长 ' + (scope.duration || '') + ' 秒 · 采样帧 ' + ((scope.frames || []).length) + ' 张 · 台词来源 ' + ((scope.transcript || {}).source || 'none') + ' · 模型不听音轨、未完整观看' + (review.draft_uid ? ' · 关联研究稿 ' + review.draft_uid + ' v' + review.draft_version : '');
    el('mrObservations').innerHTML = (result.observations || []).map(item =>
      '<li>' + esc(item.text) + ' <small>' + esc(item.kind + (item.frames && item.frames.length ? ' · 帧' + item.frames.join('/') : '') + (item.unverified ? ' · 待验证' : '')) + '</small></li>').join('') || '<li class="script-hint">（无）</li>';
    el('mrChanges').innerHTML = (result.changes || []).map(item =>
      '<p><strong>' + esc(item.what) + '</strong><br><small>为什么：' + esc(item.why || '未填') + ' · 依据：' + esc(item.basis || '未填') + ' · 条件：' + esc(item.conditions || '未填') + ' · 缺口：' + esc(item.gaps || '未填') + ' · 下一步：' + esc(item.next || '未填') + (item.frames && item.frames.length ? ' · 帧' + item.frames.join('/') : '') + '</small></p>').join('') || '<p class="script-hint">（无）</p>';
    el('mrCannot').innerHTML = (result.cannot_judge || []).map(item => '<li>' + esc(item) + '</li>').join('') || '<li class="script-hint">（无）</li>';
    el('mrGaps').innerHTML = (result.gaps || []).map(item => '<li>' + esc(item) + '</li>').join('') || '<li class="script-hint">（无）</li>';
    el('mrNext').innerHTML = (result.next || []).map(item => '<li>' + esc(item) + '</li>').join('') || '<li class="script-hint">（无）</li>';
  }

  async function openReview(uid) {
    if (dirty() && !confirm('当前输入与素材有未保存修改，打开历史会覆盖；继续？')) return;
    const before = collectInput();
    const seq = ++pageSeq;
    try {
      const data = await request('/api/ops/media-review?id=' + encodeURIComponent(uid), null);
      if (seq !== pageSeq) return;
      if (!sameInput(collectInput(), before) &&
          !confirm('等待期间有新的编辑，打开历史会覆盖；继续？')) return;
      materialSeq += 1;
      frames = [];
      videoInfo = null;
      el('mrFrames').innerHTML = '';
      el('mrVideoInfo').textContent = '历史记录不含原视频/采样帧，请重新选择素材。';
      fillInput(data.input_json, data.scope_json);
      if (data.draft_uid) {
        el('mrDraft').value = data.draft_uid;
        renderDraftVersions();
        el('mrDraftVersion').value = String(data.draft_version);
      } else {
        el('mrDraft').value = '';
        renderDraftVersions();
      }
      render(data);
      baseline = collectInput();
      el('mrStatus').textContent = '已打开 ' + uid + '（历史记录，素材已清空，需重新选择）';
    } catch (error) { el('mrError').textContent = error.message; }
  }

  async function loadHistory() {
    try {
      const list = await request('/api/ops/media-review/list', null);
      el('mrHistory').innerHTML = list.length ? list.map(item =>
        '<button class="mr-history-item" data-open="' + esc(item.review_uid) + '">' + esc(item.goal || '（无目标）') +
        ' <small>' + esc(item.source) + ' · ' + ((item.scope_json || {}).frames || []).length + ' 帧 · ' +
        new Date((item.created_at || 0) * 1000).toLocaleString('zh-CN') + '</small></button>').join('')
        : '<p class="script-hint">还没有审阅记录。</p>';
      el('mrHistory').querySelectorAll('[data-open]').forEach(button => {
        button.onclick = () => openReview(button.dataset.open);
      });
    } catch (error) { el('mrHistory').innerHTML = '<p class="script-hint">历史读取失败</p>'; }
  }

  el('mrVideo').addEventListener('change', event => {
    loadVideo(event.target.files && event.target.files[0]).catch(error => { el('mrError').textContent = error.message; });
  });
  el('mrDraft').addEventListener('change', renderDraftVersions);
  el('mrAnalyzeDemo').onclick = () => analyze(false);
  el('mrAnalyzeReal').onclick = () => analyze(true);
  loadDrafts().then(() => {
    if (typeof location === 'undefined') return;
    const uid = new URLSearchParams(location.search).get('id');
    if (uid && /^[a-f0-9]{12}$/.test(uid)) openReview(uid);
  });
  loadHistory();
})();
