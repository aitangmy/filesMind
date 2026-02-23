<script setup>
import { ref, nextTick, onMounted, onUnmounted, computed, defineAsyncComponent, watch, defineComponent, h } from 'vue';
import { useRouter } from 'vue-router';
import { apiFetch, buildApiUrl, getApiAuthToken } from './services/apiClient';
import { canUseDesktopPerfBridge, fetchMacosRuntimeState, perfBegin, perfEnd } from './services/macosRuntime';

const props = defineProps({
  routeMode: {
    type: String,
    default: 'workspace'
  }
});

const router = useRouter();
const isSettingsRoute = computed(() => props.routeMode === 'settings');

const loadMindMapComponent = () => import('./components/MindMap.vue');
const loadVirtualPdfViewerComponent = () => import('./components/VirtualPdfViewer.vue');

const createAsyncState = (message, tone = 'info') => defineComponent({
  name: tone === 'error' ? 'AsyncErrorState' : 'AsyncLoadingState',
  setup() {
    const className = tone === 'error'
      ? 'absolute inset-0 flex items-center justify-center bg-rose-50/70 text-rose-600 text-xs'
      : 'absolute inset-0 flex items-center justify-center bg-slate-50/70 text-slate-500 text-xs';
    return () => h('div', { class: className }, message);
  }
});

const createResilientAsyncComponent = (loader, options = {}) => defineAsyncComponent({
  loader,
  delay: 120,
  timeout: 20000,
  loadingComponent: createAsyncState(options.loadingText || 'Loading module...'),
  errorComponent: createAsyncState(options.errorText || 'Module load failed. Please refresh.', 'error'),
  onError(error, retry, fail, attempts) {
    if (attempts <= 2) {
      retry();
      return;
    }
    fail(error);
  }
});

const MindMap = createResilientAsyncComponent(loadMindMapComponent, {
  loadingText: 'Loading mind map...',
  errorText: 'Mind map module failed to load. Please refresh.'
});
const VirtualPdfViewer = createResilientAsyncComponent(loadVirtualPdfViewerComponent, {
  loadingText: 'Loading PDF viewer...',
  errorText: 'PDF viewer failed to load. Please refresh.'
});

let pdfPrefetchPromise = null;
const prefetchPdfViewerAssets = () => {
  if (pdfPrefetchPromise) return pdfPrefetchPromise;
  pdfPrefetchPromise = Promise.all([
    loadVirtualPdfViewerComponent()
  ]).catch((err) => {
    console.warn('PDF assets prefetch failed', err);
  });
  return pdfPrefetchPromise;
};

let xmindPrefetchPromise = null;
const prefetchXmindExportAssets = () => {
  if (xmindPrefetchPromise) return xmindPrefetchPromise;
  xmindPrefetchPromise = Promise.all([
    import('simple-mind-map/src/plugins/Export.js'),
    import('simple-mind-map/src/plugins/ExportXMind.js')
  ]).catch((err) => {
    console.warn('XMind export assets prefetch failed', err);
  });
  return xmindPrefetchPromise;
};

const MASKED_KEY = '***';
const providerOptions = [
  { value: 'minimax', label: 'MiniMax', base_url: 'https://api.minimaxi.com/v1', default_model: 'MiniMax-M2.5' },
  { value: 'deepseek', label: 'DeepSeek (官方)', base_url: 'https://api.deepseek.com', default_model: 'deepseek-chat' },
  { value: 'openai', label: 'OpenAI', base_url: 'https://api.openai.com', default_model: 'gpt-4o' },
  { value: 'anthropic', label: 'Anthropic (Claude)', base_url: 'https://api.anthropic.com', default_model: 'claude-3-5-sonnet-20241022' },
  { value: 'moonshot', label: '月之暗面 (Moonshot)', base_url: 'https://api.moonshot.cn', default_model: 'moonshot-v1-8k' },
  { value: 'dashscope', label: '阿里云 (DashScope)', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1', default_model: 'qwen-max' },
  { value: 'ollama', label: 'Ollama (Local)', base_url: 'http://localhost:11434/v1', default_model: 'qwen2.5:7b' },
  { value: 'custom', label: 'Custom', base_url: '', default_model: '' }
];
const parserBackendOptions = [
  { value: 'docling', label: 'Docling（稳定）' },
  { value: 'marker', label: 'Marker（版面鲁棒）' },
  { value: 'hybrid', label: 'Hybrid（自动择优）' }
];
const hfEndpointRegionOptions = [
  { value: 'global', label: '海外 / 国际网络（huggingface.co）' },
  { value: 'cn', label: '中国大陆（hf-mirror.com）' }
];

const defaultParserConfig = () => ({
  parser_backend: 'docling',
  hybrid_noise_threshold: 0.2,
  hybrid_docling_skip_score: 70,
  hybrid_switch_min_delta: 2,
  hybrid_marker_min_length: 200,
  marker_prefer_api: false,
  hf_endpoint_region: 'global',
  task_timeout_seconds: 600
});

const defaultAdvancedConfig = () => ({
  engine_concurrency: 5,
  engine_temperature: 0.3,
  engine_max_tokens: 8192
});

const fileInput = ref(null);
const isLoading = ref(false);
const errorMsg = ref('');
const DEFAULT_MINDMAP_PLACEHOLDER = '# Welcome to FilesMind\n\n- **Upload a PDF** to generate a Deep Knowledge Map\n- Powered by **IBM Docling** & **LLM Models** & **aitangmy**\n- **Recursive Reasoning** for profound insights';
const mindmapData = ref(DEFAULT_MINDMAP_PLACEHOLDER);
const isMindmapReady = ref(false);

// 侧边栏与布局
const appShellRef = ref(null);
const workspaceLayoutRef = ref(null);
const viewportWidth = ref(typeof window !== 'undefined' ? window.innerWidth : 1440);

const showSidebar = ref(true);
const sidebarWidth = ref(300);
const history = ref([]);
const currentFileId = ref(null);

const pdfPaneWidth = ref(450);
const isPdfResizing = ref(false);
const isSidebarResizing = ref(false);

const clamp = (value, min, max) => Math.min(max, Math.max(min, value));

const updateViewport = () => {
  viewportWidth.value = window.innerWidth;
  const sidebarMax = Math.max(260, Math.min(460, window.innerWidth * 0.42));
  const pdfMax = Math.max(420, window.innerWidth * 0.62);
  sidebarWidth.value = clamp(sidebarWidth.value, 220, sidebarMax);
  pdfPaneWidth.value = clamp(pdfPaneWidth.value, 320, pdfMax);
};

const startSidebarResizing = () => {
  if (!showSidebar.value) return;
  isSidebarResizing.value = true;
  document.body.style.cursor = 'col-resize';
  document.body.style.userSelect = 'none';
  document.addEventListener('mousemove', onSidebarMouseMove);
  document.addEventListener('mouseup', stopSidebarResizing);
};

const onSidebarMouseMove = (event) => {
  if (!isSidebarResizing.value) return;
  const shellRect = appShellRef.value?.getBoundingClientRect();
  if (!shellRect) return;
  const rawWidth = event.clientX - shellRect.left;
  const maxWidth = Math.max(260, Math.min(460, shellRect.width * 0.38));
  sidebarWidth.value = clamp(rawWidth, 220, maxWidth);
};

const stopSidebarResizing = () => {
  isSidebarResizing.value = false;
  document.body.style.cursor = '';
  document.body.style.userSelect = '';
  document.removeEventListener('mousemove', onSidebarMouseMove);
  document.removeEventListener('mouseup', stopSidebarResizing);
};

const startPdfResizing = () => {
  isPdfResizing.value = true;
  document.body.style.cursor = 'col-resize';
  document.body.style.userSelect = 'none';
  document.addEventListener('mousemove', onPdfMouseMove);
  document.addEventListener('mouseup', stopPdfResizing);
};

const onPdfMouseMove = (event) => {
  if (!isPdfResizing.value) return;
  const workspaceRect = workspaceLayoutRef.value?.getBoundingClientRect();
  if (!workspaceRect) return;
  const rawWidth = workspaceRect.right - event.clientX;
  const maxWidth = Math.max(420, workspaceRect.width * 0.58);
  pdfPaneWidth.value = clamp(rawWidth, 320, maxWidth);
};

const stopPdfResizing = () => {
  isPdfResizing.value = false;
  document.body.style.cursor = '';
  document.body.style.userSelect = '';
  document.removeEventListener('mousemove', onPdfMouseMove);
  document.removeEventListener('mouseup', stopPdfResizing);
};

// 导图交互状态
const mindMapRef = ref(null);
const THEME_STORAGE_KEY = 'filesmind.theme';
const isDarkTheme = ref(false);
let prefersDarkMediaQuery = null;

const applyGlobalTheme = (darkEnabled) => {
  if (typeof document === 'undefined') return;
  const root = document.documentElement;
  if (!root) return;
  root.classList.toggle('dark', darkEnabled);
  root.setAttribute('data-theme', darkEnabled ? 'dark' : 'light');
};

const setDarkTheme = (darkEnabled, persist = true) => {
  const next = Boolean(darkEnabled);
  isDarkTheme.value = next;
  applyGlobalTheme(next);
  if (persist) {
    try {
      window.localStorage.setItem(THEME_STORAGE_KEY, next ? 'dark' : 'light');
    } catch {
      // Ignore storage failures.
    }
  }
};

const readStoredTheme = () => {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    if (stored === 'dark') return true;
    if (stored === 'light') return false;
  } catch {
    // Ignore storage failures.
  }
  return null;
};

const syncThemeFromSystemPreference = () => {
  const stored = readStoredTheme();
  if (stored !== null) {
    setDarkTheme(stored, false);
    return;
  }
  const prefersDark = Boolean(prefersDarkMediaQuery?.matches);
  setDarkTheme(prefersDark, false);
};

if (typeof window !== 'undefined') {
  const stored = readStoredTheme();
  if (stored !== null) {
    setDarkTheme(stored, false);
  } else if (typeof window.matchMedia === 'function') {
    setDarkTheme(window.matchMedia('(prefers-color-scheme: dark)').matches, false);
  }
}

const triggerExportPng = () => {
  if (mindMapRef.value?.exportPNG) mindMapRef.value.exportPNG();
};

const triggerExportMd = () => {
  if (mindMapRef.value?.exportMarkdown) mindMapRef.value.exportMarkdown();
};

const triggerExportXmind = () => {
  void prefetchXmindExportAssets();
  if (mindMapRef.value?.exportXMind) mindMapRef.value.exportXMind();
};

const triggerToggleTheme = () => {
  setDarkTheme(!isDarkTheme.value, true);
};

const mindMapZoomPercent = ref(100);

const syncMindMapZoom = async () => {
  await nextTick();
  if (mindMapRef.value?.getZoomPercent) {
    mindMapZoomPercent.value = Number(mindMapRef.value.getZoomPercent()) || 100;
  }
};

const triggerExpandAll = async () => {
  if (!mindMapRef.value?.expandAll) return;
  mindMapRef.value.expandAll();
  await syncMindMapZoom();
};

const triggerCollapseAll = async () => {
  if (!mindMapRef.value?.collapseAll) return;
  mindMapRef.value.collapseAll();
  await syncMindMapZoom();
};

const triggerFitView = async () => {
  if (!mindMapRef.value?.fitView) return;
  mindMapRef.value.fitView();
  await syncMindMapZoom();
};

const triggerZoomIn = async () => {
  if (!mindMapRef.value?.zoomIn) return;
  mindMapRef.value.zoomIn();
  await syncMindMapZoom();
};

const triggerZoomOut = async () => {
  if (!mindMapRef.value?.zoomOut) return;
  mindMapRef.value.zoomOut();
  await syncMindMapZoom();
};

// 拖拽上传状态
const isDraggingFile = ref(false);
const uploadProgress = ref(0);
const isPdfFile = (file) => {
  if (!file) return false;
  const mime = String(file.type || '').toLowerCase();
  const name = String(file.name || '').toLowerCase();
  return mime === 'application/pdf' || name.endsWith('.pdf');
};

const onDragOver = (e) => {
  e.preventDefault();
  isDraggingFile.value = true;
};

const onDragLeave = (e) => {
  e.preventDefault();
  isDraggingFile.value = false;
};

const onDrop = (e) => {
  e.preventDefault();
  isDraggingFile.value = false;
  if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
    const file = e.dataTransfer.files[0];
    if (isPdfFile(file)) {
      void handleSelectedFile(file);
    } else {
      errorMsg.value = "请上传 PDF 文件";
    }
  }
};

const triggerFileInput = () => {
  if (fileInput.value) {
    fileInput.value.click();
  }
};

// 硬件状态
const hardwareType = ref('unknown'); // 'cpu', 'gpu', 'mps'

// 设置弹窗
const showSettings = ref(props.routeMode === 'settings');
const activeSettingsTab = ref('model'); // model | parser | advanced
const configLoading = ref(false);
const configTestResult = ref(null);
const modelFetchResult = ref(null);
const modelLoading = ref(false);
const configImportInput = ref(null);
const configOperationMsg = ref('');
const advancedAutoSaveState = ref('idle'); // idle | saving | saved | error
let advancedAutoSaveTimer = null;
const toasts = ref([]);
const toastTimers = new Map();
let toastSeq = 0;

const openSettingsPage = () => {
  activeSettingsTab.value = 'model';
  showSettings.value = true;
  if (!isSettingsRoute.value) {
    void router.push('/settings');
  }
};

const closeSettings = () => {
  showSettings.value = false;
  if (isSettingsRoute.value) {
    void router.push('/workspace');
  }
};

watch(isSettingsRoute, (value) => {
  showSettings.value = value;
  if (value && !activeSettingsTab.value) {
    activeSettingsTab.value = 'model';
  }
});

const removeToast = (toastId) => {
  const timer = toastTimers.get(toastId);
  if (timer) {
    clearTimeout(timer);
    toastTimers.delete(toastId);
  }
  toasts.value = toasts.value.filter((item) => item.id !== toastId);
};

const notify = (type, message, duration = 4000) => {
  const id = `toast_${Date.now()}_${toastSeq++}`;
  toasts.value.push({ id, type, message });
  if (duration > 0) {
    const timer = setTimeout(() => removeToast(id), duration);
    toastTimers.set(id, timer);
  }
};

const toastTypeClass = (type) => {
  if (type === 'success') return 'bg-emerald-50 border-emerald-200 text-emerald-700';
  if (type === 'warning') return 'bg-amber-50 border-amber-200 text-amber-700';
  if (type === 'error') return 'bg-rose-50 border-rose-200 text-rose-700';
  return 'bg-blue-50 border-blue-200 text-blue-700';
};

// 系统能力标志
const systemFeatures = ref({
  FEATURE_SERVER_PNG_EXPORT: false,
  FEATURE_VIRTUAL_PDF: true,
  FEATURE_SIDECAR_ANCHOR: true
});

// 配置中心（多 profile）
const profiles = ref([]);
const activeProfileId = ref('');
const config = ref({
  id: '',
  name: '',
  provider: 'custom',
  base_url: '',
  model: '',
  api_key: '',
  has_api_key: false,
  account_type: 'free',
  manual_models_text: ''
});
const modelCatalogByProfile = ref({});
const parserConfig = ref(defaultParserConfig());
const advancedConfig = ref(defaultAdvancedConfig());

const isOllamaUrl = (baseUrl) => {
  const lowered = (baseUrl || '').toLowerCase();
  return lowered.includes('ollama') || lowered.includes('11434');
};

const normalizeManualModels = (value) => {
  if (!value) return [];
  return [...new Set(
    String(value)
      .split(/[,\n;]/)
      .map((v) => v.trim())
      .filter(Boolean)
  )].slice(0, 100);
};

const toBoolean = (value, fallback = false) => {
  if (typeof value === 'boolean') return value;
  if (value === null || value === undefined) return fallback;
  const lowered = String(value).trim().toLowerCase();
  if (['1', 'true', 'yes', 'on'].includes(lowered)) return true;
  if (['0', 'false', 'no', 'off'].includes(lowered)) return false;
  return fallback;
};

const ERROR_CODE_HINTS = {
  OK: '配置可用',
  MISSING_PROFILE_NAME: '请填写配置名称',
  PROFILE_NAME_TOO_LONG: '配置名称不应超过 60 个字符',
  MISSING_BASE_URL: '请填写 API Base URL',
  INVALID_BASE_URL: 'API Base URL 需要以 http:// 或 https:// 开头',
  BASE_URL_TOO_LONG: 'API Base URL 过长',
  MISSING_MODEL: '请填写模型名称',
  MODEL_NAME_TOO_LONG: '模型名称过长',
  INVALID_ACCOUNT_TYPE: '账户类型无效',
  INVALID_PROVIDER: '服务商类型无效',
  AUTH_FAILED: '认证失败，请检查 API Key',
  PERMISSION_DENIED: '无权限访问该模型',
  RESOURCE_NOT_FOUND: '模型或接口不存在',
  RATE_LIMITED: '请求过快，请稍后重试',
  NETWORK_TIMEOUT: '网络超时，请检查网络或代理',
  CONNECTION_REFUSED: '连接被拒绝，请确认服务是否启动',
  CONFIG_IMPORT_FAILED: '导入失败，请检查文件内容',
  CONFIG_SAVE_FAILED: '保存失败，请稍后重试',
  INVALID_PARSER_CONFIG: '解析配置格式无效',
  INVALID_PARSER_BACKEND: '解析后端仅支持 docling / marker / hybrid',
  SOURCE_INDEX_REBUILD_FAILED: '历史索引重建失败',
};

const getErrorHint = (code, fallback = '') => ERROR_CODE_HINTS[code] || fallback || '操作失败，请检查配置';

const providerLabel = (provider) => {
  const matched = providerOptions.find((item) => item.value === provider);
  return matched?.label || provider || 'Custom';
};

