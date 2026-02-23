import { createApp } from 'vue';
import './style.css';
import App from './App.vue';
import router from './router';

const BOOT_ERROR_PANEL_ID = 'filesmind-boot-error-panel';

const renderBootError = (title, detail = '') => {
  if (typeof document === 'undefined') return;
  const appRoot = document.getElementById('app');
  if (!appRoot) return;

  const detailText = String(detail || '').trim();
  appRoot.innerHTML = `
    <div id="${BOOT_ERROR_PANEL_ID}" style="height:100vh;display:flex;align-items:center;justify-content:center;background:#0f172a;color:#e2e8f0;padding:24px;box-sizing:border-box;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;">
      <div style="width:min(720px,95vw);border:1px solid rgba(148,163,184,.35);background:rgba(30,41,59,.9);border-radius:14px;padding:18px 20px;box-shadow:0 12px 36px rgba(2,6,23,.42);">
        <div style="font-size:16px;font-weight:700;line-height:1.5;">${title}</div>
        <div style="margin-top:10px;font-size:13px;line-height:1.65;color:#cbd5e1;white-space:pre-wrap;word-break:break-word;">${detailText || '请重启应用；若仍异常，请清理缓存后再试。'}</div>
        <button id="filesmind-reload-btn" style="margin-top:14px;border:1px solid rgba(96,165,250,.55);background:rgba(30,58,138,.55);color:#dbeafe;border-radius:10px;padding:8px 12px;font-size:12px;font-weight:600;cursor:pointer;">重新加载</button>
      </div>
    </div>
  `;

  const reloadBtn = document.getElementById('filesmind-reload-btn');
  if (reloadBtn) {
    reloadBtn.addEventListener('click', () => {
      window.location.reload();
    });
  }
};

const handlePreloadError = (event) => {
  event.preventDefault();
  const retryKey = 'filesmind.preload-retry-count';
  const tries = Number(sessionStorage.getItem(retryKey) || '0');
  if (tries < 1) {
    sessionStorage.setItem(retryKey, String(tries + 1));
    window.location.reload();
    return;
  }
  renderBootError(
    '应用资源加载失败',
    '检测到静态资源未成功加载。请退出应用后重新打开，或清理 WebKit 缓存目录再试。'
  );
};

if (typeof window !== 'undefined') {
  window.addEventListener('vite:preloadError', handlePreloadError);
}

router.onError((err) => {
  const detail = err?.stack || err?.message || String(err || 'unknown route load error');
  console.error('Router runtime error:', err);
  renderBootError('页面加载失败', detail);
});

try {
  createApp(App).use(router).mount('#app');
} catch (err) {
  const detail = err?.stack || err?.message || String(err || 'bootstrap failed');
  console.error('App bootstrap error:', err);
  renderBootError('应用启动失败', detail);
}
