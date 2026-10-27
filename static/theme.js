/* Read before styles paint; preferences contain only the selected color mode. */
window.IceTheme = (() => {
  const key = 'ice-ui-theme-v1';
  const valid = value => value === 'light' || value === 'dark';
  function read() {
    try {
      const cookie = document.cookie.split('; ').find(item => item.startsWith(key + '='))?.split('=')[1];
      if (valid(cookie)) return cookie;
    } catch {}
    try { const saved = localStorage.getItem(key); if (valid(saved)) return saved; } catch {}
    return 'light';
  }
  function apply(mode, save = false) {
    if (!valid(mode)) return;
    document.documentElement.dataset.theme = mode;
    document.documentElement.style.colorScheme = mode;
    if (save) {
      try { localStorage.setItem(key, mode); } catch {}
      try { document.cookie = key + '=' + mode + '; Path=/; Max-Age=31536000; SameSite=Strict'; } catch {}
    }
    const button = document.getElementById('themeToggle');
    if (button) {
      button.setAttribute('aria-checked', String(mode === 'dark'));
      button.title = mode === 'dark' ? '切换到亮色模式' : '切换到暗色模式';
      button.innerHTML = '<span aria-hidden="true">' + (mode === 'dark' ? '☾' : '☀') + '</span><span class="theme-label">' + (mode === 'dark' ? '暗色' : '亮色') + '</span>';
    }
  }
  apply(read());
  addEventListener('pageshow', () => apply(read()));
  addEventListener('storage', event => { if (event.key === key && valid(event.newValue)) apply(event.newValue); });
  return {apply, read};
})();