const nextProviderProfileId = (provider) => {
  const base = `provider_${provider || 'custom'}`;
  if (!profiles.value.some((item) => item.id === base)) return base;
  let i = 2;
  while (profiles.value.some((item) => item.id === `${base}_${i}`)) i += 1;
  return `${base}_${i}`;
};

const createProfile = (overrides = {}) => {
  const provider = overrides.provider || 'deepseek';
  const preset = providerOptions.find((p) => p.value === provider) || {};
  return {
    id: overrides.id || nextProviderProfileId(provider),
    name: overrides.name || providerLabel(provider),
    provider: provider,
    base_url: overrides.base_url ?? preset.base_url ?? '',
    model: overrides.model ?? preset.default_model ?? '',
    api_key: '',
    has_api_key: Boolean(overrides.has_api_key || (overrides.api_key && overrides.api_key !== MASKED_KEY)),
    account_type: overrides.account_type || 'free',
    manual_models_text: (overrides.manual_models || []).join(', ')
  };
};

const activeProfileModels = computed(() => {
  const profileId = config.value.id;
  if (!profileId) return normalizeManualModels(config.value.manual_models_text);
  const remote = modelCatalogByProfile.value[profileId] || [];
  if (remote.length > 0) return remote;
  return normalizeManualModels(config.value.manual_models_text);
});

const requiresApiKey = computed(() => !isOllamaUrl(config.value.base_url));
const hasUsableApiKey = computed(() => !requiresApiKey.value || Boolean(config.value.api_key?.trim() || config.value.has_api_key));
const isHybridParser = computed(() => parserConfig.value.parser_backend === 'hybrid');
const usesMarkerPath = computed(() => ['marker', 'hybrid'].includes(parserConfig.value.parser_backend));

const fieldErrors = computed(() => {
  const errors = {};

  const baseUrl = config.value.base_url?.trim() || '';
  if (!baseUrl) {
    errors.base_url = 'API Base URL 不能为空';
  } else {
    try {
      const parsed = new URL(baseUrl);
      if (!['http:', 'https:'].includes(parsed.protocol)) {
        errors.base_url = 'API Base URL 必须使用 http:// 或 https://';
      }
    } catch {
      errors.base_url = 'API Base URL 格式错误';
    }
    if (baseUrl.length > 200) errors.base_url = 'API Base URL 长度不能超过 200';
  }

  const model = config.value.model?.trim() || '';
  if (!model) errors.model = '模型名称不能为空';
  else if (model.length > 120) errors.model = '模型名称长度不能超过 120';

  if (requiresApiKey.value && !hasUsableApiKey.value) {
    errors.api_key = '当前服务商需要 API Key';
  }

  const manualModels = normalizeManualModels(config.value.manual_models_text);
  if (manualModels.some((item) => item.length > 120)) {
    errors.manual_models = '手动白名单中模型名长度不能超过 120';
  }

  const parserBackend = String(parserConfig.value.parser_backend || '').trim().toLowerCase();
  if (!['docling', 'marker', 'hybrid'].includes(parserBackend)) {
    errors.parser_backend = '解析后端仅支持 docling / marker / hybrid';
  }
  const hfEndpointRegion = String(parserConfig.value.hf_endpoint_region || '').trim().toLowerCase();
  if (!['global', 'cn'].includes(hfEndpointRegion)) {
    errors.hf_endpoint_region = 'HF Endpoint 地区仅支持 global / cn';
  }

  const noiseThreshold = Number(parserConfig.value.hybrid_noise_threshold);
  if (!Number.isFinite(noiseThreshold) || noiseThreshold < 0 || noiseThreshold > 1) {
    errors.hybrid_noise_threshold = '噪声阈值需在 0 到 1 之间';
  }

  const skipScore = Number(parserConfig.value.hybrid_docling_skip_score);
  if (!Number.isFinite(skipScore) || skipScore < 0 || skipScore > 100) {
    errors.hybrid_docling_skip_score = 'Docling 跳过分数需在 0 到 100 之间';
  }

  const switchDelta = Number(parserConfig.value.hybrid_switch_min_delta);
  if (!Number.isFinite(switchDelta) || switchDelta < 0 || switchDelta > 50) {
    errors.hybrid_switch_min_delta = '切换分差阈值需在 0 到 50 之间';
  }

  const markerMinLen = Number(parserConfig.value.hybrid_marker_min_length);
  if (!Number.isInteger(markerMinLen) || markerMinLen < 0 || markerMinLen > 1000000) {
    errors.hybrid_marker_min_length = 'Marker 最小长度需在 0 到 1000000 的整数范围';
  }

  const taskTimeout = Number(parserConfig.value.task_timeout_seconds);
  if (!Number.isInteger(taskTimeout) || taskTimeout < 60 || taskTimeout > 7200) {
    errors.task_timeout_seconds = '任务超时时间需在 60 到 7200 的整数（秒）';
  }

  const engineConcurrency = Number(advancedConfig.value.engine_concurrency);
  if (!Number.isInteger(engineConcurrency) || engineConcurrency < 1 || engineConcurrency > 10) {
    errors.engine_concurrency = '并发限制需在 1 到 10 之间';
  }

  const engineTemp = Number(advancedConfig.value.engine_temperature);
  if (!Number.isFinite(engineTemp) || engineTemp < 0 || engineTemp > 1) {
    errors.engine_temperature = 'AI 思维发散度需在 0 到 1 之间';
  }

  const maxTokens = Number(advancedConfig.value.engine_max_tokens);
  if (!Number.isInteger(maxTokens) || maxTokens < 1000 || maxTokens > 16000) {
    errors.engine_max_tokens = '最大返回长度需在 1000 到 16000 之间';
  }

  return errors;
});

const hasValidationErrors = computed(() => Object.keys(fieldErrors.value).length > 0);
const canTestConfig = computed(() => Boolean(config.value.base_url?.trim() && config.value.model?.trim()) && !Boolean(fieldErrors.value.base_url || fieldErrors.value.model || fieldErrors.value.api_key));
const parserErrorKeys = [
  'parser_backend',
  'hf_endpoint_region',
  'task_timeout_seconds',
  'hybrid_noise_threshold',
  'hybrid_docling_skip_score',
  'hybrid_switch_min_delta',
  'hybrid_marker_min_length'
];
const llmErrorKeys = ['base_url', 'model', 'api_key', 'manual_models'];
const advancedErrorKeys = ['engine_concurrency', 'engine_temperature', 'engine_max_tokens'];
const advancedAutoSaveErrorKeys = ['task_timeout_seconds', ...advancedErrorKeys];

const hasParserValidationErrors = computed(() => parserErrorKeys.some((key) => Boolean(fieldErrors.value[key])));
const hasLlmValidationErrors = computed(() => llmErrorKeys.some((key) => Boolean(fieldErrors.value[key])));
const hasAdvancedValidationErrors = computed(() => advancedErrorKeys.some((key) => Boolean(fieldErrors.value[key])));

const isSettingsSaveDisabled = computed(() => configLoading.value || hasParserValidationErrors.value || hasLlmValidationErrors.value || hasAdvancedValidationErrors.value);

// 检测是否为 MiniMax 2.5 系列模型
const isMiniMax25 = (model) => {
  if (!model) return false;
  const minimaxModels = ['MiniMax-M2.5', 'MiniMax-M2.5-highspeed', 'abab6.5s-chat', 'abab6.5g-chat'];
  return minimaxModels.some(m => model.toLowerCase().includes(m.toLowerCase()));
};

const persistEditorProfile = () => {
  if (!config.value.id) return;
  const idx = profiles.value.findIndex((item) => item.id === config.value.id);
  if (idx === -1) return;
  profiles.value[idx] = {
    ...profiles.value[idx],
    ...config.value,
    manual_models_text: config.value.manual_models_text || ''
  };
};

const loadProfileIntoEditor = (profileId) => {
  const profile = profiles.value.find((item) => item.id === profileId);
  if (!profile) return;
  config.value = { ...profile };
  activeProfileId.value = profileId;
  configTestResult.value = null;
  modelFetchResult.value = null;
};

const clearStoredKey = () => {
  config.value.has_api_key = false;
  config.value.api_key = '';
};

const switchToProviderConfig = (provider) => {
  const targetProvider = String(provider || 'custom').toLowerCase();
  const existing = profiles.value.find((item) => item.provider === targetProvider);
  if (existing) {
    loadProfileIntoEditor(existing.id);
    return;
  }
  const created = createProfile({
    provider: targetProvider,
    name: providerLabel(targetProvider),
  });
  profiles.value.push(created);
  loadProfileIntoEditor(created.id);
};

const onProviderChange = (event) => {
  const provider = String(event?.target?.value || config.value.provider || 'custom').toLowerCase();
  persistEditorProfile();
  switchToProviderConfig(provider);
  modelFetchResult.value = null;
};

const buildConfigStorePayload = ({ persistCurrentProfile = true } = {}) => {
  if (persistCurrentProfile) {
    persistEditorProfile();
  }
  const parser = {
    parser_backend: String(parserConfig.value.parser_backend || 'docling').trim().toLowerCase(),
    hf_endpoint_region: ['global', 'cn'].includes(String(parserConfig.value.hf_endpoint_region || '').trim().toLowerCase())
      ? String(parserConfig.value.hf_endpoint_region).trim().toLowerCase()
      : 'global',
    hybrid_noise_threshold: Number(parserConfig.value.hybrid_noise_threshold ?? 0.2),
    hybrid_docling_skip_score: Number(parserConfig.value.hybrid_docling_skip_score ?? 70),
    hybrid_switch_min_delta: Number(parserConfig.value.hybrid_switch_min_delta ?? 2),
    hybrid_marker_min_length: Number(parserConfig.value.hybrid_marker_min_length ?? 200),
    marker_prefer_api: Boolean(parserConfig.value.marker_prefer_api),
    task_timeout_seconds: Number(parserConfig.value.task_timeout_seconds ?? 600)
  };
  const advanced = {
    engine_concurrency: Number(advancedConfig.value.engine_concurrency ?? 5),
    engine_temperature: Number(advancedConfig.value.engine_temperature ?? 0.3),
    engine_max_tokens: Number(advancedConfig.value.engine_max_tokens ?? 8192)
  };
  return {
    active_profile_id: activeProfileId.value,
    parser,
    advanced,
    profiles: profiles.value.map((item) => ({
      id: item.id,
      name: item.name?.trim() || providerLabel(item.provider),
      provider: item.provider || 'custom',
      base_url: item.base_url?.trim() || '',
      model: item.model?.trim() || '',
      api_key: item.api_key?.trim() ? item.api_key.trim() : (item.has_api_key ? MASKED_KEY : ''),
      account_type: item.account_type || 'free',
      manual_models: normalizeManualModels(item.manual_models_text)
    }))
  };
};

const buildSingleProfilePayload = () => ({
  profile: {
    id: config.value.id,
    name: config.value.name?.trim() || providerLabel(config.value.provider),
    provider: config.value.provider || 'custom',
    base_url: config.value.base_url?.trim() || '',
    model: config.value.model?.trim() || '',
    api_key: config.value.api_key?.trim() ? config.value.api_key.trim() : (config.value.has_api_key ? MASKED_KEY : ''),
    account_type: config.value.account_type || 'free',
    manual_models: normalizeManualModels(config.value.manual_models_text)
  }
});

const parseResponsePayload = async (response) => {
  if (!response) return null;
  if (response.status === 204) return null;
  try {
    const text = await response.text();
    if (!text || !text.trim()) return null;
    try {
      return JSON.parse(text);
    } catch {
      return { message: text.trim() };
    }
  } catch {
    return null;
  }
};

const isEmptyServerErrorResponse = (response, payload) => {
  if (!response || response.status !== 500) return false;
  return payload == null;
};

const backendUnavailableMessage = '后端服务不可用，请确认后端已启动并监听 http://localhost:8000';

const normalizeBackendError = async (response, fallbackMessage) => {
  try {
    const data = await parseResponsePayload(response);
    if (!data) return { code: 'UNKNOWN_ERROR', message: fallbackMessage };
    const detail = data?.detail || data;
    if (typeof detail === 'string') return { code: 'UNKNOWN_ERROR', message: detail };
    return {
      code: detail?.code || data?.code || 'UNKNOWN_ERROR',
      message: detail?.message || data?.message || fallbackMessage,
      field: detail?.field
    };
  } catch {
    return { code: 'UNKNOWN_ERROR', message: fallbackMessage };
  }
};

const exportConfig = async () => {
  persistEditorProfile();
  try {
    const response = await apiFetch('/api/config/export');
    if (!response.ok) {
      const err = await normalizeBackendError(response, '导出配置失败');
      notify('error', `${getErrorHint(err.code, err.message)} (${err.code})`);
      return;
    }
    const data = await response.json();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `filesmind-config-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.json`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    configOperationMsg.value = '配置已导出（不含明文密钥）';
    notify('success', '配置已导出（不含明文密钥）');
  } catch (err) {
    notify('error', `导出配置失败: ${err.message}`);
  }
};

const triggerImportConfig = () => {
  if (configImportInput.value) {
    configImportInput.value.value = '';
    configImportInput.value.click();
  }
};

const importConfigFromFile = async (event) => {
  const file = event.target.files?.[0];
  if (!file) return;
  try {
    const text = await file.text();
    const parsed = JSON.parse(text);
    const payload = {
      active_profile_id: parsed?.active_profile_id || '',
      profiles: Array.isArray(parsed?.profiles) ? parsed.profiles : [],
      parser: parsed?.parser || defaultParserConfig(),
      advanced: parsed?.advanced || defaultAdvancedConfig()
    };
    const response = await apiFetch('/api/config/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!response.ok) {
      const err = await normalizeBackendError(response, '导入配置失败');
      notify('error', `${getErrorHint(err.code, err.message)} (${err.code})`);
      return;
    }
    const result = await response.json();
    await loadConfig();
    configOperationMsg.value = `${result.message || '配置导入成功'}，请检查后保存`;
    notify('success', result.message || '配置导入成功');
  } catch (err) {
    notify('error', `导入配置失败: ${err.message}`);
  }
};

const normalizeConfigStore = (raw) => {
  // 兼容 legacy 单配置格式
  if (!raw?.profiles || !Array.isArray(raw.profiles)) {
    const fallback = createProfile({
      name: 'Default',
      provider: 'deepseek',
      base_url: raw?.base_url || 'https://api.deepseek.com',
      model: raw?.model || 'deepseek-chat',
      api_key: raw?.api_key || '',
      has_api_key: Boolean(raw?.api_key),
      account_type: raw?.account_type || 'free',
      manual_models: []
    });
    return {
      active_profile_id: fallback.id,
      profiles: [fallback],
      parser: defaultParserConfig(),
      advanced: defaultAdvancedConfig()
    };
  }

  const normalizedProfilesRaw = raw.profiles.map((item) => createProfile({
    ...item,
    has_api_key: Boolean(item.has_api_key || item.api_key === MASKED_KEY || item.api_key),
    manual_models: item.manual_models || []
  }));

  const activeRaw = normalizedProfilesRaw.find((item) => item.id === raw.active_profile_id) || normalizedProfilesRaw[0];
  const providerMap = new Map();
  if (activeRaw?.provider) providerMap.set(activeRaw.provider, activeRaw);
  for (const item of normalizedProfilesRaw) {
    if (!providerMap.has(item.provider)) providerMap.set(item.provider, item);
  }
  const normalizedProfiles = Array.from(providerMap.values());
  const active = normalizedProfiles.find((item) => item.provider === activeRaw?.provider) || normalizedProfiles[0];
  const parserRaw = raw?.parser || {};
  const parser = {
    parser_backend: ['docling', 'marker', 'hybrid'].includes(String(parserRaw.parser_backend || '').toLowerCase())
      ? String(parserRaw.parser_backend).toLowerCase()
      : 'docling',
    hf_endpoint_region: ['global', 'cn'].includes(String(parserRaw.hf_endpoint_region || '').toLowerCase())
      ? String(parserRaw.hf_endpoint_region).toLowerCase()
      : 'global',
    hybrid_noise_threshold: Number.isFinite(Number(parserRaw.hybrid_noise_threshold))
      ? Number(parserRaw.hybrid_noise_threshold)
      : 0.2,
    hybrid_docling_skip_score: Number.isFinite(Number(parserRaw.hybrid_docling_skip_score))
      ? Number(parserRaw.hybrid_docling_skip_score)
      : 70,
    hybrid_switch_min_delta: Number.isFinite(Number(parserRaw.hybrid_switch_min_delta))
      ? Number(parserRaw.hybrid_switch_min_delta)
      : 2,
    hybrid_marker_min_length: Number.isInteger(Number(parserRaw.hybrid_marker_min_length))
      ? Number(parserRaw.hybrid_marker_min_length)
      : 200,
    marker_prefer_api: toBoolean(parserRaw.marker_prefer_api, false),
    task_timeout_seconds: Number.isInteger(Number(parserRaw.task_timeout_seconds))
      ? Number(parserRaw.task_timeout_seconds)
      : 600
  };

  const advancedRaw = raw?.advanced || {};
  const advanced = {
    engine_concurrency: Number.isInteger(Number(advancedRaw.engine_concurrency)) ? Number(advancedRaw.engine_concurrency) : 5,
    engine_temperature: Number.isFinite(Number(advancedRaw.engine_temperature)) ? Number(advancedRaw.engine_temperature) : 0.3,
    engine_max_tokens: Number.isInteger(Number(advancedRaw.engine_max_tokens)) ? Number(advancedRaw.engine_max_tokens) : 8192
  };

  return {
    active_profile_id: active?.id || '',
    profiles: normalizedProfiles,
    parser,
    advanced
  };
};

