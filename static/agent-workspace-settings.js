/* finesse · companion behavior for the Agent workspace settings component; visual tokens and layout are in agent-workspace-settings.css. */
/* ICE product settings · persistent local path only; workspace content remains read-only. */
(() => {
  const dialog = document.getElementById('siteSettingsDialog');
  const keyForm = document.getElementById('siteSettingsForm');
  if (!dialog || !keyForm || document.getElementById('agentWorkspaceForm')) return;

  const styles = document.createElement('link');
  styles.rel = 'stylesheet';
  styles.href = '/agent-workspace-settings.css';
  document.head.append(styles);

  keyForm.insertAdjacentHTML('beforebegin', `
    <section class="agent-workspace-settings" aria-labelledby="agentWorkspaceTitle">
      <div class="agent-workspace-heading">
        <div>
          <h3 id="agentWorkspaceTitle">Agent workspace <span class="agent-readonly-tag">只读</span></h3>
          <p>连接你的 short-video-ops-kit 工作区，供运营总览读取资料。ICE 只保存目录路径，不改写工作区文件。</p>
        </div>
      </div>
      <form id="agentWorkspaceForm" novalidate>
        <label for="agentWorkspacePath">本机工作区目录</label>
        <div class="agent-workspace-path-row">
          <input id="agentWorkspacePath" name="workspace_path" type="text" autocomplete="off" spellcheck="false"
            aria-describedby="agentWorkspaceHelp agentWorkspaceStatus" placeholder="粘贴 Agent workspace 完整目录路径">
          <button id="agentWorkspaceBrowse" class="secondary" type="button" disabled>选择目录</button>
        </div>
        <p id="agentWorkspaceHelp" class="helper">会先检查 project.manifest.json。浏览器调试模式可粘贴完整路径；桌面版可打开系统目录选择器。</p>
        <p id="agentWorkspaceStatus" class="agent-workspace-status" role="status" aria-live="polite"></p>
        <div class="agent-workspace-actions">
          <button id="agentWorkspaceClear" class="text-button" type="button">清除路径绑定</button>
          <button id="agentWorkspaceSave" class="primary" type="submit">校验并保存</button>
        </div>
      </form>
    </section>`);

  const el = id => document.getElementById(id);
  const pathInput = el('agentWorkspacePath');
  const browseButton = el('agentWorkspaceBrowse');
  const saveButton = el('agentWorkspaceSave');
  const clearButton = el('agentWorkspaceClear');
  const status = el('agentWorkspaceStatus');
  let busy = false;

  function setStatus(message, kind = 'info') {
    status.textContent = message || '';
    status.dataset.state = kind;
    const pathError = kind === 'error' && /目录|manifest|workspace|路径/i.test(message || '');
    pathInput.setAttribute('aria-invalid', String(pathError));
  }

  function updatePickerAvailability() {
    const ready = Boolean(window.pywebview?.api?.choose_agent_workspace);
    browseButton.disabled = !ready || busy;
    browseButton.title = ready ? '' : '桌面版提供系统目录选择器；浏览器调试模式请粘贴完整路径';
  }

  async function stateToken() {
    const response = await fetch('/api/state?mode=live', {cache: 'no-store'});
    if (!response.ok) throw new Error('无法读取本机设置状态，请刷新页面后重试');
    const state = await response.json();
    if (!state.token) throw new Error('本机设置令牌不可用，请刷新页面后重试');
    return state.token;
  }

  async function loadConfig() {
    setStatus('正在读取本机路径设置…');
    try {
      const response = await fetch('/api/agent/workspace-config', {cache: 'no-store'});
      const config = await response.json();
      if (!response.ok) throw new Error(config.error || '读取 Agent workspace 设置失败');
      pathInput.value = config.configured_path || config.effective_path || '';
      if (config.environment_override) {
        setStatus(config.valid
          ? '当前环境变量覆盖本机保存值；本机设置仅用于无覆盖的正式启动。'
          : (config.message || '环境变量中的工作区路径无效。'), config.valid ? 'info' : 'error');
      } else if (config.valid) {
        setStatus('已连接：目录校验通过，路径保存在 ICE 本机数据目录。', 'success');
      } else {
        setStatus(config.message || '尚未配置 Agent workspace。', config.configured_path ? 'error' : 'info');
      }
    } catch (error) {
      setStatus(error.message || '读取设置失败。', 'error');
    }
  }

  async function saveConfig(payload) {
    const token = await stateToken();
    const response = await fetch('/api/agent/workspace-config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-Radar-Token': token},
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || '保存 Agent workspace 设置失败');
    return result;
  }

  document.addEventListener('click', event => {
    if (event.target.closest('#siteSettings, [data-site-settings]')) window.setTimeout(loadConfig, 0);
  });
  window.addEventListener('pywebviewready', updatePickerAvailability);
  updatePickerAvailability();

  browseButton.addEventListener('click', async () => {
    if (!window.pywebview?.api?.choose_agent_workspace) return;
    browseButton.disabled = true;
    try {
      const selected = await window.pywebview.api.choose_agent_workspace();
      if (selected) {
        pathInput.value = selected;
        setStatus('目录已选择；校验并保存后才会生效。', 'info');
      }
    } catch (_) {
      setStatus('无法打开系统目录选择器；你也可以粘贴完整目录路径。', 'error');
    } finally {
      updatePickerAvailability();
    }
  });

  el('agentWorkspaceForm').addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    const workspacePath = pathInput.value.trim();
    if (!workspacePath) {
      pathInput.focus();
      setStatus('请先选择或粘贴 Agent workspace 目录。', 'error');
      return;
    }
    busy = true;
    el('agentWorkspaceForm').setAttribute('aria-busy', 'true');
    saveButton.disabled = true;
    clearButton.disabled = true;
    pathInput.disabled = true;
    saveButton.textContent = '校验中…';
    setStatus('正在检查 manifest 并保存本机路径…');
    try {
      const result = await saveConfig({workspace_path: workspacePath});
      setStatus(result.message || 'Agent workspace 已保存。', 'success');
      document.dispatchEvent(new CustomEvent('agent-workspace-config-changed'));
      await loadConfig();
    } catch (error) {
      setStatus(error.message || '保存失败；原有路径设置保持不变。', 'error');
    } finally {
      busy = false;
      el('agentWorkspaceForm').setAttribute('aria-busy', 'false');
      pathInput.disabled = false;
      saveButton.disabled = false;
      clearButton.disabled = false;
      saveButton.textContent = '校验并保存';
      updatePickerAvailability();
    }
  });

  clearButton.addEventListener('click', async () => {
    if (busy || !window.confirm('只清除 ICE 中保存的路径，不会删除 Agent workspace 文件。继续吗？')) return;
    busy = true;
    clearButton.disabled = true;
    saveButton.disabled = true;
    try {
      const result = await saveConfig({clear: true});
      pathInput.value = '';
      setStatus(result.message || '已清除本机路径绑定。', 'success');
      document.dispatchEvent(new CustomEvent('agent-workspace-config-changed'));
      await loadConfig();
    } catch (error) {
      setStatus(error.message || '清除失败。', 'error');
    } finally {
      busy = false;
      el('agentWorkspaceForm').setAttribute('aria-busy', 'false');
      clearButton.disabled = false;
      saveButton.disabled = false;
      updatePickerAvailability();
    }
  });
})();
