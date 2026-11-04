/* finesse · component=capture-picker · register=product · existing theme tokens */
(function (root, factory) {
  const picker = factory();
  if (typeof module === 'object' && module.exports) module.exports = picker;
  else root.CapturePicker = picker;
})(typeof window === 'object' ? window : globalThis, function () {
  'use strict';
  const LIMIT = 20, STORAGE = 'ice-capture-picker-v1';
  const domestic = new Set(['bilibili','douyin','kuaishou','net_ease_cloud_music','pipixia','toutiao','wechat_channels','wechat_mp','wechat_search','weibo','xiaohongshu','xigua','zhihu']);
  const overseas = new Set(['instagram','lemon8','linkedin','reddit','telegram','threads','tiktok','twitter','youtube']);
  const names = {douyin:'抖音',xiaohongshu:'小红书',bilibili:'哔哩哔哩',kuaishou:'快手',toutiao:'今日头条',wechat_channels:'微信视频号',wechat_mp:'微信公众号',wechat_search:'微信搜索',weibo:'微博',xigua:'西瓜视频',zhihu:'知乎',net_ease_cloud_music:'网易云音乐',pipixia:'皮皮虾',tiktok:'TikTok',youtube:'YouTube',instagram:'Instagram',twitter:'X / Twitter',reddit:'Reddit',linkedin:'LinkedIn',telegram:'Telegram',threads:'Threads',lemon8:'Lemon8',tikhub:'TikHub 账户',health:'服务状态',captcha:'验证码服务',sora2:'Sora 2',ios_shortcut:'iOS 快捷指令',hybrid:'通用解析',demo:'演示接口'};
  const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
  const regionOf = platform => domestic.has(platform) ? 'domestic' : overseas.has(platform) ? 'overseas' : 'other';
  const platformName = item => names[item.platform] || item.platform_name || item.platform;
  function filter(items, region, platform, query = '') {
    const q = query.trim().toLocaleLowerCase();
    return items.filter(item => (!region || regionOf(item.platform) === region) && (!platform || item.platform === platform) &&
      (!q || [item.title,item.path,item.method,platformName(item)].join(' ').toLocaleLowerCase().includes(q)));
  }
  function validSelection(ids, items) {
    const known = new Set(items.map(item => item.id));
    return [...new Set(Array.isArray(ids) ? ids : [])].filter(id => typeof id === 'string' && known.has(id)).slice(0, LIMIT);
  }
  function parameterURL(item, keyword = '', ids = [item.id]) {
    const query = new URLSearchParams({id:item.id, collect:item.collection_supported === true ? '1' : '0'});
    if (keyword.trim()) query.set('keyword', keyword.trim().slice(0, 40));
    for (const id of [...new Set(ids)].slice(0, LIMIT)) query.append('pick', id);
    return '/market?' + query.toString();
  }
  function statusOf(item, tool) {
    if (item.availability === 'unavailable') return '不可用 · 已暂停';
    if (!item.documented || !item.runnable) return '待接入';
    if (item.legacy_documentation && /历史.*暂停|历史.*搜索/.test(item.execution_reason || '')) return '历史接口 · 已暂停';
    return (tool?.enabled ? '已启用' : '未启用') + ' · ' + (item.availability_label || '待验证');
  }
  function mount({api, toast}) {
    const $ = id => document.getElementById(id);
    let model = {items:[],tools:{}}, selected = [], region = 'domestic', platform = 'douyin', sequence = 0, ready = false;
    try {
      const raw = localStorage.getItem(STORAGE);
      const saved = raw && raw.length < 20000 ? JSON.parse(raw) : null;
      if (saved) {
        selected = Array.isArray(saved.selected) ? saved.selected.slice(0, LIMIT) : [];
        if (['domestic','overseas','other'].includes(saved.region)) region = saved.region;
        if (typeof saved.platform === 'string') platform = saved.platform;
      }
    } catch {}
    const items = () => selected.map(id => model.items.find(item => item.id === id)).filter(Boolean);
    function save() {
      try { localStorage.setItem(STORAGE, JSON.stringify({region,platform,selected})); } catch {}
    }
    function navigate(item) {
      location.href = parameterURL(item, $('searchKeywordInput').value, selected);
    }
    function renderSelection() {
      const chosen = items();
      $('captureSelected').hidden = !chosen.length;
      $('captureSelectedCount').textContent = `已选 ${chosen.length} 个接口 · 在参数页逐个切换、手动执行`;
      $('captureSelectedList').innerHTML = chosen.map((item,index) => `<li><span><strong>${escape(platformName(item))} · ${escape(item.title)}</strong><code>${escape(item.method)} ${escape(item.path)}</code></span><button type="button" class="secondary" data-open="${index}" ${ready ? '' : 'disabled'}>填写参数</button><button type="button" class="text-button" data-remove="${index}" aria-label="移除 ${escape(item.title)}">移除</button></li>`).join('');
      $('keywordSearchSubmit').disabled = !ready || !chosen.length;
      $('keywordSearchSubmit').textContent = chosen.length ? `填写所选接口参数（${chosen.length}）` : '先选择接口';
    }
    function renderRows() {
      const rows = filter(model.items, region, platform, $('captureQuery').value);
      $('captureMatchCount').textContent = `当前平台 ${rows.length} 个匹配接口`;
      $('captureEndpointList').innerHTML = rows.length ? rows.map(item => `<label class="capture-choice"><input type="checkbox" data-capture-id="${escape(item.id)}" ${selected.includes(item.id) ? 'checked' : ''}><span class="capture-choice-content"><strong>${escape(item.title)}</strong><code>${escape(item.method)} ${escape(item.path)}</code><span class="capture-choice-meta"><span>${escape(statusOf(item,model.tools[item.id]))}</span><span>目录标价 ${item.price == null ? '未知' : '$' + escape(item.price)} / 次</span><span>${item.collection_supported ? '可尝试识别作品' : '仅查看响应 · 作品收录待接入'}</span></span>${item.execution_reason ? `<small>${escape(item.execution_reason)}</small>` : ''}</span></label>`).join('') : '<p class="capture-empty">没有匹配接口，请清空筛选词或更换平台。</p>';
    }
    function renderPlatforms() {
      const available = [...new Map(filter(model.items,region,'').map(item => [item.platform,platformName(item)])).entries()].sort((a,b) => a[1].localeCompare(b[1],'zh-CN'));
      if (!available.some(([id]) => id === platform)) platform = available[0]?.[0] || '';
      $('capturePlatform').innerHTML = available.length ? available.map(([id,name]) => `<option value="${escape(id)}">${escape(name)}</option>`).join('') : '<option value="">暂无平台</option>';
      $('capturePlatform').value = platform;
      $('capturePlatform').disabled = !available.length;
      $('captureRegion').value = region;
      renderRows(); save();
    }
    async function load() {
      const current = ++sequence;
      ready = false;
      $('refreshKeywordEndpoints').disabled = true;
      $('captureEndpointList').setAttribute('aria-busy','true');
      $('captureEndpointList').inert = true;
      $('keywordSearchStatus').textContent = '正在读取本机接口目录，不会执行抓取…';
      renderSelection();
      try {
        const snapshot = await api('/api/catalog');
        if (current !== sequence) return;
        model = snapshot; selected = validSelection(selected,model.items); ready = true;
        renderPlatforms(); renderSelection();
        $('keywordSearchStatus').textContent = `已读取 ${new Set(model.items.map(item => item.platform)).size} 个平台。选择和切换不发起收费请求；每个接口需到参数页单独确认执行。目录价格、文档状态与真实可用性分别展示。`;
      } catch (error) {
        if (current !== sequence) return;
        $('keywordSearchStatus').textContent = '目录读取失败：' + error.message + '。请恢复连接后点击“刷新接口”；已选项会保留。';
        renderSelection();
      } finally {
        if (current === sequence) {
          $('refreshKeywordEndpoints').disabled = false;
          $('captureEndpointList').setAttribute('aria-busy','false');
          $('captureEndpointList').inert = false;
        }
      }
    }
    $('captureRegion').onchange = () => { region = $('captureRegion').value; $('captureQuery').value = ''; renderPlatforms(); };
    $('capturePlatform').onchange = () => { platform = $('capturePlatform').value; $('captureQuery').value = ''; renderRows(); save(); };
    $('captureQuery').oninput = renderRows;
    $('captureEndpointList').onchange = event => {
      const input = event.target.closest('[data-capture-id]');
      if (!input) return;
      const id = input.dataset.captureId;
      if (input.checked && selected.length >= LIMIT) { input.checked = false; toast(`最多选择 ${LIMIT} 个接口，请先移除不需要的接口。`); return; }
      selected = input.checked ? [...new Set([...selected,id])] : selected.filter(value => value !== id);
      save(); renderSelection();
    };
    $('captureSelectedList').onclick = event => {
      const button = event.target.closest('button');
      if (!button) return;
      const chosen = items(), index = Number(button.dataset.open ?? button.dataset.remove), item = chosen[index];
      if (!item) return;
      if (button.dataset.open !== undefined) navigate(item);
      else { selected = selected.filter(id => id !== item.id); save(); renderRows(); renderSelection(); }
    };
    $('keywordSearchForm').onsubmit = event => { event.preventDefault(); const item = items()[0]; if (ready && item) navigate(item); else toast('请先选择接口。'); };
    $('refreshKeywordEndpoints').onclick = load;
    load();
  }
  return {filter,regionOf,validSelection,parameterURL,statusOf,mount};
});