// 轮询相关
const currentTaskId = ref(null);
const pollTimer = ref(null);
const taskStatus = ref('');
const taskProgress = ref(0);
const taskMessage = ref('');
const taskFailureDetails = ref([]);
const showAllFailureDetails = ref(false);
const treeData = ref(null);
const sourceIndexRebuildRunning = ref(false);
const sourceIndexRebuildResult = ref(null);
const sourceIndexRebuildItems = computed(() => {
  const items = sourceIndexRebuildResult.value?.items;
  return Array.isArray(items) ? items : [];
});

const FLAT_NODE_PAGE_SIZE = 1200;
const flatNodes = ref([]);
const flatNodesFileId = ref('');
const flatNodesTotal = ref(0);
const flatNodesNextOffset = ref(0);
const flatNodesHasMore = ref(false);
let flatNodesPageInFlight = null;
let flatNodesPageInFlightFileId = '';
const selectedNode = ref(null);
const sourceView = ref({
  loading: false,
  error: '',
  topic: '',
  lineStart: 0,
  lineEnd: 0,
  parserBackend: 'unknown',
  pdfPageNo: null,
  pdfYRatio: null,
  pdfLoadError: ''
});
const pdfNavigateToken = ref(0);
let sourceRequestToken = 0;

const RUNTIME_MONITOR_ACTIVE_INTERVAL_MS = 5000;
const RUNTIME_MONITOR_IDLE_INTERVAL_MS = 20000;
const RUNTIME_MONITOR_IDLE_LOW_POWER_INTERVAL_MS = 30000;
let runtimeMonitorTimer = null;
let runtimeMonitorEnabled = false;
const runtimeState = ref({
  platform: 'unknown',
  thermalLevel: 'unknown',
  cpuSpeedLimit: null,
  schedulerLimit: null,
  availableCpus: null,
  lowPowerMode: false,
  timestampMs: 0
});
const runtimeHintState = ref({
  signature: '',
  syncedAtMs: 0
});
const desktopPerfSessionToken = ref(0);
let pollInFlight = false;
let runtimeHintInFlight = false;
const thermalPollingProfile = {
  nominal: 1400,
  fair: 1800,
  serious: 2400,
  critical: 3200,
  unknown: 1700
};
const thermalPdfProfile = {
  nominal: { preloadMaxPages: 1500, preloadConcurrency: 2 },
  fair: { preloadMaxPages: 900, preloadConcurrency: 2 },
  serious: { preloadMaxPages: 420, preloadConcurrency: 1 },
  critical: { preloadMaxPages: 180, preloadConcurrency: 1 },
  unknown: { preloadMaxPages: 800, preloadConcurrency: 2 }
};
const thermalPdfWindowProfile = {
  nominal: { maxMountedPages: 8, bufferPages: 2 },
  fair: { maxMountedPages: 7, bufferPages: 2 },
  serious: { maxMountedPages: 5, bufferPages: 1 },
  critical: { maxMountedPages: 4, bufferPages: 1 },
  unknown: { maxMountedPages: 6, bufferPages: 1 }
};
const pollCadenceState = ref({
  stagnantTicks: 0,
  lastProgress: -1,
  lastStatus: ''
});

const normalizeThermalLevel = (value) => {
  const level = String(value || '').trim().toLowerCase();
  if (level === 'nominal' || level === 'fair' || level === 'serious' || level === 'critical') {
    return level;
  }
  return 'unknown';
};

const applyRuntimeSnapshot = (snapshot) => {
  if (!snapshot || typeof snapshot !== 'object') return;
  const thermalRaw = snapshot.thermalLevel ?? snapshot.thermal_level;
  const thermalLevel = thermalRaw ? normalizeThermalLevel(thermalRaw) : runtimeState.value.thermalLevel;
  const lowPowerRaw = snapshot.lowPowerMode ?? snapshot.low_power_mode;
  runtimeState.value = {
    platform: String(snapshot.platform || runtimeState.value.platform || 'unknown'),
    thermalLevel,
    cpuSpeedLimit: Number.isFinite(Number(snapshot.cpuSpeedLimit ?? snapshot.cpu_speed_limit))
      ? Number(snapshot.cpuSpeedLimit ?? snapshot.cpu_speed_limit)
      : runtimeState.value.cpuSpeedLimit,
    schedulerLimit: Number.isFinite(Number(snapshot.schedulerLimit ?? snapshot.scheduler_limit))
      ? Number(snapshot.schedulerLimit ?? snapshot.scheduler_limit)
      : runtimeState.value.schedulerLimit,
    availableCpus: Number.isFinite(Number(snapshot.availableCpus ?? snapshot.available_cpus))
      ? Number(snapshot.availableCpus ?? snapshot.available_cpus)
      : runtimeState.value.availableCpus,
    lowPowerMode: lowPowerRaw === undefined ? runtimeState.value.lowPowerMode : Boolean(lowPowerRaw),
    timestampMs: Number(snapshot.timestampMs ?? snapshot.timestamp_ms) || Date.now()
  };
};

const toIntOrNull = (value) => {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return null;
  return Math.trunc(parsed);
};

const buildRuntimeHintPayload = () => ({
  platform: String(runtimeState.value.platform || 'unknown').trim().toLowerCase() || 'unknown',
  thermal_level: normalizeThermalLevel(runtimeState.value.thermalLevel),
  cpu_speed_limit: toIntOrNull(runtimeState.value.cpuSpeedLimit),
  scheduler_limit: toIntOrNull(runtimeState.value.schedulerLimit),
  available_cpus: toIntOrNull(runtimeState.value.availableCpus),
  low_power_mode: Boolean(runtimeState.value.lowPowerMode),
  source: 'tauri_runtime_bridge',
  timestamp_ms: toIntOrNull(runtimeState.value.timestampMs) || Date.now()
});

const runtimeHintSignature = (payload) => JSON.stringify([
  payload.platform,
  payload.thermal_level,
  payload.cpu_speed_limit,
  payload.scheduler_limit,
  payload.available_cpus,
  payload.low_power_mode
]);

const syncRuntimeHintToBackend = async ({ force = false } = {}) => {
  if (!canUseDesktopPerfBridge()) return;
  const payload = buildRuntimeHintPayload();
  const signature = runtimeHintSignature(payload);
  if (!force && signature === runtimeHintState.value.signature) {
    return;
  }
  if (runtimeHintInFlight) return;

  runtimeHintInFlight = true;
  try {
    const response = await apiFetch('/api/runtime/hint', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (response.ok) {
      runtimeHintState.value = {
        signature,
        syncedAtMs: Date.now()
      };
    } else {
      console.warn('runtime hint sync failed:', response.status);
    }
  } catch (error) {
    console.warn('runtime hint sync error:', error);
  } finally {
    runtimeHintInFlight = false;
  }
};

const refreshRuntimeState = async () => {
  if (!canUseDesktopPerfBridge()) return;
  const snapshot = await fetchMacosRuntimeState();
  applyRuntimeSnapshot(snapshot);
  await syncRuntimeHintToBackend();
};

const scheduleRuntimeMonitor = () => {
  if (!runtimeMonitorEnabled) return;
  if (runtimeMonitorTimer) {
    clearTimeout(runtimeMonitorTimer);
    runtimeMonitorTimer = null;
  }
  runtimeMonitorTimer = setTimeout(async () => {
    runtimeMonitorTimer = null;
    if (!runtimeMonitorEnabled) return;
    await refreshRuntimeState();
    scheduleRuntimeMonitor();
  }, runtimeMonitorIntervalMs.value);
};

const beginDesktopPerfSession = async (reason = 'document-processing') => {
  if (!canUseDesktopPerfBridge()) return;
  if (Number(desktopPerfSessionToken.value) > 0) return;
  const payload = await perfBegin(reason);
  const token = Number(payload?.token || 0);
  if (payload?.active && Number.isFinite(token) && token > 0) {
    desktopPerfSessionToken.value = token;
  }
  applyRuntimeSnapshot(payload);
  await refreshRuntimeState();
};

const endDesktopPerfSession = async () => {
  if (!canUseDesktopPerfBridge()) return;
  const token = Number(desktopPerfSessionToken.value || 0);
  if (!Number.isFinite(token) || token <= 0) return;
  desktopPerfSessionToken.value = 0;
  const payload = await perfEnd(token);
  applyRuntimeSnapshot(payload);
  await refreshRuntimeState();
};

watch(isLoading, (loading) => {
  if (loading) {
    void beginDesktopPerfSession('document-processing');
    return;
  }
  void endDesktopPerfSession();
});

const taskPollIntervalMs = computed(() => {
  const level = normalizeThermalLevel(runtimeState.value.thermalLevel);
  let interval = thermalPollingProfile[level] || thermalPollingProfile.unknown;
  if (runtimeState.value.lowPowerMode) {
    interval = Math.round(interval * 1.25);
  }
  return Math.max(900, Math.min(4500, interval));
});

const pdfRuntimeProfile = computed(() => {
  const level = normalizeThermalLevel(runtimeState.value.thermalLevel);
  const profile = thermalPdfProfile[level] || thermalPdfProfile.unknown;
  let preloadMaxPages = profile.preloadMaxPages;
  let preloadConcurrency = profile.preloadConcurrency;
  if (runtimeState.value.lowPowerMode) {
    preloadMaxPages = Math.max(120, Math.round(preloadMaxPages * 0.7));
    preloadConcurrency = Math.max(1, preloadConcurrency - 1);
  }
  return { preloadMaxPages, preloadConcurrency };
});
const pdfPreloadMaxPages = computed(() => pdfRuntimeProfile.value.preloadMaxPages);
const pdfPreloadConcurrency = computed(() => pdfRuntimeProfile.value.preloadConcurrency);
const pdfWindowRuntimeProfile = computed(() => {
  const level = normalizeThermalLevel(runtimeState.value.thermalLevel);
  const profile = thermalPdfWindowProfile[level] || thermalPdfWindowProfile.unknown;
  let maxMountedPages = profile.maxMountedPages;
  const bufferPages = profile.bufferPages;
  if (runtimeState.value.lowPowerMode) {
    maxMountedPages = Math.max(3, maxMountedPages - 1);
  }
  return { maxMountedPages, bufferPages };
});
const pdfMaxMountedPages = computed(() => pdfWindowRuntimeProfile.value.maxMountedPages);
const pdfBufferPages = computed(() => pdfWindowRuntimeProfile.value.bufferPages);

const resetPollCadence = () => {
  pollCadenceState.value = {
    stagnantTicks: 0,
    lastProgress: -1,
    lastStatus: ''
  };
};

const updatePollCadence = (statusValue, progressValue, forceStagnant = false) => {
  const normalizedStatus = String(statusValue || '').trim().toLowerCase();
  const parsedProgress = Number(progressValue);
  const nextProgress = Number.isFinite(parsedProgress)
    ? Math.max(0, Math.min(100, parsedProgress))
    : pollCadenceState.value.lastProgress;
  const previous = pollCadenceState.value;
  const activeStatuses = ['pending', 'processing', 'uploading'];

  if (!activeStatuses.includes(normalizedStatus)) {
    resetPollCadence();
    return;
  }

  const statusChanged = normalizedStatus !== previous.lastStatus;
  const progressAdvanced = Number.isFinite(nextProgress) && nextProgress > (previous.lastProgress + 0.15);
  const shouldResetStagnation = statusChanged || progressAdvanced;

  let stagnantTicks = shouldResetStagnation ? 0 : previous.stagnantTicks;
  if (!shouldResetStagnation && (forceStagnant || normalizedStatus === 'processing')) {
    stagnantTicks = Math.min(12, previous.stagnantTicks + 1);
  }

  pollCadenceState.value = {
    stagnantTicks,
    lastProgress: nextProgress,
    lastStatus: normalizedStatus
  };
};

const resolveAdaptivePollDelayMs = () => {
  const base = taskPollIntervalMs.value;
  const status = String(taskStatus.value || '').trim().toLowerCase();
  if (isUploadStage.value || status === 'uploading') {
    return Math.max(900, Math.min(1600, base));
  }
  if (!status || !['pending', 'processing'].includes(status)) {
    return base;
  }

  const stagnantBoost = 1 + Math.min(6, pollCadenceState.value.stagnantTicks) * 0.18;
  const lowPowerBoost = runtimeState.value.lowPowerMode ? 1.15 : 1;
  const raw = base * stagnantBoost * lowPowerBoost;
  return Math.max(900, Math.min(6500, Math.round(raw)));
};

let pollStartTime = 0;
const isUploadStage = computed(() => {
  if (!isLoading.value) return false;
  if (currentTaskId.value) return false;
  return ['pending', 'uploading'].includes(String(taskStatus.value || '').toLowerCase());
});
const runtimeMonitorIntervalMs = computed(() => {
  if (isLoading.value || currentTaskId.value) {
    return RUNTIME_MONITOR_ACTIVE_INTERVAL_MS;
  }
  if (runtimeState.value.lowPowerMode) {
    return RUNTIME_MONITOR_IDLE_LOW_POWER_INTERVAL_MS;
  }
  return RUNTIME_MONITOR_IDLE_INTERVAL_MS;
});

const chunkProgress = computed(() => {
  const text = String(taskMessage.value || '');
  const match = text.match(/(?:章节|chunk)\s*(\d+)\s*\/\s*(\d+)/i);
  if (!match) return { completed: 0, total: 0 };
  const completed = Number(match[1] || 0);
  const total = Number(match[2] || 0);
  return {
    completed: Number.isFinite(completed) ? Math.max(0, completed) : 0,
    total: Number.isFinite(total) ? Math.max(0, total) : 0
  };
});

const skeletonBranchTotal = computed(() => {
  const total = Number(chunkProgress.value.total || 0);
  if (total > 0) return Math.max(6, Math.min(16, total));
  return 10;
});

const skeletonBranchActive = computed(() => {
  const branchTotal = skeletonBranchTotal.value;
  if (chunkProgress.value.total > 0) {
    const ratio = chunkProgress.value.completed / chunkProgress.value.total;
    return Math.max(1, Math.min(branchTotal, Math.round(ratio * branchTotal)));
  }
  const fallbackProgress = isUploadStage.value ? Number(uploadProgress.value || 0) : Number(taskProgress.value || 0);
  return Math.max(1, Math.min(branchTotal, Math.round((fallbackProgress / 100) * branchTotal)));
});

const skeletonBranches = computed(() => Array.from({ length: skeletonBranchTotal.value }, (_, idx) => ({
  index: idx,
  side: idx % 2 === 0 ? 'left' : 'right',
  active: idx < skeletonBranchActive.value
})));

const effectiveTaskProgress = computed(() => {
  if (isUploadStage.value) {
    const p = Number(uploadProgress.value) || 0;
    return Math.max(3, Math.min(99, p));
  }
  const p = Number(taskProgress.value) || 0;
  return Math.max(0, Math.min(100, p));
});
const pollTimeoutMs = computed(() => {
  const seconds = Number(parserConfig.value.task_timeout_seconds ?? 600);
  if (!Number.isInteger(seconds) || seconds < 60 || seconds > 7200) {
    return 600000;
  }
  return seconds * 1000;
});
const isTabletViewport = computed(() => viewportWidth.value >= 768 && viewportWidth.value <= 1024);
const showDetailPane = computed(() => viewportWidth.value > 1024);
const showMindmapCanvas = computed(() => Boolean(currentFileId.value) && isMindmapReady.value);
const showMindmapToolbar = computed(() => showMindmapCanvas.value && !isLoading.value);
const currentPdfSourceUrl = computed(() => {
  if (!currentFileId.value) return '';
  return buildApiUrl(`/api/file/${currentFileId.value}/pdf`);
});
const canUseVirtualPdf = computed(() => Boolean(systemFeatures.value?.FEATURE_VIRTUAL_PDF));
const showPdfViewer = computed(() => canUseVirtualPdf.value && Boolean(currentPdfSourceUrl.value));
const workspaceGridStyle = computed(() => {
  if (!showDetailPane.value) {
    return { gridTemplateColumns: 'minmax(0, 1fr)' };
  }
  return {
    gridTemplateColumns: `minmax(0, 1fr) 0.625rem minmax(320px, ${pdfPaneWidth.value}px)`
  };
});
const topNoticeVisible = computed(() => isLoading.value || Boolean(errorMsg.value));
const hasTaskFailureDetails = computed(() => Array.isArray(taskFailureDetails.value) && taskFailureDetails.value.length > 0);
const taskFailureDetailCount = computed(() => (hasTaskFailureDetails.value ? taskFailureDetails.value.length : 0));
const visibleTaskFailureDetails = computed(() => {
  const list = hasTaskFailureDetails.value ? taskFailureDetails.value : [];
  if (showAllFailureDetails.value) return list;
  return list.slice(0, 6);
});

const normalizeFailureDetails = (input) => {
  if (!Array.isArray(input)) return [];
  return input
    .map((item) => ({
      nodeId: String(item?.node_id || item?.nodeId || '').trim(),
      topic: String(item?.topic || '').trim(),
      error: String(item?.error || '').trim()
    }))
    .filter((item) => item.topic || item.nodeId || item.error);
};

watch(showPdfViewer, (visible) => {
  if (visible) {
    void prefetchPdfViewerAssets();
  }
});

// 加载历史记录
const loadHistory = async () => {
  try {
    const response = await apiFetch('/api/history');
    if (response.ok) {
      history.value = await response.json();
    }
  } catch (err) {
    console.error('加载历史失败:', err);
  }
};

const resetSourceView = () => {
  sourceRequestToken += 1;
  pdfNavigateToken.value = 0;
  selectedNode.value = null;
  sourceView.value = {
    loading: false,
    error: '',
    topic: '',
    lineStart: 0,
    lineEnd: 0,
    parserBackend: 'unknown',
    pdfPageNo: null,
    pdfYRatio: null,
    pdfLoadError: ''
  };
};

const resetFlatNodesCache = (fileId = '') => {
  flatNodes.value = [];
  flatNodesFileId.value = String(fileId || '').trim();
  flatNodesTotal.value = 0;
  flatNodesNextOffset.value = 0;
  flatNodesHasMore.value = false;
};

const buildTreeRequestPath = (
  fileId,
  {
    includeTree = true,
    includeFlatNodes = false,
    flatOffset = 0,
    flatLimit = null
  } = {}
) => {
  const params = new URLSearchParams();
  params.set('include_tree', includeTree ? 'true' : 'false');
  params.set('include_flat_nodes', includeFlatNodes ? 'true' : 'false');
  params.set('flat_offset', String(Math.max(0, Number(flatOffset) || 0)));
  const parsedLimit = Number(flatLimit);
  if (includeFlatNodes && Number.isFinite(parsedLimit) && parsedLimit > 0) {
    params.set('flat_limit', String(Math.trunc(parsedLimit)));
  }
  return `/api/file/${fileId}/tree?${params.toString()}`;
};

const mergeFlatNodePage = (incomingNodes, { replace = false } = {}) => {
  const source = Array.isArray(incomingNodes) ? incomingNodes : [];
  if (replace) {
    flatNodes.value = source;
    return;
  }
  if (!source.length) return;
  const existing = Array.isArray(flatNodes.value) ? flatNodes.value : [];
  const seenIds = new Set(
    existing
      .map((node) => String(node?.node_id || '').trim())
      .filter(Boolean)
  );
  const merged = [...existing];
  for (const node of source) {
    if (!node || typeof node !== 'object') continue;
    const nodeId = String(node.node_id || '').trim();
    if (nodeId && seenIds.has(nodeId)) continue;
    if (nodeId) seenIds.add(nodeId);
    merged.push(node);
  }
  flatNodes.value = merged;
};

const loadTreeForFile = async (fileId, { includeFlatNodes = false } = {}) => {
  const normalizedFileId = String(fileId || '').trim();
  if (!normalizedFileId) {
    treeData.value = null;
    resetFlatNodesCache('');
    return;
  }
  try {
    const response = await apiFetch(
      buildTreeRequestPath(normalizedFileId, {
        includeTree: true,
        includeFlatNodes,
        flatOffset: 0,
        flatLimit: includeFlatNodes ? FLAT_NODE_PAGE_SIZE : null
      })
    );
    if (!response.ok) {
      throw new Error('无法加载节点索引');
    }
    const data = await response.json();
    treeData.value = data.tree || null;

    const total = Math.max(0, Number(data.flat_nodes_total) || 0);
    flatNodesFileId.value = normalizedFileId;
    flatNodesTotal.value = total;

    if (includeFlatNodes) {
      const pageNodes = Array.isArray(data.flat_nodes) ? data.flat_nodes : [];
      mergeFlatNodePage(pageNodes, { replace: true });
      const responseOffset = Math.max(0, Number(data.flat_nodes_offset) || 0);
      flatNodesNextOffset.value = responseOffset + pageNodes.length;
      flatNodesHasMore.value = Boolean(data.flat_nodes_has_more);
    } else {
      flatNodes.value = [];
      flatNodesNextOffset.value = 0;
      flatNodesHasMore.value = total > 0;
    }
  } catch (err) {
    treeData.value = null;
    resetFlatNodesCache(normalizedFileId);
    console.error('加载节点树失败:', err);
  }
};

const loadNextFlatNodesPage = async (fileId) => {
  const normalizedFileId = String(fileId || '').trim();
  if (!normalizedFileId) return [];

  if (flatNodesFileId.value !== normalizedFileId) {
    resetFlatNodesCache(normalizedFileId);
    flatNodesHasMore.value = true;
  }

  if (!flatNodesHasMore.value && flatNodes.value.length >= flatNodesTotal.value) {
    return [];
  }

  if (flatNodesPageInFlight && flatNodesPageInFlightFileId !== normalizedFileId) {
    try {
      await flatNodesPageInFlight;
    } catch (_err) {
      // Swallow previous file's paging error and continue with current file.
    }
  }

  if (flatNodesPageInFlight && flatNodesPageInFlightFileId === normalizedFileId) {
    return flatNodesPageInFlight;
  }

  flatNodesPageInFlightFileId = normalizedFileId;
  flatNodesPageInFlight = (async () => {
    const offset = Math.max(0, Number(flatNodesNextOffset.value) || 0);
    const response = await apiFetch(
      buildTreeRequestPath(normalizedFileId, {
        includeTree: false,
        includeFlatNodes: true,
        flatOffset: offset,
        flatLimit: FLAT_NODE_PAGE_SIZE
      })
    );
    if (!response.ok) {
      throw new Error('无法加载节点索引分页数据');
    }
    const data = await response.json();
    const pageNodes = Array.isArray(data.flat_nodes) ? data.flat_nodes : [];
    const responseOffset = Math.max(0, Number(data.flat_nodes_offset) || offset);
    flatNodesFileId.value = normalizedFileId;
    flatNodesTotal.value = Math.max(0, Number(data.flat_nodes_total) || 0);
    flatNodesNextOffset.value = responseOffset + pageNodes.length;
    flatNodesHasMore.value = Boolean(data.flat_nodes_has_more);
    mergeFlatNodePage(pageNodes, { replace: responseOffset === 0 && offset === 0 });
    return pageNodes;
  })();

  try {
    return await flatNodesPageInFlight;
  } finally {
    if (flatNodesPageInFlightFileId === normalizedFileId) {
      flatNodesPageInFlight = null;
      flatNodesPageInFlightFileId = '';
    }
  }
};

const loadNodeSource = async (nodeId) => {
  if (!currentFileId.value || !nodeId) return;
  const requestToken = ++sourceRequestToken;
  const requestedFileId = currentFileId.value;
  sourceView.value.loading = true;
  sourceView.value.error = '';
  sourceView.value.pdfLoadError = '';
  try {
    const response = await apiFetch(`/api/file/${requestedFileId}/node/${nodeId}/source`);
    if (!response.ok) {
      throw new Error('节点原文加载失败');
    }
    const data = await response.json();
    if (requestToken !== sourceRequestToken || currentFileId.value !== requestedFileId) {
      return;
    }
    sourceView.value = {
      loading: false,
      error: '',
      topic: data.topic || '',
      lineStart: data.line_start || 0,
      lineEnd: data.line_end || 0,
      parserBackend: data.capabilities?.parser_backend ?? 'unknown',
      pdfPageNo: Number.isInteger(Number(data.pdf_page_no)) ? Number(data.pdf_page_no) : null,
      pdfYRatio: Number.isFinite(Number(data.pdf_y_ratio)) ? Number(data.pdf_y_ratio) : null,
      pdfLoadError: ''
    };
    pdfNavigateToken.value += 1;
  } catch (err) {
    if (requestToken !== sourceRequestToken || currentFileId.value !== requestedFileId) {
      return;
    }
    sourceView.value.loading = false;
    sourceView.value.error = err.message || '节点原文加载失败';
  }
};

const handleMindmapNodeClick = async (payload) => {
  if (!payload?.nodeId) {
    pdfNavigateToken.value = 0;
    selectedNode.value = payload || null;
    sourceView.value = {
      loading: false,
      error: '',
      topic: payload?.topic || '',
      lineStart: Number(payload?.sourceLineStart || 0),
      lineEnd: Number(payload?.sourceLineEnd || payload?.sourceLineStart || 0),
      parserBackend: sourceView.value.parserBackend || 'unknown',
      pdfPageNo: null,
      pdfYRatio: null,
      pdfLoadError: ''
    };
    return;
  }
  selectedNode.value = payload;
  await loadNodeSource(payload.nodeId);
};

const handlePdfViewerLoaded = () => {
  if (sourceView.value.pdfLoadError) {
    sourceView.value.pdfLoadError = '';
  }
};

const handlePdfViewerError = (payload) => {
  const message = payload?.message || 'PDF 渲染失败';
  sourceView.value.pdfLoadError = message;
};

const handleMindmapFeedback = (payload) => {
  const message = payload?.message || '操作失败，请重试';
  const type = payload?.type || 'info';
  notify(type, message);
};

const handleMindmapZoomChange = (payload) => {
  const zoom = Number(payload?.zoomPercent);
  if (Number.isFinite(zoom) && zoom > 0) {
    mindMapZoomPercent.value = Math.round(zoom);
  }
};

const clearTaskErrorNotice = () => {
  errorMsg.value = '';
  taskFailureDetails.value = [];
  showAllFailureDetails.value = false;
};

const matchFailedNodeFromCandidates = (candidates, item) => {
  const list = Array.isArray(candidates) ? candidates : [];
  if (!list.length) return null;

  const targetNodeId = String(item?.nodeId || '').trim();
  if (targetNodeId) {
    const byId = list.find((node) => String(node?.node_id || '').trim() === targetNodeId);
    if (byId) return byId;
  }

  const targetTopic = String(item?.topic || '').trim().toLowerCase();
  if (!targetTopic) return null;
  return (
    list.find((node) => String(node?.topic || '').trim().toLowerCase() === targetTopic) ||
    null
  );
};

const locateFailedNode = async (item) => {
  const fileId = String(currentFileId.value || '').trim();
  if (!fileId) {
    notify('warning', 'Current file context is missing');
    return;
  }

  let matched = matchFailedNodeFromCandidates(flatNodes.value, item);
  while (!matched && (flatNodesHasMore.value || flatNodesFileId.value !== fileId)) {
    try {
      const page = await loadNextFlatNodesPage(fileId);
      if (!Array.isArray(page) || !page.length) {
        break;
      }
      matched = matchFailedNodeFromCandidates(page, item) || matchFailedNodeFromCandidates(flatNodes.value, item);
    } catch (err) {
      console.error('加载节点索引分页失败:', err);
      notify('warning', 'Failed to load node index page');
      return;
    }
  }

  if (!matched) {
    notify('warning', 'Failed node is not available in current tree index');
    return;
  }

  await handleMindmapNodeClick({
    nodeId: matched.node_id || '',
    topic: matched.topic || item?.topic || '',
    level: Number(matched.level || 0),
    sourceLineStart: Number(matched.source_line_start || 0),
    sourceLineEnd: Number(matched.source_line_end || 0)
  });

  await nextTick();
  if (mindMapRef.value?.focusNode) {
    const focused = await mindMapRef.value.focusNode(
      String(matched.node_id || item?.nodeId || ''),
      String(matched.topic || item?.topic || '')
    );
    if (!focused) {
      notify('warning', 'Node located in details pane, but visual focus in mind map failed');
    }
  }
};

// 加载文件内容
const loadFile = async (fileId) => {
  try {
    resetSourceView();
    taskFailureDetails.value = [];
    showAllFailureDetails.value = false;
    const response = await apiFetch(`/api/file/${fileId}?format=raw`);
    if (!response.ok) {
      throw new Error('文件加载失败');
    }
    const contentType = String(response.headers.get('content-type') || '').toLowerCase();
    if (contentType.includes('application/json')) {
      const data = await response.json();
      mindmapData.value = data.content || '';
    } else {
      mindmapData.value = await response.text();
    }
    isMindmapReady.value = true;
    currentFileId.value = fileId;
    await loadTreeForFile(fileId);
    await syncMindMapZoom();
    isLoading.value = false;
  } catch (err) {
    errorMsg.value = err.message;
    console.error('加载文件失败:', err);
  }
};

// 删除文件
const deleteFile = async (fileId, event) => {
  event.stopPropagation();
  if (!confirm('Are you sure you want to delete this file?')) return;
  
  try {
    const response = await apiFetch(`/api/file/${fileId}`, {
      method: 'DELETE'
    });
    if (response.ok) {
      await loadHistory();
      if (currentFileId.value === fileId) {
        mindmapData.value = DEFAULT_MINDMAP_PLACEHOLDER;
        isMindmapReady.value = false;
        currentFileId.value = null;
        treeData.value = null;
        resetFlatNodesCache('');
        resetSourceView();
      }
    }
  } catch (err) {
    console.error('删除失败:', err);
  }
};

// 清理轮询
const cleanupPoll = () => {
  if (pollTimer.value) {
    clearTimeout(pollTimer.value);
    pollTimer.value = null;
  }
  pollInFlight = false;
  currentTaskId.value = null;
  pollStartTime = 0;
  resetPollCadence();
};

const scheduleNextPoll = (delayMs = resolveAdaptivePollDelayMs()) => {
  if (!currentTaskId.value) return;
  if (pollTimer.value) {
    clearTimeout(pollTimer.value);
    pollTimer.value = null;
  }
  const resolvedDelay = Math.max(600, Number(delayMs) || 0);
  pollTimer.value = setTimeout(() => {
    pollTimer.value = null;
    void runPollTick();
  }, resolvedDelay);
};

const runPollTick = async () => {
  if (!currentTaskId.value) return;
  if (pollInFlight) {
    scheduleNextPoll(resolveAdaptivePollDelayMs());
    return;
  }
  pollInFlight = true;
  try {
    await checkPollTimeout();
    if (currentTaskId.value) {
      await pollTaskStatus(currentFileId.value, currentTaskId.value);
    }
  } finally {
    pollInFlight = false;
    if (currentTaskId.value) {
      scheduleNextPoll(resolveAdaptivePollDelayMs());
    }
  }
};

const startTaskPolling = (docId, taskId, message = '') => {
  if (!taskId) return;
  if (pollTimer.value) {
    clearTimeout(pollTimer.value);
    pollTimer.value = null;
  }
  currentTaskId.value = taskId;
  if (docId) {
    currentFileId.value = docId;
  }
  pollStartTime = Date.now();
  resetPollCadence();
  updatePollCadence('processing', 0, false);
  if (message) {
    taskMessage.value = message;
  }
  void runPollTick();
};

watch(taskPollIntervalMs, () => {
  if (!currentTaskId.value || pollInFlight) return;
  scheduleNextPoll(Math.min(resolveAdaptivePollDelayMs(), 900));
});

watch(runtimeMonitorIntervalMs, () => {
  if (!runtimeMonitorEnabled) return;
  scheduleRuntimeMonitor();
});

onUnmounted(() => {
  cleanupPoll();
  runtimeMonitorEnabled = false;
  if (runtimeMonitorTimer) {
    clearTimeout(runtimeMonitorTimer);
    runtimeMonitorTimer = null;
  }
  void endDesktopPerfSession();
  if (advancedAutoSaveTimer) {
    clearTimeout(advancedAutoSaveTimer);
    advancedAutoSaveTimer = null;
  }
  if (prefersDarkMediaQuery?.removeEventListener) {
    prefersDarkMediaQuery.removeEventListener('change', syncThemeFromSystemPreference);
  } else if (prefersDarkMediaQuery?.removeListener) {
    prefersDarkMediaQuery.removeListener(syncThemeFromSystemPreference);
  }
  prefersDarkMediaQuery = null;
  stopPdfResizing();
  stopSidebarResizing();
  window.removeEventListener('resize', updateViewport);
  for (const timer of toastTimers.values()) {
    clearTimeout(timer);
  }
  toastTimers.clear();
});

// 轮询任务状态
const pollTaskStatus = async (docId, taskId = '') => {
  if (!docId && !taskId) return;
  try {
    const response = docId
      ? await apiFetch(`/api/documents/${docId}/status`)
      : await apiFetch(`/api/task/${taskId}`);

    if (response.status === 404) {
      cleanupPoll();
      isLoading.value = false;
      errorMsg.value = 'Task status not found';
      await loadHistory();
      return;
    }

    if (!response.ok) {
      throw new Error(`Status check failed: ${response.statusText}`);
    }

    const data = await response.json();

    taskStatus.value = data.status;
    taskProgress.value = data.progress;
    taskMessage.value = data.message;
    taskFailureDetails.value = normalizeFailureDetails(data.failure_details);
    updatePollCadence(data.status, data.progress);

    if (data.status === 'completed' || data.status === 'completed_with_gaps') {
      cleanupPoll();
      taskFailureDetails.value = [];
      showAllFailureDetails.value = false;
      const resolvedFileId = data.doc_id || data.file_id || docId || currentFileId.value;
      if (resolvedFileId) {
        currentFileId.value = resolvedFileId;
        await loadFile(resolvedFileId);
      } else if (data.result) {
        mindmapData.value = data.result;
        isMindmapReady.value = true;
      }
      await syncMindMapZoom();
      isLoading.value = false;
      uploadProgress.value = 0;
      if (fileInput.value) fileInput.value.value = '';
      await loadHistory();
    } else if (data.status === 'failed') {
      cleanupPoll();
      isMindmapReady.value = false;
      errorMsg.value = data.error || 'Processing failed';
      showAllFailureDetails.value = false;
      isLoading.value = false;
      uploadProgress.value = 0;
      await loadHistory();
    } else if (data.status === 'cancelled') {
      cleanupPoll();
      isMindmapReady.value = false;
      errorMsg.value = data.message || 'Task cancelled';
      taskFailureDetails.value = [];
      showAllFailureDetails.value = false;
      isLoading.value = false;
      uploadProgress.value = 0;
      await loadHistory();
    }

  } catch (err) {
    updatePollCadence(taskStatus.value || 'processing', taskProgress.value || 0, true);
    console.error('Poll error:', err);
  }
};

const requestTaskCancel = async (taskId, reason = 'manual cancel', docId = null) => {
  if (!taskId && !docId) return;
  try {
    const endpoint = docId ? `/api/documents/${docId}/cancel` : `/api/task/${taskId}/cancel`;
    const response = await apiFetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason })
    });
    if (!response.ok) {
      console.warn('Cancel request failed:', response.status);
    }
  } catch (err) {
    console.warn('Cancel request error:', err);
  }
};

const checkPollTimeout = async () => {
  if (pollStartTime && Date.now() - pollStartTime > pollTimeoutMs.value) {
    const timeoutSeconds = Math.round(pollTimeoutMs.value / 1000);
    const taskId = currentTaskId.value;
    await requestTaskCancel(taskId, `timeout after ${timeoutSeconds}s`, currentFileId.value);
    cleanupPoll();
    isMindmapReady.value = false;
    errorMsg.value = `Processing timeout (${timeoutSeconds}s), task cancelled`;
    isLoading.value = false;
    await loadHistory();
  }
};
const uploadPdfFile = (file) => new Promise((resolve, reject) => {
  const formData = new FormData();
  formData.append('file', file);

  const xhr = new XMLHttpRequest();
  xhr.open('POST', buildApiUrl('/api/upload'));
  const desktopToken = getApiAuthToken();
  if (desktopToken) {
    xhr.setRequestHeader('X-FilesMind-Token', desktopToken);
  }
  xhr.responseType = 'json';

  xhr.upload.onprogress = (event) => {
    if (!event.lengthComputable) return;
    const percent = Math.round((event.loaded / event.total) * 100);
    uploadProgress.value = Math.max(1, Math.min(100, percent));
    taskStatus.value = 'uploading';
    taskMessage.value = `正在上传文件... ${uploadProgress.value}%`;
  };

  xhr.onload = () => {
    let payload = xhr.response;
    if (!payload && xhr.responseText) {
      try {
        payload = JSON.parse(xhr.responseText);
      } catch (err) {
        reject(new Error('上传响应解析失败'));
        return;
      }
    }
    if (xhr.status < 200 || xhr.status >= 300) {
      const detail = payload?.detail || xhr.statusText || `HTTP ${xhr.status}`;
      reject(new Error(`Upload failed: ${detail}`));
      return;
    }
    resolve(payload || {});
  };

  xhr.onerror = () => reject(new Error('Network error, upload failed'));
  xhr.onabort = () => reject(new Error('Upload aborted'));
  xhr.send(formData);
});

const handleSelectedFile = async (file, clearInput) => {
  if (!file) return;
  if (!isPdfFile(file)) {
    errorMsg.value = 'Please upload a PDF file';
    if (typeof clearInput === 'function') clearInput();
    return;
  }

  // [新增] 硬件性能检查拦截
  if (hardwareType.value === 'cpu') {
      const confirmCpu = window.confirm(
          "Performance reminder\n\n" +
          "Current backend is running on CPU.\n" +
          "Large files may take longer to process.\n\n" +
          "Continue upload?"
      );
      
      if (!confirmCpu) {
          if (typeof clearInput === 'function') clearInput();
          return; // 终止上传
      }
  }

  if (currentTaskId.value) {
    cleanupPoll();
  }

  isLoading.value = true;
  taskFailureDetails.value = [];
  showAllFailureDetails.value = false;
  resetSourceView();
  isMindmapReady.value = false;
  errorMsg.value = '';
  
  taskStatus.value = 'pending';
  taskProgress.value = 0;
  uploadProgress.value = 0;
  taskMessage.value = '正在上传文件...';

  try {
    if (canUseDesktopPerfBridge()) {
      await refreshRuntimeState();
      await syncRuntimeHintToBackend({ force: true });
    }
    const data = await uploadPdfFile(file);
    
    if (data.error) {
      throw new Error(data.error);
    }

    if (data.is_duplicate) {
      if (data.status === 'completed') {
        const resolvedFileId = data.doc_id || data.file_id;
        if (!resolvedFileId) {
          throw new Error('未获取到历史文件ID');
        }
        currentFileId.value = resolvedFileId;
        if (typeof data.existing_md === 'string' && data.existing_md.length > 0) {
          mindmapData.value = data.existing_md;
          isMindmapReady.value = true;
          await loadTreeForFile(resolvedFileId);
          await syncMindMapZoom();
          isLoading.value = false;
        } else {
          await loadFile(resolvedFileId);
        }
        uploadProgress.value = 0;
        notify('info', '该文件已存在，已直接加载历史结果');
        if (typeof clearInput === 'function') clearInput();
        return;
      }

      if (data.status === 'processing' && data.task_id) {
        uploadProgress.value = 0;
        isMindmapReady.value = false;
        taskStatus.value = 'processing';
        startTaskPolling(
          data.file_id,
          data.task_id,
          data.message || '检测到相同文件正在处理中，已连接到现有任务'
        );
        await loadHistory();
        return;
      }
    }

    if (!data.task_id) {
      throw new Error('未获取到任务ID');
    }

    uploadProgress.value = 0;
    isMindmapReady.value = false;
    taskStatus.value = 'processing';

    startTaskPolling(data.doc_id || data.file_id, data.task_id);
    await loadHistory();
    
  } catch (err) {
    errorMsg.value = err.message;
    console.error("Upload error:", err);
    isMindmapReady.value = false;
    uploadProgress.value = 0;
    isLoading.value = false;
    cleanupPoll();
  } finally {
    if (typeof clearInput === 'function') clearInput();
  }
};

const handleFileUpload = async (event) => {
  const file = event?.target?.files?.[0];
  if (!file) return;
  await handleSelectedFile(file, () => {
    if (event?.target) event.target.value = '';
  });
};

const cancelTask = async () => {
  if (currentTaskId.value) {
    await requestTaskCancel(currentTaskId.value, 'user cancelled', currentFileId.value);
  }
  cleanupPoll();
  isLoading.value = false;
  uploadProgress.value = 0;
  taskProgress.value = 0;
  taskMessage.value = 'Task cancelled';
  taskFailureDetails.value = [];
  showAllFailureDetails.value = false;
  await loadHistory();
};

const formatDate = (dateStr) => {
  const date = new Date(dateStr);
  return date.toLocaleDateString('zh-CN', { 
    month: 'short', 
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  });
};

const formatDateTime = (dateStr) => {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  });
};

const rebuildActionLabel = (action) => {
  if (action === 'rebuilt') return 'rebuilt';
  if (action === 'would_rebuild') return '预览重建';
  if (action === 'skipped') return 'skipped';
  if (action === 'failed') return '失败';
  return action || '未知';
};

const rebuildActionClass = (action) => {
  if (action === 'rebuilt') return 'bg-emerald-50 text-emerald-700 border-emerald-200';
  if (action === 'would_rebuild') return 'bg-blue-50 text-blue-700 border-blue-200';
  if (action === 'skipped') return 'bg-slate-100 text-slate-600 border-slate-200';
  if (action === 'failed') return 'bg-rose-50 text-rose-700 border-rose-200';
  return 'bg-slate-100 text-slate-600 border-slate-200';
};

onMounted(() => {
  if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') {
    prefersDarkMediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    if (prefersDarkMediaQuery?.addEventListener) {
      prefersDarkMediaQuery.addEventListener('change', syncThemeFromSystemPreference);
    } else if (prefersDarkMediaQuery?.addListener) {
      prefersDarkMediaQuery.addListener(syncThemeFromSystemPreference);
    }
  }
  syncThemeFromSystemPreference();
  if (isSettingsRoute.value) {
    showSettings.value = true;
  }
  updateViewport();
  window.addEventListener('resize', updateViewport);
  if (canUseDesktopPerfBridge()) {
    runtimeMonitorEnabled = true;
    void refreshRuntimeState();
    scheduleRuntimeMonitor();
  }
  loadHistory();
  loadConfig();
  checkHardware();
  loadFeatures();
});

// 获取系统功能开关
const loadFeatures = async () => {
  try {
    const response = await apiFetch('/api/system/features');
    if (response.ok) {
      const data = await response.json();
      systemFeatures.value = { ...systemFeatures.value, ...data };
    }
  } catch (err) {
    console.warn("Features set fetch failed:", err);
  }
};

// 检查硬件状态
const checkHardware = async () => {
    try {
        const response = await apiFetch('/api/system/hardware');
        if (response.ok) {
            const data = await response.json();
            hardwareType.value = data.device_type;
            console.log("Hardware Status:", data);
        }
    } catch (err) {
        console.warn("Hardware check failed:", err);
    }
};

// 加载配置
const loadConfig = async () => {
  try {
    const response = await apiFetch('/api/config');
    if (response.ok) {
      const data = await response.json();
      const normalized = normalizeConfigStore(data);
      profiles.value = normalized.profiles;
      parserConfig.value = normalized.parser;
      advancedConfig.value = normalized.advanced;
      advancedAutoSaveState.value = 'idle';
      activeProfileId.value = normalized.active_profile_id;
      loadProfileIntoEditor(activeProfileId.value);
      configOperationMsg.value = '';
    } else {
      const err = await normalizeBackendError(response, '加载配置失败');
      console.error('加载配置失败:', err);
    }
  } catch (err) {
    console.error('加载配置失败:', err);
  }
};

const firstFieldErrorMessage = (keys) => {
  for (const key of keys) {
    if (fieldErrors.value[key]) return fieldErrors.value[key];
  }
  return '';
};

// 保存配置
const saveConfig = async (scope = 'all', options = {}) => {
  const {
    silent = false,
    reloadAfterSave = true
  } = options;
  let keys = [];
  if (scope === 'parser') keys = parserErrorKeys;
  else if (scope === 'llm') keys = llmErrorKeys;
  else if (scope === 'advanced') keys = advancedAutoSaveErrorKeys;
  else keys = Object.keys(fieldErrors.value);

  const scopedError = firstFieldErrorMessage(keys);
  if (scopedError) {
    if (scope === 'advanced') advancedAutoSaveState.value = 'error';
    if (!silent) notify('warning', scopedError || 'Please fix config fields first');
    return;
  }
  if (scope === 'all' && hasValidationErrors.value) {
    const firstMessage = Object.values(fieldErrors.value)[0] || 'Please fix config fields first';
    if (!silent) notify('warning', firstMessage);
    return;
  }
  configLoading.value = true;
  if (scope !== 'advanced') {
    configTestResult.value = null;
  }
  try {
    const payload = buildConfigStorePayload({
      persistCurrentProfile: scope === 'all' || scope === 'llm'
    });
    const response = await apiFetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await parseResponsePayload(response);
    if (isEmptyServerErrorResponse(response, data)) {
      if (scope === 'advanced') {
        advancedAutoSaveState.value = 'error';
      } else if (!silent) {
        notify('error', backendUnavailableMessage);
      }
      return;
    }
    if (response.ok && data?.success !== false) {
      if (reloadAfterSave) {
        await loadConfig();
      }
      if (scope === 'advanced') {
        advancedAutoSaveState.value = 'saved';
      } else if (!silent) {
        notify('success', 'Config saved');
      }
      if (!silent) {
        configOperationMsg.value = '配置已保存并生效';
      }
    } else {
      const detail = data?.detail || data;
      const code = detail?.code || data?.code || (response.ok ? 'UNKNOWN_ERROR' : `HTTP_${response.status}`);
      const message = typeof detail === 'string'
        ? detail
        : (detail?.message || data?.message || response.statusText || '未知错误');
      if (scope === 'advanced') {
        advancedAutoSaveState.value = 'error';
      } else if (!silent) {
        notify('error', `保存失败: ${getErrorHint(code, message)} (${code})`);
      }
    }
  } catch (err) {
    if (scope === 'advanced') {
      advancedAutoSaveState.value = 'error';
    } else if (!silent) {
      notify('error', `保存失败: ${err.message || backendUnavailableMessage}`);
    }
  }
  configLoading.value = false;
};

const scheduleAdvancedAutoSave = () => {
  advancedAutoSaveState.value = 'idle';
  if (firstFieldErrorMessage(advancedAutoSaveErrorKeys)) return;
  if (advancedAutoSaveTimer) clearTimeout(advancedAutoSaveTimer);
  advancedAutoSaveState.value = 'saving';
  advancedAutoSaveTimer = setTimeout(async () => {
    await saveConfig('advanced', { silent: true, reloadAfterSave: false });
  }, 360);
};

// 测试配置
const testConfig = async () => {
  if (!canTestConfig.value) {
    const firstMessage = Object.values(fieldErrors.value)[0] || 'Please fix config fields first';
    notify('warning', firstMessage);
    return;
  }
  configLoading.value = true;
  configTestResult.value = null;
  try {
    const response = await apiFetch('/api/config/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildSingleProfilePayload())
    });
    const result = await parseResponsePayload(response);
    if (isEmptyServerErrorResponse(response, result)) {
      configTestResult.value = {
        success: false,
        code: 'BACKEND_UNAVAILABLE',
        message: `${backendUnavailableMessage} (BACKEND_UNAVAILABLE)`,
        hint: backendUnavailableMessage
      };
      return;
    }
    const success = response.ok ? (result?.success !== false) : false;
    const code = result?.code || (success ? 'OK' : `HTTP_${response.status}`);
    const message = result?.message || (success ? '连接测试完成' : (response.statusText || '连接测试失败'));
    configTestResult.value = {
      ...(result || {}),
      success,
      code,
      message: `${message}${code ? ` (${code})` : ''}`,
      hint: getErrorHint(code, message)
    };
  } catch (err) {
    configTestResult.value = { success: false, message: err.message || backendUnavailableMessage };
  }
  configLoading.value = false;
};

const loadModels = async () => {
  if (!canTestConfig.value) {
    const firstMessage = Object.values(fieldErrors.value)[0] || 'Please fix config fields first';
    notify('warning', firstMessage);
    return;
  }
  modelLoading.value = true;
  modelFetchResult.value = null;
  try {
    const response = await apiFetch('/api/config/models', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(buildSingleProfilePayload())
    });
    const data = await parseResponsePayload(response);
    if (isEmptyServerErrorResponse(response, data)) {
      modelFetchResult.value = {
        success: false,
        message: backendUnavailableMessage,
        source: 'none',
        code: 'BACKEND_UNAVAILABLE'
      };
      return;
    }
    if (!data) {
      modelFetchResult.value = {
        success: false,
        message: response.ok ? '服务端未返回模型列表数据' : (response.statusText || '拉取模型列表失败'),
        source: 'none',
        code: response.ok ? 'EMPTY_RESPONSE' : `HTTP_${response.status}`
      };
      return;
    }
    modelFetchResult.value = data;
    if (response.ok && data?.success && Array.isArray(data.models)) {
      modelCatalogByProfile.value[config.value.id] = data.models;
      if (!config.value.model && data.models.length > 0) {
        config.value.model = data.models[0];
      }
    } else if (data?.code) {
      modelFetchResult.value.message = `${data.message || ''} (${data.code})`;
    } else if (!response.ok) {
      modelFetchResult.value = {
        ...data,
        success: false,
        message: data?.message || response.statusText || '拉取模型列表失败',
        source: data?.source || 'none',
        code: data?.code || `HTTP_${response.status}`
      };
    }
  } catch (err) {
    modelFetchResult.value = { success: false, message: err.message, source: 'none', code: 'NETWORK_ERROR' };
  }
  modelLoading.value = false;
};

const runSourceIndexRebuild = async (dryRun = false) => {
  if (sourceIndexRebuildRunning.value) return;
  sourceIndexRebuildRunning.value = true;
  try {
    const response = await apiFetch('/api/admin/source-index/rebuild', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        dry_run: Boolean(dryRun),
        force: false,
        only_shallow: true,
        include_precise_anchor: false,
        verbose: true
      })
    });
    const data = await parseResponsePayload(response);
    sourceIndexRebuildResult.value = data;

    if (isEmptyServerErrorResponse(response, data)) {
      notify('error', backendUnavailableMessage);
      return;
    }
    if (!response.ok) {
      const detail = data?.detail || data;
      const code = detail?.code || `HTTP_${response.status}`;
      const message = detail?.message || response.statusText || '索引重建失败';
      notify('error', `${getErrorHint(code, message)} (${code})`);
      return;
    }

    const summary = data?.summary || {};
    const failed = Number(summary.failed || 0);
    const rebuilt = Number(summary.rebuilt || 0);
    const skipped = Number(summary.skipped || 0);
    const scanned = Number(summary.scanned || 0);
    if (failed > 0) {
      notify('warning', `完成但存在失败：扫描 ${scanned}，重建 ${rebuilt}，跳过 ${skipped}，失败 ${failed}`);
    } else {
      notify('success', `${dryRun ? '预览完成' : '重建完成'}：扫描 ${scanned}，重建 ${rebuilt}，跳过 ${skipped}`);
    }
    if (!dryRun) {
      await loadHistory();
    }
  } catch (err) {
    notify('error', `索引重建失败: ${err.message || backendUnavailableMessage}`);
  } finally {
    sourceIndexRebuildRunning.value = false;
  }
};
</script>

<template>
  <div
    ref="appShellRef"
    class="app-shell w-full h-screen flex transform-gpu font-sans overflow-hidden relative text-slate-700 dark:text-slate-200"
    @dragover.prevent="onDragOver"
    @dragleave.prevent="onDragLeave"
    @drop.prevent="onDrop"
  >
    <!-- 全局拖拽悬浮层 -->
    <div
      v-if="isDraggingFile"
      class="absolute inset-0 z-[100] bg-blue-500/10 backdrop-blur-sm m-4 rounded-3xl border-4 border-dashed border-blue-400 flex items-center justify-center transition-all duration-300 pointer-events-none"
    >
      <div class="bg-white/95 dark:bg-slate-900/95 px-10 py-8 rounded-2xl shadow-2xl flex flex-col items-center border border-slate-100 dark:border-slate-700/60">
        <svg class="w-20 h-20 text-blue-500 mb-4 animate-bounce" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 16.5V9.75m0 0l3 3m-3-3l-3 3M6.75 19.5a4.5 4.5 0 01-1.41-8.775 5.25 5.25 0 0110.233-2.33 3 3 0 013.758 3.848A3.752 3.752 0 0118 19.5H6.75z"></path>
        </svg>
        <h2 class="text-2xl font-bold text-slate-700 dark:text-slate-100 tracking-wide">释放鼠标，立即解析文档</h2>
      </div>
    </div>

    <!-- Toast 通知 -->
    <TransitionGroup name="toast" tag="div" class="fixed top-4 right-4 z-[120] flex flex-col gap-2 w-[min(92vw,360px)] pointer-events-none">
      <div
        v-for="item in toasts"
        :key="item.id"
        class="pointer-events-auto rounded-xl border shadow-lg backdrop-blur-sm px-3 py-2.5 flex items-start gap-2"
        :class="toastTypeClass(item.type)"
      >
        <span class="mt-1 h-1.5 w-1.5 rounded-full bg-current opacity-80"></span>
        <div class="text-sm leading-5 flex-1">{{ item.message }}</div>
        <button
          @click="removeToast(item.id)"
          class="text-current/70 hover:text-current rounded-md px-1 transition-all duration-200"
          aria-label="close toast"
        >
          ×
        </button>
      </div>
    </TransitionGroup>

    <!-- 侧边栏 - 可折叠 + 可拖拽 -->
    <aside
      class="app-panel elev-md flex-shrink-0 backdrop-blur-xl flex flex-col overflow-hidden transition-[width,opacity] duration-300 ease-out"
      :style="{ width: showSidebar ? `${sidebarWidth}px` : '0px' }"
      :class="showSidebar ? 'opacity-100 border-r border-slate-200/60 dark:border-slate-700/70' : 'opacity-0 border-r-0 pointer-events-none'"
    >
      <!-- Logo 区域 -->
      <div class="brand-banner h-14 px-4 flex items-center border-b border-slate-200/40">
        <div class="flex items-center gap-2.5">
          <div class="w-8 h-8 bg-white/20 backdrop-blur-sm rounded-lg flex items-center justify-center text-white text-sm font-bold shadow-lg">
            FM
          </div>
          <div>
            <span class="text-sm font-bold text-white tracking-wide">FilesMind</span>
            <p class="text-[10px] text-blue-100 -mt-0.5">Document to MindMap</p>
          </div>
        </div>
      </div>

      <!-- 文件列表 -->
      <div class="flex-1 overflow-y-auto p-3 bg-slate-50/50 dark:bg-slate-900/20">
        <div class="flex items-center justify-between mb-3 px-2">
          <div class="text-xs font-semibold text-slate-500 uppercase tracking-wider">
            历史文件
          </div>
          <span class="text-[10px] px-2 py-0.5 bg-slate-200/60 text-slate-600 rounded-full">{{ history.length }}</span>
        </div>

        <div v-if="history.length === 0" class="text-xs text-slate-400 text-center py-8 px-4">
          <svg class="w-12 h-12 mx-auto mb-2 opacity-30" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
          </svg>
          暂无文件记录
        </div>

        <div v-else class="space-y-1.5">
          <div
            v-for="item in history"
            :key="item.file_id"
            @click="loadFile(item.file_id)"
            class="group p-2.5 rounded-xl cursor-pointer transition-all duration-200 border card-hover"
            :class="currentFileId === item.file_id
              ? 'bg-gradient-to-r from-blue-50/60 to-indigo-50/60 border-blue-200/60 shadow-sm'
              : 'bg-white/60 border-transparent hover:bg-white hover:border-slate-200/40 hover:shadow-soft'"
          >
            <div class="flex items-start justify-between gap-2">
              <div class="flex-1 min-w-0">
                <div class="font-medium text-slate-700 truncate text-sm">{{ item.filename }}</div>
                <div class="flex items-center gap-2 mt-1.5">
                  <span
                    class="text-[10px] px-1.5 py-0.5 rounded-full font-medium flex items-center gap-0.5"
                    :class="item.status === 'completed'
                      ? 'bg-emerald-100 text-emerald-600'
                      : item.status === 'processing'
                        ? 'bg-amber-100 text-amber-600'
                        : 'bg-rose-100 text-rose-600'"
                  >
                    <span v-if="item.status === 'completed'">OK</span>
                    <span v-else-if="item.status === 'processing'">...</span>
                    <span v-else>!</span>
                  </span>
                  <span class="text-[10px] text-slate-400">{{ formatDate(item.created_at) }}</span>
                </div>
              </div>

              <button
                @click="deleteFile(item.file_id, $event)"
                class="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg text-slate-400 hover:text-rose-500 hover:bg-rose-50 transition-all duration-200"
              >
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部提示 -->
      <div class="p-3 border-t border-slate-200/60 dark:border-slate-700/70 bg-gradient-to-r from-slate-50 to-blue-50/30 dark:from-slate-900/40 dark:to-slate-800/30">
        <div class="text-[10px] text-slate-400 text-center">
          Powered by <span class="font-medium text-slate-500">IBM Docling</span> & <span class="font-medium text-slate-500">LLM Models</span> & <span class="font-medium text-slate-500">aitangmy</span>
        </div>
      </div>
    </aside>

    <div
      v-if="showSidebar"
      class="w-2 cursor-col-resize bg-slate-200/40 dark:bg-slate-700/30 hover:bg-blue-100/70 dark:hover:bg-blue-900/50 transition-colors relative flex items-center justify-center"
      :class="{ 'bg-blue-100/90': isSidebarResizing }"
      @mousedown="startSidebarResizing"
    >
      <div class="h-14 w-[2px] rounded-full bg-slate-400/40"></div>
      <div class="absolute inset-y-0 left-0 right-0 flex items-center justify-center">
        <div class="h-7 w-1 rounded-full bg-blue-500/35"></div>
      </div>
    </div>

    <!-- 主内容区 -->
    <div class="flex-1 flex flex-col min-w-0">
      <!-- 椤堕儴瀵艰埅鏍?-->
      <header class="app-toolbar flex-shrink-0 backdrop-blur-xl border-b border-slate-200/40 dark:border-slate-700/60 shadow-sm">
        <div class="h-14 flex items-center justify-between px-4">
          <div class="flex items-center gap-3">
            <button
              @click="showSidebar = !showSidebar"
              class="p-2 rounded-xl text-slate-500 dark:text-slate-300 hover:bg-slate-100/80 dark:hover:bg-slate-700/60 hover:text-slate-700 dark:hover:text-slate-100 transition-all duration-200"
              :title="showSidebar ? '隐藏侧边栏' : '显示侧边栏'"
            >
              <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M3.75 6.75h13.5M3.75 12h13.5M3.75 17.25h13.5"></path>
              </svg>
            </button>

            <label
              class="inline-flex items-center px-4 py-2 btn-primary text-sm rounded-xl cursor-pointer disabled:opacity-50 brand-glow"
              :class="{ 'opacity-50': isLoading }"
            >
              <input
                ref="fileInput"
                type="file"
                accept=".pdf"
                class="hidden"
                @change="handleFileUpload"
                :disabled="isLoading"
              />

              <span class="flex items-center gap-2">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path>
                </svg>
                上传 PDF
              </span>
            </label>
          </div>

          <div class="flex items-center gap-2">
            <span
              v-if="isTabletViewport"
              class="hidden md:inline-flex text-[11px] px-2 py-1 rounded-full bg-slate-100 dark:bg-slate-700/70 text-slate-500 dark:text-slate-200"
            >
              平板宽度已自动隐藏原文区
            </span>
            <button
              @click="triggerToggleTheme"
              class="p-2 rounded-xl text-slate-500 dark:text-slate-300 hover:text-slate-700 dark:hover:text-slate-100 hover:bg-slate-100/80 dark:hover:bg-slate-700/60 transition-all duration-200 border border-transparent hover:border-slate-200 dark:hover:border-slate-600"
              :title="isDarkTheme ? '切换为浅色模式' : '切换为深色模式'"
            >
              <svg v-if="!isDarkTheme" class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"></path></svg>
              <svg v-else class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 3v2.25m0 13.5V21m6.364-13.364l-1.59 1.59M7.227 16.773l-1.59 1.59m12.727 0l-1.59-1.59M7.227 7.227l-1.59-1.59M21 12h-2.25M5.25 12H3m9 6a6 6 0 100-12 6 6 0 000 12z"></path></svg>
            </button>
            <button
              @click="openSettingsPage"
              data-testid="settings-open-btn"
              class="settings-open-btn flex items-center gap-2 px-3 py-2 rounded-xl text-slate-600 dark:text-slate-100 transition-all duration-200 border font-semibold"
              title="系统设置"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317a1 1 0 011.35-.936l.75.325a1 1 0 00.9 0l.75-.325a1 1 0 011.35.936l.084.805a1 1 0 00.57.79l.726.42a1 1 0 01.365 1.366l-.403.701a1 1 0 000 .998l.403.701a1 1 0 01-.365 1.366l-.726.42a1 1 0 00-.57.79l-.084.805a1 1 0 01-1.35.936l-.75-.325a1 1 0 00-.9 0l-.75.325a1 1 0 01-1.35-.936l-.084-.805a1 1 0 00-.57-.79l-.726-.42a1 1 0 01-.365-1.366l.403-.701a1 1 0 000-.998l-.403-.701a1 1 0 01.365-1.366l.726-.42a1 1 0 00.57-.79l.084-.805z"></path>
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10.5a1.5 1.5 0 110 3 1.5 1.5 0 010-3z"></path>
              </svg>
              <span class="text-[13px] hidden sm:inline">系统设置</span>
            </button>
          </div>
        </div>

        <div v-if="topNoticeVisible" class="px-4 pb-3 space-y-2">
          <div
            v-if="isLoading"
            class="rounded-xl border border-blue-200/70 dark:border-blue-500/40 bg-gradient-to-r from-blue-50 to-indigo-50 dark:from-slate-800/90 dark:to-slate-700/80 px-3 py-2 flex items-center gap-2"
          >
            <div class="flex-1 h-2 bg-white/80 dark:bg-slate-900/90 rounded-full overflow-hidden border border-white/40 dark:border-slate-600/80">
              <div
                class="brand-progress h-full rounded-full transition-all duration-300 relative overflow-hidden"
                :class="{ 'animate-pulse': isUploadStage }"
                :style="{ width: `${effectiveTaskProgress}%` }"
              >
                <div class="absolute inset-0 bg-white/20 animate-pulse"></div>
              </div>
            </div>
            <span class="text-[11px] font-semibold text-slate-700 dark:text-slate-100 w-11 text-right">{{ Math.round(effectiveTaskProgress) }}%</span>
            <span class="text-[11px] text-slate-500 dark:text-slate-300 max-w-[240px] truncate">{{ taskMessage }}</span>
            <button @click="cancelTask" class="p-1 rounded-md text-slate-400 dark:text-slate-300 hover:text-rose-500 dark:hover:text-rose-300 hover:bg-rose-50 dark:hover:bg-rose-500/20 transition-all duration-200">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
              </svg>
            </button>
          </div>
          <div
            v-if="errorMsg"
            class="rounded-xl border border-rose-200/80 bg-gradient-to-r from-rose-50 to-orange-50 px-3 py-2"
          >
            <div class="flex items-center gap-2">
              <div class="p-1 rounded-md bg-rose-100">
                <svg class="w-4 h-4 text-rose-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                </svg>
              </div>
              <span class="text-xs font-medium text-rose-700 truncate">{{ errorMsg }}</span>
              <button
                @click="clearTaskErrorNotice"
                class="ml-auto p-1 rounded-md text-rose-400 hover:text-rose-600 hover:bg-rose-100 transition-all duration-200"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                </svg>
              </button>
            </div>
            <div v-if="hasTaskFailureDetails" class="mt-2 rounded-lg border border-rose-200 bg-white/80 p-2.5">
              <div class="flex items-center justify-between gap-2 mb-2">
                <span class="text-[11px] font-semibold text-rose-700">Failure Nodes ({{ taskFailureDetailCount }})</span>
                <button
                  v-if="taskFailureDetailCount > 6"
                  @click="showAllFailureDetails = !showAllFailureDetails"
                  class="text-[11px] text-rose-600 hover:text-rose-700 font-medium"
                >
                  {{ showAllFailureDetails ? 'Collapse' : 'Show all' }}
                </button>
              </div>
              <div class="space-y-1.5 max-h-40 overflow-y-auto pr-1">
                <div
                  v-for="(item, idx) in visibleTaskFailureDetails"
                  :key="`${item.nodeId || item.topic || 'node'}-${idx}`"
                  class="failure-item"
                >
                  <div class="failure-head">
                    <span class="failure-topic" :title="item.topic || item.nodeId || 'Unknown node'">{{ item.topic || item.nodeId || 'Unknown node' }}</span>
                    <button
                      class="failure-jump-btn"
                      @click="locateFailedNode(item)"
                      title="Locate this failed node"
                    >
                      定位
                    </button>
                  </div>
                  <div class="failure-error" :title="item.error || 'Unknown error'">{{ item.error || 'Unknown error' }}</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </header>

      <!-- 主内容区（双栏分割容器） -->
      <main class="flex-1 p-6 overflow-hidden bg-slate-100/50 dark:bg-slate-900/30 flex">
        <div
          ref="workspaceLayoutRef"
          class="h-full w-full grid items-stretch overflow-hidden"
          :style="workspaceGridStyle"
        >
          <!-- 左侧：思维导图 -->
          <div class="app-card elev-md min-w-0 h-full flex flex-col rounded-xl border border-slate-200/40 dark:border-slate-700/60 overflow-hidden relative">
            <div class="absolute top-4 right-4 flex items-center gap-1 z-20 bg-white/70 dark:bg-slate-900/70 backdrop-blur-md p-1 rounded-xl shadow-sm border border-slate-200/40 dark:border-slate-700/70">
              <button @click="triggerExportPng" class="p-2 rounded-lg text-slate-500 dark:text-slate-200 hover:text-slate-700 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors" title="Export as PNG">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 5h16v12H4z"></path><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 15l4-4 3 3 4-4 5 5"></path></svg>
              </button>
              <button @click="triggerExportMd" class="p-2 rounded-lg text-slate-500 dark:text-slate-200 hover:text-slate-700 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors" title="Export as Markdown">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
              </button>
              <button
                @click="triggerExportXmind"
                @mouseenter="prefetchXmindExportAssets"
                @focus="prefetchXmindExportAssets"
                class="p-2 rounded-lg text-slate-500 dark:text-slate-200 hover:text-slate-700 dark:hover:text-white hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
                title="Export as XMind"
              >
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
              </button>
            </div>

            <div class="flex-1 min-h-0 w-full relative">
              <Transition name="fade" mode="out-in">
                <div v-if="!showMindmapCanvas" key="hero-upload" class="absolute inset-0 p-6 md:p-10 bg-gradient-to-b from-slate-50 to-white dark:from-slate-900 dark:to-slate-950 flex items-center justify-center">
                  <div
                    @click="triggerFileInput"
                    class="group w-full max-w-3xl min-h-[340px] rounded-3xl border-2 border-dashed border-slate-300 dark:border-slate-600 hover:border-orange-400 dark:hover:border-orange-300 hover:bg-orange-50/60 dark:hover:bg-orange-500/10 transition-all duration-300 ease-out cursor-pointer bg-white/90 dark:bg-slate-800/85 shadow-sm flex flex-col items-center justify-center px-8 py-10"
                    :class="{ 'border-orange-400 dark:border-orange-300 bg-orange-50/70 dark:bg-orange-500/15 shadow-md': isDraggingFile }"
                  >
                    <svg class="w-20 h-20 mb-5 text-slate-400 dark:text-slate-500 group-hover:text-blue-500 dark:group-hover:text-blue-300 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 16.5V9.75m0 0l3 3m-3-3l-3 3M6.75 19.5a4.5 4.5 0 01-1.41-8.775 5.25 5.25 0 0110.233-2.33 3 3 0 013.758 3.848A3.752 3.752 0 0118 19.5H6.75z"></path>
                    </svg>
                    <h2 class="text-xl md:text-2xl font-semibold text-slate-700 dark:text-slate-100 tracking-wide text-center">点击或拖拽 PDF 文件至此</h2>
                    <p class="text-sm text-slate-500 dark:text-slate-300 mt-3 text-center">解析完成后自动生成思维导图，并在右侧联动展示节点详情与 PDF 原文</p>
                    <p class="text-xs text-slate-400 dark:text-slate-400 mt-4">支持 PDF 格式，最大 50MB</p>

                    <div v-if="isLoading" class="w-full max-w-xl mt-8 space-y-4">
                      <div class="skeleton-tree-wrap">
                        <div class="skeleton-trunk"></div>
                        <div class="skeleton-branches">
                          <div
                            v-for="branch in skeletonBranches"
                            :key="branch.index"
                            class="skeleton-branch"
                            :class="[branch.side, { active: branch.active }]"
                          ></div>
                        </div>
                      </div>

                      <div class="w-full h-3 bg-slate-200 dark:bg-slate-700 rounded-full overflow-hidden border border-slate-200/60 dark:border-slate-600/70">
                        <div
                          class="brand-progress h-full rounded-full transition-all duration-300 relative"
                          :class="{ 'animate-pulse': isUploadStage }"
                          :style="{ width: `${effectiveTaskProgress}%` }"
                        >
                          <div class="absolute inset-0 bg-white/20 animate-pulse"></div>
                        </div>
                      </div>
                      <div class="mt-2 flex items-center justify-between text-xs">
                        <span class="text-slate-500 dark:text-slate-300 truncate pr-3">{{ taskMessage }}</span>
                        <span class="text-slate-600 dark:text-slate-100 font-medium">{{ Math.round(effectiveTaskProgress) }}%</span>
                      </div>
                    </div>
                  </div>
                </div>

                <MindMap
                  v-else
                  key="mindmap-canvas"
                  ref="mindMapRef"
                  :tree="treeData"
                  :markdown="mindmapData"
                  :file-id="currentFileId || ''"
                  :features="systemFeatures"
                  :flat-nodes="flatNodes"
                  :dark-mode="isDarkTheme"
                  class="absolute inset-0"
                  @node-click="handleMindmapNodeClick"
                  @feedback="handleMindmapFeedback"
                  @zoom-change="handleMindmapZoomChange"
                />
              </Transition>
              <div
                v-if="showMindmapToolbar"
                class="absolute bottom-4 left-1/2 -translate-x-1/2 z-20 flex items-center gap-1.5 bg-white/88 dark:bg-slate-900/88 backdrop-blur-md rounded-xl border border-slate-200 dark:border-slate-700 shadow-lg px-2 py-1.5"
              >
                <button @click="triggerCollapseAll" class="toolbar-btn" title="折叠全部">折叠</button>
                <button @click="triggerExpandAll" class="toolbar-btn" title="展开全部">展开</button>
                <button @click="triggerFitView" class="toolbar-btn" title="居中视图">居中</button>
                <div class="w-px h-5 bg-slate-200 dark:bg-slate-600 mx-1"></div>
                <button @click="triggerZoomOut" class="toolbar-btn toolbar-zoom" title="缩小">-</button>
                <span class="text-[11px] text-slate-600 dark:text-slate-200 font-medium min-w-12 text-center">{{ mindMapZoomPercent }}%</span>
                <button @click="triggerZoomIn" class="toolbar-btn toolbar-zoom" title="放大">+</button>
              </div>
            </div>
          </div>

          <!-- 分隔拖拽条 -->
          <div
            v-if="showDetailPane"
            class="group cursor-col-resize flex flex-col justify-center items-center rounded-md bg-slate-200/40 dark:bg-slate-700/30 hover:bg-blue-100/70 dark:hover:bg-blue-900/50 transition-colors relative"
            :class="{ 'bg-blue-100/90': isPdfResizing }"
            @mousedown="startPdfResizing"
          >
            <div class="h-full w-[2px] bg-slate-400/40 rounded-full group-hover:bg-blue-500/45 transition-colors relative">
              <div class="absolute top-1/2 -translate-y-1/2 -left-1 w-4 h-7 bg-blue-500/35 rounded-full"></div>
            </div>
          </div>

          <!-- 右侧：节点详情 -->
          <aside
            v-if="showDetailPane"
            class="app-card elev-md h-full flex flex-col rounded-xl border border-slate-200/40 dark:border-slate-700/60 overflow-hidden transition-all duration-300 ease-out"
            :class="{ 'duration-0': isPdfResizing }"
            :style="{ width: `${pdfPaneWidth}px`, minWidth: '320px' }"
            @mouseenter="prefetchPdfViewerAssets"
          >
            <div class="p-3 border-b border-slate-200/40 dark:border-slate-700/60 flex-shrink-0 bg-slate-50/60 dark:bg-slate-800/70 backdrop-blur-sm z-10 flex items-center justify-between">
              <div>
                <h3 class="text-sm font-semibold text-slate-700 flex items-center gap-2">
                  <svg class="w-4 h-4 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
                  节点详情
                </h3>
                <p class="text-[11px] text-slate-500 mt-0.5 truncate max-w-[240px]" :title="sourceView.topic || '选择节点以查看'">
                  {{ sourceView.topic ? sourceView.topic : '选择左侧节点以查看详情与 PDF 原文' }}
                </p>
              </div>
            </div>

            <div class="flex-1 min-h-0 relative bg-slate-100 dark:bg-slate-900/40 flex flex-col pointer-events-auto">
              <div v-if="!currentFileId" class="absolute inset-0 flex items-center justify-center p-6 bg-slate-50/50">
                <div class="w-full max-w-sm flex flex-col items-center justify-center p-8 border border-slate-200 rounded-2xl bg-white text-center">
                  <svg class="w-12 h-12 text-slate-300 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5A3.375 3.375 0 0010.125 2.25H6.75A2.25 2.25 0 004.5 4.5v15A2.25 2.25 0 006.75 21.75h10.5a2.25 2.25 0 002.25-2.25v-5.25z"></path>
                  </svg>
                  <h4 class="text-sm font-semibold text-slate-700">详情面板</h4>
                  <p class="text-xs text-slate-500 mt-1 leading-relaxed">上传并生成导图后，点击左侧节点可在这里查看结构化摘要和 PDF 原文。</p>
                </div>
              </div>
              <div v-else-if="!selectedNode" class="absolute inset-0 flex items-center justify-center p-6 bg-slate-50/50">
                <div class="w-full max-w-sm flex flex-col items-center justify-center p-8 border border-slate-200 rounded-2xl bg-white text-center">
                  <svg class="w-12 h-12 text-slate-300 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M13.5 4.5L21 12l-7.5 7.5M3 12h18"></path>
                  </svg>
                  <h4 class="text-sm font-semibold text-slate-700">请选择导图节点</h4>
                  <p class="text-xs text-slate-500 mt-1 leading-relaxed">点击左侧任意节点后，这里会展示行号范围并定位 PDF 原文。</p>
                </div>
              </div>
              <div v-else-if="sourceView.loading" class="absolute inset-x-0 top-0 z-20 flex justify-center p-2">
                 <div class="bg-blue-50 text-blue-600 text-[11px] px-3 py-1.5 rounded-full border border-blue-200 shadow-sm flex items-center gap-2 font-medium">
                    <svg class="animate-spin h-3.5 w-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    正在加载节点详情...
                 </div>
              </div>
              <div v-else-if="sourceView.error" class="absolute inset-0 flex items-center justify-center p-4 z-10">
                <div class="text-xs text-rose-600 bg-rose-50 border border-rose-200 rounded-lg p-4 text-center max-w-[80%] shadow-sm">
                  {{ sourceView.error }}
                </div>
              </div>
              <div v-else class="w-full h-full p-4 flex flex-col gap-3 min-h-0">
                <div class="flex flex-wrap gap-2 flex-shrink-0">
                  <span class="px-2 py-1 rounded-lg bg-blue-50 text-blue-700 border border-blue-200 text-xs font-medium">
                    {{ sourceView.topic || selectedNode.topic || '未命名节点' }}
                  </span>
                  <span v-if="sourceView.lineStart" class="px-2 py-1 rounded-lg bg-slate-100 text-slate-600 border border-slate-200 text-xs font-mono">
                    L{{ sourceView.lineStart }}-L{{ sourceView.lineEnd || sourceView.lineStart }}
                  </span>
                  <span class="px-2 py-1 rounded-lg bg-slate-100 text-slate-500 border border-slate-200 text-xs">
                    parser: {{ sourceView.parserBackend || 'unknown' }}
                  </span>
                  <span v-if="sourceView.pdfPageNo" class="px-2 py-1 rounded-lg bg-indigo-50 text-indigo-700 border border-indigo-200 text-xs font-mono">
                    PDF P{{ sourceView.pdfPageNo }}
                  </span>
                </div>
                <div v-if="showPdfViewer" class="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 overflow-hidden flex-1 min-h-[320px]">
                  <VirtualPdfViewer
                    :key="currentFileId || 'none'"
                    :source-url="currentPdfSourceUrl"
                    :page-no="sourceView.pdfPageNo"
                    :y-ratio="sourceView.pdfYRatio"
                    :navigate-key="pdfNavigateToken"
                    :scale="1.05"
                    :max-mounted-pages="pdfMaxMountedPages"
                    :buffer-pages="pdfBufferPages"
                    :preload-max-pages="pdfPreloadMaxPages"
                    :preload-concurrency="pdfPreloadConcurrency"
                    @loaded="handlePdfViewerLoaded"
                    @error="handlePdfViewerError"
                  />
                </div>
                <div v-if="sourceView.pdfLoadError" class="rounded-xl border border-rose-200 bg-rose-50 p-3 text-xs text-rose-700 flex-shrink-0">
                  PDF 渲染失败：{{ sourceView.pdfLoadError }}
                </div>
              </div>
            </div>
          </aside>
        </div>
      </main>
    </div>
  </div>

  <!-- 系统设置弹窗（统一 Tabs） -->
  <Transition name="modal">
    <div
      v-if="showSettings"
      data-testid="settings-modal"
      class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm flex items-center justify-center z-50 p-4"
      @click.self="closeSettings"
    >
      <div class="settings-modal-panel app-card elev-lg rounded-2xl w-full max-w-2xl mx-4 overflow-hidden flex flex-col h-[min(90vh,820px)] transition-all duration-300 ease-out border border-slate-200/40">
        <div class="settings-modal-header flex items-center justify-between px-6 py-4 border-b border-slate-200/40 bg-gradient-to-r from-slate-50/80 to-blue-50/20 flex-shrink-0">
          <div class="flex items-center gap-3">
            <div class="p-2 bg-blue-100 rounded-xl">
              <svg class="w-5 h-5 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317a1 1 0 011.35-.936l.75.325a1 1 0 00.9 0l.75-.325a1 1 0 011.35.936l.084.805a1 1 0 00.57.79l.726.42a1 1 0 01.365 1.366l-.403.701a1 1 0 000 .998l.403.701a1 1 0 01-.365 1.366l-.726.42a1 1 0 00-.57.79l-.084.805a1 1 0 01-1.35.936l-.75-.325a1 1 0 00-.9 0l-.75.325a1 1 0 01-1.35-.936l-.084-.805a1 1 0 00-.57-.79l-.726-.42a1 1 0 01-.365-1.366l.403-.701a1 1 0 000-.998l-.403-.701a1 1 0 01.365-1.366l.726-.42a1 1 0 00.57-.79l.084-.805z"></path>
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10.5a1.5 1.5 0 110 3 1.5 1.5 0 010-3z"></path>
              </svg>
            </div>
            <div>
              <h2 class="text-lg font-semibold text-slate-800">系统设置</h2>
              <p class="text-xs text-slate-500">
                {{ activeSettingsTab === 'model' ? '模型与鉴权' : (activeSettingsTab === 'parser' ? '解析与阈值' : '高级引擎控制') }}
              </p>
            </div>
          </div>
          <button @click="closeSettings" class="settings-modal-close-btn p-2 rounded-xl text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-all duration-200">
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
          </button>
        </div>

        <div class="settings-modal-tabs px-6 pt-3 pb-1 border-b border-slate-200/40 bg-slate-50/70 flex items-center gap-2">
          <button
            data-testid="settings-tab-model"
            class="settings-tab-btn"
            :class="{ active: activeSettingsTab === 'model' }"
            type="button"
            @click="activeSettingsTab = 'model'"
          >
            模型与授权
          </button>
          <button
            data-testid="settings-tab-parser"
            class="settings-tab-btn"
            :class="{ active: activeSettingsTab === 'parser' }"
            type="button"
            @click="activeSettingsTab = 'parser'"
          >
            解析与阈值
          </button>
          <button
            data-testid="settings-tab-advanced"
            class="settings-tab-btn"
            :class="{ active: activeSettingsTab === 'advanced' }"
            type="button"
            @click="activeSettingsTab = 'advanced'"
          >
            高级引擎
          </button>
        </div>

        <input
          ref="configImportInput"
          type="file"
          accept=".json,application/json"
          class="hidden"
          @change="importConfigFromFile"
        />

        <div class="settings-modal-body p-6 flex-1 min-h-0 overflow-y-auto">
          <div v-if="activeSettingsTab === 'model'" data-testid="settings-model-panel" class="space-y-5">
            <div class="flex items-center justify-between gap-2 p-3 bg-blue-50/60 border border-blue-100 rounded-xl">
              <p class="text-xs text-slate-600">支持导出当前配置（不含明文密钥），并在本机或其他环境导入。</p>
              <div class="flex items-center gap-2">
                <button @click="triggerImportConfig" type="button" class="px-3 py-1.5 text-xs rounded-lg border border-slate-300 hover:bg-white">导入</button>
                <button @click="exportConfig" type="button" class="px-3 py-1.5 text-xs rounded-lg border border-slate-300 hover:bg-white">导出</button>
              </div>
            </div>
            <div v-if="configOperationMsg" class="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2">
              {{ configOperationMsg }}
            </div>

            <div>
              <label class="flex items-center gap-2 text-sm font-medium text-slate-700 mb-2">
                服务商
              </label>
              <select
                :value="config.provider"
                @change="onProviderChange"
                class="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-200 bg-white hover:border-slate-300"
              >
                <option v-for="opt in providerOptions" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>
            </div>

            <div>
              <label class="flex items-center gap-2 text-sm font-medium text-slate-700 mb-2">
                API Base URL
              </label>
              <input
                v-model="config.base_url"
                type="text"
                :data-error="Boolean(fieldErrors.base_url)"
                class="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-200 bg-white hover:border-slate-300 placeholder:text-slate-400"
                placeholder="https://api.deepseek.com"
              />
              <p v-if="fieldErrors.base_url" class="text-xs text-rose-600 mt-1">{{ fieldErrors.base_url }}</p>
            </div>

            <div class="space-y-2">
              <div class="flex items-center justify-between">
                <label class="text-sm font-medium text-slate-700">模型</label>
                <button
                  @click="loadModels"
                  :disabled="modelLoading || !canTestConfig"
                  type="button"
                  class="px-3 py-1.5 text-xs rounded-lg border border-slate-300 hover:bg-slate-100 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {{ modelLoading ? '拉取中...' : '拉取模型列表' }}
                </button>
              </div>
              <select
                v-if="activeProfileModels.length > 0"
                v-model="config.model"
                :data-error="Boolean(fieldErrors.model)"
                class="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-200 bg-white hover:border-slate-300"
              >
                <option v-for="model in activeProfileModels" :key="model" :value="model">
                  {{ model }}
                </option>
              </select>
              <input
                v-model="config.model"
                type="text"
                :data-error="Boolean(fieldErrors.model)"
                class="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-200 bg-white hover:border-slate-300 placeholder:text-slate-400"
                placeholder="手动输入模型名"
              />
              <textarea
                v-model="config.manual_models_text"
                rows="2"
                :data-error="Boolean(fieldErrors.manual_models)"
                class="w-full px-4 py-2 border border-slate-200 rounded-xl text-xs focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-200 bg-white hover:border-slate-300 placeholder:text-slate-400"
                placeholder="手动白名单（逗号或换行分隔），用于 /models 不可用时回退"
              ></textarea>
              <p v-if="fieldErrors.model" class="text-xs text-rose-600">{{ fieldErrors.model }}</p>
              <p v-if="fieldErrors.manual_models" class="text-xs text-rose-600">{{ fieldErrors.manual_models }}</p>
              <div
                v-if="modelFetchResult"
                class="text-xs p-2 rounded-lg border"
                :class="modelFetchResult.success ? 'bg-emerald-50 border-emerald-200 text-emerald-700' : 'bg-amber-50 border-amber-200 text-amber-700'"
              >
                {{ modelFetchResult.message }}<span v-if="modelFetchResult.source"> (source: {{ modelFetchResult.source }})</span>
                <div v-if="modelFetchResult.code" class="mt-1 opacity-80">{{ getErrorHint(modelFetchResult.code) }}</div>
              </div>
            </div>

            <div v-if="requiresApiKey">
              <label class="flex items-center gap-2 text-sm font-medium text-slate-700 mb-2">
                API Key
              </label>
              <input
                v-model="config.api_key"
                type="password"
                :data-error="Boolean(fieldErrors.api_key)"
                class="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-200 bg-white hover:border-slate-300 placeholder:text-slate-400"
                placeholder="sk-..."
              />
              <div v-if="config.has_api_key && !config.api_key" class="mt-2 flex items-center justify-between text-xs text-slate-500">
                <span>已保存密钥（未显示）。留空表示继续使用已保存密钥。</span>
                <button @click="clearStoredKey" type="button" class="text-rose-600 hover:text-rose-700">清空密钥</button>
              </div>
              <p v-if="fieldErrors.api_key" class="text-xs text-rose-600 mt-1">{{ fieldErrors.api_key }}</p>
            </div>
            <div v-else class="p-3 bg-blue-50 text-blue-700 text-xs rounded-xl flex items-center gap-2">
              Ollama 模式下无需 API Key（后端自动处理占位）。
            </div>

            <div v-if="isMiniMax25(config.model)" class="p-4 bg-amber-50 border border-amber-200 rounded-xl">
              <label class="flex items-center gap-2 text-sm font-medium text-amber-800 mb-2">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z"></path>
                </svg>
                账户类型
              </label>
              <select
                v-model="config.account_type"
                class="w-full px-4 py-2.5 border border-amber-300 rounded-xl text-sm focus:ring-2 focus:ring-amber-500 focus:border-amber-500 transition-all duration-200 bg-white"
              >
                <option value="free">免费用户 (20 RPM)</option>
                <option value="paid">付费用户 (500 RPM)</option>
              </select>
            </div>

            <div
              v-if="configTestResult"
              class="p-4 rounded-xl text-sm flex items-center gap-3"
              :class="configTestResult.success ? 'bg-emerald-50 text-emerald-700 border border-emerald-200' : 'bg-rose-50 text-rose-700 border border-rose-200'"
            >
              <svg class="w-5 h-5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path v-if="configTestResult.success" stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z"></path>
                <path v-else stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
              </svg>
              <div>
                <div>{{ configTestResult.message }}</div>
                <div v-if="configTestResult.code" class="text-xs opacity-80 mt-1">{{ configTestResult.hint }}</div>
              </div>
            </div>
          </div>

          <div v-else-if="activeSettingsTab === 'parser'" data-testid="settings-parser-panel" class="space-y-5">
            <div class="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-3">
              <label class="flex items-center gap-2 text-sm font-medium text-slate-700">
                解析引擎
              </label>
              <select
                v-model="parserConfig.parser_backend"
                :data-error="Boolean(fieldErrors.parser_backend)"
                class="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
              >
                <option v-for="opt in parserBackendOptions" :key="opt.value" :value="opt.value">
                  {{ opt.label }}
                </option>
              </select>
              <p v-if="fieldErrors.parser_backend" class="text-xs text-rose-600">{{ fieldErrors.parser_backend }}</p>

              <div>
                <label class="text-xs text-slate-600">HuggingFace 访问区域</label>
                <select
                  v-model="parserConfig.hf_endpoint_region"
                  :data-error="Boolean(fieldErrors.hf_endpoint_region)"
                  class="mt-1 w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
                >
                  <option v-for="opt in hfEndpointRegionOptions" :key="opt.value" :value="opt.value">
                    {{ opt.label }}
                  </option>
                </select>
                <p class="text-[11px] text-slate-500 mt-1">用于控制 `HF_ENDPOINT`，建议按所在网络环境选择。</p>
                <p v-if="fieldErrors.hf_endpoint_region" class="text-xs text-rose-600 mt-1">{{ fieldErrors.hf_endpoint_region }}</p>
              </div>

              <div>
                <label class="text-xs text-slate-600">任务超时（秒）</label>
                <input
                  data-testid="parser-timeout"
                  v-model.number="parserConfig.task_timeout_seconds"
                  type="range"
                  :data-error="Boolean(fieldErrors.task_timeout_seconds)"
                  min="60"
                  max="7200"
                  step="30"
                  class="mt-1 w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
                />
                <div class="mt-1 text-xs text-slate-600">{{ parserConfig.task_timeout_seconds }} s</div>
                <p class="text-[11px] text-slate-500 mt-1">控制前端等待与后端任务执行的统一超时阈值。</p>
                <p v-if="fieldErrors.task_timeout_seconds" class="text-xs text-rose-600 mt-1">{{ fieldErrors.task_timeout_seconds }}</p>
              </div>

              <div v-if="isHybridParser" class="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <label class="text-xs text-slate-600">噪声阈值 (0-1)</label>
                  <input
                    v-model.number="parserConfig.hybrid_noise_threshold"
                    type="number"
                    :data-error="Boolean(fieldErrors.hybrid_noise_threshold)"
                    min="0"
                    max="1"
                    step="0.01"
                    class="mt-1 w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
                  />
                  <p v-if="fieldErrors.hybrid_noise_threshold" class="text-xs text-rose-600 mt-1">{{ fieldErrors.hybrid_noise_threshold }}</p>
                </div>
                <div>
                  <label class="text-xs text-slate-600">Docling 跳过分数 (0-100)</label>
                  <input
                    v-model.number="parserConfig.hybrid_docling_skip_score"
                    type="number"
                    :data-error="Boolean(fieldErrors.hybrid_docling_skip_score)"
                    min="0"
                    max="100"
                    step="0.5"
                    class="mt-1 w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
                  />
                  <p v-if="fieldErrors.hybrid_docling_skip_score" class="text-xs text-rose-600 mt-1">{{ fieldErrors.hybrid_docling_skip_score }}</p>
                </div>
                <div>
                  <label class="text-xs text-slate-600">切换分差阈值 (0-50)</label>
                  <input
                    v-model.number="parserConfig.hybrid_switch_min_delta"
                    type="number"
                    :data-error="Boolean(fieldErrors.hybrid_switch_min_delta)"
                    min="0"
                    max="50"
                    step="0.5"
                    class="mt-1 w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
                  />
                  <p v-if="fieldErrors.hybrid_switch_min_delta" class="text-xs text-rose-600 mt-1">{{ fieldErrors.hybrid_switch_min_delta }}</p>
                </div>
                <div>
                  <label class="text-xs text-slate-600">Marker 最小长度（字符）</label>
                  <input
                    v-model.number="parserConfig.hybrid_marker_min_length"
                    type="number"
                    :data-error="Boolean(fieldErrors.hybrid_marker_min_length)"
                    min="0"
                    max="1000000"
                    step="1"
                    class="mt-1 w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
                  />
                  <p v-if="fieldErrors.hybrid_marker_min_length" class="text-xs text-rose-600 mt-1">{{ fieldErrors.hybrid_marker_min_length }}</p>
                </div>
              </div>

              <label v-if="usesMarkerPath" class="flex items-center justify-between gap-3 p-3 rounded-lg bg-white border border-slate-200">
                <div>
                  <p class="text-sm text-slate-700">优先使用 Marker Python API</p>
                  <p class="text-xs text-slate-500">失败时自动回退到 CLI</p>
                </div>
                <input v-model="parserConfig.marker_prefer_api" type="checkbox" class="h-4 w-4 rounded border-slate-300 text-blue-600 focus:ring-blue-500">
              </label>
            </div>

            <div class="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-3">
              <div class="flex items-start justify-between gap-3">
                <div>
                  <p class="text-sm font-medium text-slate-700">历史索引重建</p>
                  <p class="text-xs text-slate-500 mt-1">修复历史文件中“导图仅根节点”的索引问题，并返回逐文件日志。</p>
                </div>
                <div class="flex items-center gap-2">
                  <button
                    @click="runSourceIndexRebuild(true)"
                    :disabled="sourceIndexRebuildRunning"
                    class="px-3 py-1.5 text-xs rounded-lg border border-slate-300 hover:bg-white disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {{ sourceIndexRebuildRunning ? '执行中...' : '预览重建' }}
                  </button>
                  <button
                    @click="runSourceIndexRebuild(false)"
                    :disabled="sourceIndexRebuildRunning"
                    class="px-3 py-1.5 text-xs rounded-lg btn-primary disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {{ sourceIndexRebuildRunning ? '执行中...' : '执行重建' }}
                  </button>
                </div>
              </div>

              <div v-if="sourceIndexRebuildResult" class="space-y-2">
                <div class="flex flex-wrap items-center gap-2 text-[11px]">
                  <span class="px-2 py-1 rounded-md bg-slate-100 border border-slate-200 text-slate-600">
                    扫描 {{ sourceIndexRebuildResult.summary?.scanned || 0 }}
                  </span>
                  <span class="px-2 py-1 rounded-md bg-emerald-50 border border-emerald-200 text-emerald-700">
                    重建 {{ sourceIndexRebuildResult.summary?.rebuilt || 0 }}
                  </span>
                  <span class="px-2 py-1 rounded-md bg-slate-100 border border-slate-200 text-slate-600">
                    跳过 {{ sourceIndexRebuildResult.summary?.skipped || 0 }}
                  </span>
                  <span class="px-2 py-1 rounded-md bg-rose-50 border border-rose-200 text-rose-700">
                    失败 {{ sourceIndexRebuildResult.summary?.failed || 0 }}
                  </span>
                  <span class="text-slate-500">
                    完成于 {{ formatDateTime(sourceIndexRebuildResult.finished_at) || '--' }}
                  </span>
                </div>

                <div class="max-h-56 overflow-y-auto rounded-lg border border-slate-200 bg-white divide-y divide-slate-100">
                  <div
                    v-for="(item, idx) in sourceIndexRebuildItems"
                    :key="`${item.file_id || 'unknown'}-${idx}`"
                    class="px-3 py-2 text-xs"
                  >
                    <div class="flex items-center justify-between gap-2">
                      <div class="truncate text-slate-700 font-medium" :title="item.filename || item.file_id">{{ item.filename || item.file_id }}</div>
                      <span class="px-2 py-0.5 rounded-md border" :class="rebuildActionClass(item.action)">
                        {{ rebuildActionLabel(item.action) }}
                      </span>
                    </div>
                    <div class="text-slate-500 mt-1 break-all">{{ item.reason || '-' }}</div>
                    <div v-if="item.old_nodes !== undefined || item.new_nodes !== undefined" class="text-[11px] text-slate-400 mt-1">
                      old={{ item.old_nodes ?? '-' }}, new={{ item.new_nodes ?? '-' }}, mode={{ item.index_mode || '-' }}
                    </div>
                  </div>
                  <div v-if="sourceIndexRebuildItems.length === 0" class="px-3 py-3 text-xs text-slate-400">
                    本次没有可展示日志。
                  </div>
                </div>
              </div>
            </div>
          </div>

          <div v-else data-testid="settings-advanced-panel" class="space-y-6">
            <div class="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-4">
              <!-- Timeout Setting -->
              <div>
                <label class="text-sm font-medium text-slate-700">任务最大超时时间（秒）：{{ parserConfig.task_timeout_seconds }}</label>
                <div class="flex items-center gap-4 mt-2">
                  <input
                    data-testid="advanced-task-timeout-slider"
                    v-model.number="parserConfig.task_timeout_seconds"
                    type="range"
                    min="60"
                    max="7200"
                    step="60"
                    class="flex-1"
                    @input="scheduleAdvancedAutoSave"
                  />
                  <input
                    data-testid="advanced-task-timeout-input"
                    v-model.number="parserConfig.task_timeout_seconds"
                    type="number"
                    min="60"
                    max="7200"
                    class="w-24 text-sm rounded-lg border-slate-200 focus:border-indigo-500 focus:ring-1 focus:ring-indigo-500 p-2"
                    @input="scheduleAdvancedAutoSave"
                  />
                </div>
                <p class="text-xs text-slate-500 mt-1">控制长文档分析任务的最大等待时间，默认 600 秒。</p>
                <p v-if="fieldErrors.task_timeout_seconds" class="text-xs text-rose-600 mt-1">{{ fieldErrors.task_timeout_seconds }}</p>
              </div>

              <hr class="border-slate-200" />

              <div>
                <label class="text-sm font-medium text-slate-700">并发请求限制：{{ advancedConfig.engine_concurrency }}</label>
                <input
                  data-testid="advanced-concurrency"
                  v-model.number="advancedConfig.engine_concurrency"
                  type="range"
                  min="1"
                  max="10"
                  step="1"
                  class="mt-2 w-full"
                  @input="scheduleAdvancedAutoSave"
                />
                <p v-if="fieldErrors.engine_concurrency" class="text-xs text-rose-600 mt-1">{{ fieldErrors.engine_concurrency }}</p>
              </div>

              <div>
                <label class="text-sm font-medium text-slate-700">AI 思维发散度：{{ Number(advancedConfig.engine_temperature).toFixed(2) }}</label>
                <input
                  data-testid="advanced-temperature"
                  v-model.number="advancedConfig.engine_temperature"
                  type="range"
                  min="0"
                  max="1"
                  step="0.01"
                  class="mt-2 w-full"
                  @input="scheduleAdvancedAutoSave"
                />
                <p v-if="fieldErrors.engine_temperature" class="text-xs text-rose-600 mt-1">{{ fieldErrors.engine_temperature }}</p>
              </div>

              <div>
                <label class="text-sm font-medium text-slate-700">返回长度限制（Max Tokens）：{{ advancedConfig.engine_max_tokens }}</label>
                <input
                  data-testid="advanced-max-tokens"
                  v-model.number="advancedConfig.engine_max_tokens"
                  type="range"
                  min="1000"
                  max="16000"
                  step="100"
                  class="mt-2 w-full"
                  @input="scheduleAdvancedAutoSave"
                />
                <p v-if="fieldErrors.engine_max_tokens" class="text-xs text-rose-600 mt-1">{{ fieldErrors.engine_max_tokens }}</p>
              </div>
            </div>

            <div
              class="text-xs rounded-lg border px-3 py-2"
              :class="advancedAutoSaveState === 'saved'
                ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                : advancedAutoSaveState === 'error'
                  ? 'bg-rose-50 border-rose-200 text-rose-700'
                  : 'bg-slate-50 border-slate-200 text-slate-600'"
            >
              <span v-if="advancedAutoSaveState === 'saving'">正在自动保存高级参数...</span>
              <span v-else-if="advancedAutoSaveState === 'saved'">高级参数已自动保存并生效。</span>
              <span v-else-if="advancedAutoSaveState === 'error'">自动保存失败，请点击“保存全部配置”重试。</span>
              <span v-else>滑动参数后将自动写入后端配置。</span>
            </div>
          </div>
        </div>

        <div class="settings-modal-footer flex items-center justify-end gap-3 px-6 py-4 border-t border-slate-200/60 bg-slate-50 flex-shrink-0">
          <button
            v-if="activeSettingsTab === 'model'"
            @click="testConfig"
            :disabled="configLoading || !canTestConfig"
            class="px-5 py-2.5 text-sm btn-secondary rounded-xl disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <span class="flex items-center gap-2">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 10V3L4 14h7v7l9-11h-7z"></path>
              </svg>
              {{ configLoading ? '测试中...' : '测试连接' }}
            </span>
          </button>
          <button
            data-testid="settings-save-all"
            @click="saveConfig('all')"
            :disabled="isSettingsSaveDisabled"
            class="px-5 py-2.5 text-sm btn-primary rounded-xl disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {{ configLoading ? '保存中...' : '保存配置' }}
          </button>
        </div>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.toolbar-btn {
  padding: 0.25rem 0.625rem;
  font-size: 0.75rem;
  border-radius: 0.5rem;
  color: #475569;
  transition: color 0.2s ease, background-color 0.2s ease;
}

.toolbar-zoom {
  width: 1.75rem;
  height: 1.75rem;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  font-size: 0.9rem;
  font-weight: 600;
}

.settings-open-btn {
  position: relative;
  border-color: rgba(148, 163, 184, 0.35);
  background: rgba(255, 255, 255, 0.78);
  color: #334155;
  box-shadow: 0 1px 1px rgba(15, 23, 42, 0.04);
}

.settings-open-btn:hover {
  color: #3730a3;
  border-color: rgba(129, 140, 248, 0.45);
  background: rgba(238, 242, 255, 0.95);
}

.settings-tab-btn {
  padding: 0.375rem 0.75rem;
  font-size: 0.75rem;
  border-radius: 0.5rem;
  color: #64748b;
  border: 1px solid transparent;
  transition: color 0.2s ease, background-color 0.2s ease, border-color 0.2s ease;
}

.settings-tab-btn.active {
  background: #eff6ff;
  color: #1d4ed8;
  border-color: #bfdbfe;
}

.toolbar-btn:hover,
.settings-tab-btn:hover {
  color: #1e293b;
  background: #f1f5f9;
}

.skeleton-tree-wrap {
  position: relative;
  height: 150px;
  border: 1px solid #e2e8f0;
  border-radius: 14px;
  background: linear-gradient(180deg, #f8fafc 0%, #eef2ff 100%);
  overflow: hidden;
}

.skeleton-trunk {
  position: absolute;
  left: 50%;
  bottom: 12px;
  width: 5px;
  height: 112px;
  transform: translateX(-50%);
  border-radius: 9999px;
  background: linear-gradient(180deg, #cbd5e1 0%, #94a3b8 100%);
  opacity: 0.8;
}

.skeleton-branches {
  position: absolute;
  inset: 0;
}

.skeleton-branch {
  position: absolute;
  width: 82px;
  height: 4px;
  border-radius: 9999px;
  background: #cbd5e1;
  opacity: 0.45;
  transform-origin: center;
  transition: all 260ms ease;
}

.skeleton-branch.left {
  left: calc(50% - 82px);
  transform: rotate(-26deg);
}

.skeleton-branch.right {
  left: 50%;
  transform: rotate(26deg);
}

.skeleton-branch:nth-child(1) { top: 24px; }
.skeleton-branch:nth-child(2) { top: 30px; }
.skeleton-branch:nth-child(3) { top: 42px; }
.skeleton-branch:nth-child(4) { top: 48px; }
.skeleton-branch:nth-child(5) { top: 60px; }
.skeleton-branch:nth-child(6) { top: 66px; }
.skeleton-branch:nth-child(7) { top: 78px; }
.skeleton-branch:nth-child(8) { top: 84px; }
.skeleton-branch:nth-child(9) { top: 96px; }
.skeleton-branch:nth-child(10) { top: 102px; }
.skeleton-branch:nth-child(11) { top: 112px; }
.skeleton-branch:nth-child(12) { top: 118px; }
.skeleton-branch:nth-child(13) { top: 126px; }
.skeleton-branch:nth-child(14) { top: 132px; }
.skeleton-branch:nth-child(15) { top: 138px; }
.skeleton-branch:nth-child(16) { top: 144px; }

.skeleton-branch.active {
  background: linear-gradient(90deg, #60a5fa 0%, #3b82f6 100%);
  opacity: 1;
  box-shadow: 0 0 16px rgba(59, 130, 246, 0.35);
  animation: skeleton-breath 1.4s ease-in-out infinite;
}

:global(.dark) .skeleton-tree-wrap {
  border-color: rgba(100, 116, 139, 0.7);
  background: linear-gradient(180deg, rgba(51, 65, 85, 0.7) 0%, rgba(30, 41, 59, 0.82) 100%);
}

:global(.dark) .skeleton-trunk {
  background: linear-gradient(180deg, #64748b 0%, #475569 100%);
}

:global(.dark) .skeleton-branch {
  background: rgba(148, 163, 184, 0.4);
}

@keyframes skeleton-breath {
  0%, 100% { opacity: 0.65; }
  50% { opacity: 1; }
}

.failure-item {
  border: 1px solid #fecdd3;
  border-radius: 0.6rem;
  background: linear-gradient(180deg, #fff1f2 0%, #ffffff 100%);
  padding: 0.45rem 0.55rem;
}

.failure-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
}

.failure-jump-btn {
  flex-shrink: 0;
  border: 1px solid #fda4af;
  background: #fff1f2;
  color: #be123c;
  font-size: 0.66rem;
  line-height: 1;
  font-weight: 700;
  border-radius: 0.45rem;
  padding: 0.2rem 0.45rem;
  transition: all 0.15s ease;
}

.failure-jump-btn:hover {
  background: #ffe4e6;
  border-color: #fb7185;
}

.failure-topic {
  display: block;
  font-size: 0.72rem;
  font-weight: 700;
  color: #be123c;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.failure-error {
  margin-top: 0.2rem;
  font-size: 0.68rem;
  line-height: 1.2rem;
  color: #9f1239;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
