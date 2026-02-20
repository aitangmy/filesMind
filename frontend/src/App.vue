<script setup>
import { ref, onMounted, onUnmounted, computed, nextTick, watch } from 'vue';
import VuePdfEmbed from 'vue-pdf-embed';
import 'vue-pdf-embed/dist/styles/annotationLayer.css';
import 'vue-pdf-embed/dist/styles/textLayer.css';
import MindMap from './components/MindMap.vue';
import VirtualPdfViewer from './components/VirtualPdfViewer.vue';

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

const defaultParserConfig = () => ({
  parser_backend: 'docling',
  hybrid_noise_threshold: 0.2,
  hybrid_docling_skip_score: 70,
  hybrid_switch_min_delta: 2,
  hybrid_marker_min_length: 200,
  marker_prefer_api: false,
  task_timeout_seconds: 600
});

const fileInput = ref(null);
const isLoading = ref(false);
const errorMsg = ref('');
const DEFAULT_MINDMAP_PLACEHOLDER = '# Welcome to FilesMind\n\n- **Upload a PDF** to generate a Deep Knowledge Map\n- Powered by **IBM Docling** & **DeepSeek R1**\n- **Recursive Reasoning** for profound insights';
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

// PDF 交互状态
const pdfScale = ref(1.0);
const pdfScrollContainer = ref(null);
const legacyPdfScrollContainer = ref(null);

const zoomInPdf = () => {
  if (pdfScale.value < 3.0) pdfScale.value = Number((pdfScale.value + 0.25).toFixed(2));
};

const zoomOutPdf = () => {
  if (pdfScale.value > 0.5) pdfScale.value = Number((pdfScale.value - 0.25).toFixed(2));
};

const toggleFullscreenPdf = () => {
  if (!pdfScrollContainer.value) return;
  if (!document.fullscreenElement) {
    pdfScrollContainer.value.requestFullscreen().catch(err => {
      console.warn(`Error attempting to enable fullscreen: ${err.message}`);
    });
  } else {
    document.exitFullscreen();
  }
};

// 导图交互状态
const mindMapRef = ref(null);

const triggerExportPng = () => {
  if (mindMapRef.value?.exportPNG) mindMapRef.value.exportPNG();
};

const triggerExportMd = () => {
  if (mindMapRef.value?.exportMarkdown) mindMapRef.value.exportMarkdown();
};

const triggerExportXmind = () => {
  if (mindMapRef.value?.exportXMind) mindMapRef.value.exportXMind();
};

const triggerToggleTheme = () => {
  if (mindMapRef.value?.toggleTheme) mindMapRef.value.toggleTheme();
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
      errorMsg.value = "请上传 PDF 格式的文件";
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
const showSettings = ref(false);
const configLoading = ref(false);
const configTestResult = ref(null);
const modelFetchResult = ref(null);
const modelLoading = ref(false);
const configImportInput = ref(null);
const configOperationMsg = ref('');
const toasts = ref([]);
const toastTimers = new Map();
let toastSeq = 0;

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
  MISSING_PROFILE_NAME: '请填写配置档案名称',
  PROFILE_NAME_TOO_LONG: '配置档案名称不应超过 60 个字符',
  MISSING_BASE_URL: '请填写 API Base URL',
  INVALID_BASE_URL: 'API Base URL 需以 http:// 或 https:// 开头',
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
  INVALID_HYBRID_NOISE_THRESHOLD: '噪声阈值必须是数字',
  OUT_OF_RANGE_HYBRID_NOISE_THRESHOLD: '噪声阈值需在 0 到 1 之间',
  INVALID_HYBRID_DOCLING_SKIP_SCORE: 'Docling 跳过分数必须是数字',
  OUT_OF_RANGE_HYBRID_DOCLING_SKIP_SCORE: 'Docling 跳过分数需在 0 到 100 之间',
  INVALID_HYBRID_SWITCH_MIN_DELTA: '切换分差阈值必须是数字',
  OUT_OF_RANGE_HYBRID_SWITCH_MIN_DELTA: '切换分差阈值需在 0 到 50 之间',
  INVALID_HYBRID_MARKER_MIN_LENGTH: 'Marker 最小长度必须是整数',
  OUT_OF_RANGE_HYBRID_MARKER_MIN_LENGTH: 'Marker 最小长度需在 0 到 1000000 之间',
  INVALID_TASK_TIMEOUT_SECONDS: '任务超时时间必须是整数',
  OUT_OF_RANGE_TASK_TIMEOUT_SECONDS: '任务超时时间需在 60 到 7200 秒之间',
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
    errors.hybrid_marker_min_length = 'Marker 最小长度需为 0 到 1000000 的整数';
  }

  const taskTimeout = Number(parserConfig.value.task_timeout_seconds);
  if (!Number.isInteger(taskTimeout) || taskTimeout < 60 || taskTimeout > 7200) {
    errors.task_timeout_seconds = '任务超时时间需为 60 到 7200 的整数（秒）';
  }

  return errors;
});

const hasValidationErrors = computed(() => Object.keys(fieldErrors.value).length > 0);
const canTestConfig = computed(() => Boolean(config.value.base_url?.trim() && config.value.model?.trim()) && !Boolean(fieldErrors.value.base_url || fieldErrors.value.model || fieldErrors.value.api_key));
const parserErrorKeys = [
  'parser_backend',
  'task_timeout_seconds',
  'hybrid_noise_threshold',
  'hybrid_docling_skip_score',
  'hybrid_switch_min_delta',
  'hybrid_marker_min_length'
];
const llmErrorKeys = ['base_url', 'model', 'api_key', 'manual_models'];

const hasParserValidationErrors = computed(() => parserErrorKeys.some((key) => Boolean(fieldErrors.value[key])));
const hasLlmValidationErrors = computed(() => llmErrorKeys.some((key) => Boolean(fieldErrors.value[key])));

const isParserSaveDisabled = computed(() => configLoading.value || hasParserValidationErrors.value);
const isLlmSaveDisabled = computed(() => configLoading.value || hasLlmValidationErrors.value);

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
    hybrid_noise_threshold: Number(parserConfig.value.hybrid_noise_threshold ?? 0.2),
    hybrid_docling_skip_score: Number(parserConfig.value.hybrid_docling_skip_score ?? 70),
    hybrid_switch_min_delta: Number(parserConfig.value.hybrid_switch_min_delta ?? 2),
    hybrid_marker_min_length: Number(parserConfig.value.hybrid_marker_min_length ?? 200),
    marker_prefer_api: Boolean(parserConfig.value.marker_prefer_api),
    task_timeout_seconds: Number(parserConfig.value.task_timeout_seconds ?? 600)
  };
  return {
    active_profile_id: activeProfileId.value,
    parser,
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
    const response = await fetch('/api/config/export');
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
      parser: parsed?.parser || defaultParserConfig()
    };
    const response = await fetch('/api/config/import', {
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
      parser: defaultParserConfig()
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

  return {
    active_profile_id: active?.id || '',
    profiles: normalizedProfiles,
    parser
  };
};

// 轮询相关
const currentTaskId = ref(null);
const pollTimer = ref(null);
const taskStatus = ref('');
const taskProgress = ref(0);
const taskMessage = ref('');
const treeData = ref(null);

const showLlmSettings = ref(false);
const showParserSettings = ref(false);

const flatNodes = ref([]);
const selectedNode = ref(null);
const sourceView = ref({
  loading: false,
  error: '',
  topic: '',
  lineStart: 0,
  lineEnd: 0,
  excerptLines: [],
  pdfPageNo: null,
  pdfBbox: null,
  pdfYRatio: null,
  hasPreciseAnchor: true,
  parserBackend: 'unknown'
});
let sourceRequestToken = 0;
let pdfNavigateTimer = null;

const POLL_INTERVAL = 1500;
let pollStartTime = 0;
const isUploadStage = computed(() => {
  if (!isLoading.value) return false;
  if (currentTaskId.value) return false;
  return ['pending', 'uploading'].includes(String(taskStatus.value || '').toLowerCase());
});
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
const showPdfPane = computed(() => viewportWidth.value > 1024);
const showMindmapCanvas = computed(() => Boolean(currentFileId.value) && isMindmapReady.value);
const workspaceGridStyle = computed(() => {
  if (!showPdfPane.value) {
    return { gridTemplateColumns: 'minmax(0, 1fr)' };
  }
  return {
    gridTemplateColumns: `minmax(0, 1fr) 0.625rem minmax(320px, ${pdfPaneWidth.value}px)`
  };
});
const topNoticeVisible = computed(() => isLoading.value || Boolean(errorMsg.value));

// 加载历史记录
const loadHistory = async () => {
  try {
    const response = await fetch('/api/history');
    if (response.ok) {
      history.value = await response.json();
    }
  } catch (err) {
    console.error('加载历史失败:', err);
  }
};

const resetSourceView = () => {
  sourceRequestToken += 1;
  selectedNode.value = null;
  if (pdfNavigateTimer) {
    clearTimeout(pdfNavigateTimer);
    pdfNavigateTimer = null;
  }
  sourceView.value = {
    loading: false,
    error: '',
    topic: '',
    lineStart: 0,
    lineEnd: 0,
    excerptLines: [],
    pdfPageNo: null,
    pdfBbox: null,
    pdfYRatio: null,
    hasPreciseAnchor: true,
    parserBackend: 'unknown'
  };
};

const pdfSourceUrl = computed(() => {
  if (!currentFileId.value) return '';
  return `/api/file/${currentFileId.value}/pdf`;
});

const clampRatio = (ratio) => {
  const n = Number(ratio);
  if (!Number.isFinite(n)) return 0.3;
  if (n < 0) return 0;
  // Navigation logic handled by VirtualPdfViewer component
  if (n > 1) return 1;
  return n;
};

const findLegacyPdfPageElement = (pageNo) => {
  if (!Number.isInteger(pageNo) || pageNo < 1) return null;
  const root = document.getElementById('source-pdf-legacy');
  if (!root) return null;

  // vue-pdf-embed declares page container IDs as `${id}-${pageNumber}`.
  const direct = document.getElementById(`source-pdf-legacy-${pageNo}`);
  if (direct) return direct;

  const selectors = [
    `[id="source-pdf-legacy-${pageNo}"]`,
    `[data-page-number="${pageNo}"]`,
    `[data-page="${pageNo}"]`,
    `[data-page-index="${pageNo - 1}"]`,
    `.vue-pdf-embed__page:nth-of-type(${pageNo})`,
  ];
  for (const selector of selectors) {
    const hit = root.querySelector(selector);
    if (hit) return hit;
  }

  const fallbackPages = root.querySelectorAll('[id^="source-pdf-legacy-"], .vue-pdf-embed__page, .page');
  if (fallbackPages.length >= pageNo) {
    return fallbackPages[pageNo - 1];
  }
  return null;
};

const performLegacyPdfNavigation = async (attempt = 0) => {
  if (systemFeatures.value.FEATURE_VIRTUAL_PDF) return;
  const pageNo = Number(sourceView.value.pdfPageNo);
  if (!Number.isInteger(pageNo) || pageNo < 1) return;

  await nextTick();
  const container = legacyPdfScrollContainer.value || pdfScrollContainer.value;
  if (!container) return;

  const target = findLegacyPdfPageElement(pageNo);
  if (!target) {
    if (attempt < 12) {
      if (pdfNavigateTimer) clearTimeout(pdfNavigateTimer);
      pdfNavigateTimer = setTimeout(() => {
        void performLegacyPdfNavigation(attempt + 1);
      }, 120);
    }
    return;
  }

  const containerRect = container.getBoundingClientRect();
  const targetRect = target.getBoundingClientRect();
  const targetTop = targetRect.top - containerRect.top + container.scrollTop;
  const targetHeight = target.clientHeight || targetRect.height || 0;
  const ratio = clampRatio(sourceView.value.pdfYRatio);
  const top = Math.max(0, targetTop + targetHeight * ratio - container.clientHeight * 0.3);
  container.scrollTo({
    top,
    behavior: attempt === 0 ? 'smooth' : 'auto',
  });
};

const schedulePdfNavigation = () => {
  if (systemFeatures.value.FEATURE_VIRTUAL_PDF) return;
  if (pdfNavigateTimer) {
    clearTimeout(pdfNavigateTimer);
    pdfNavigateTimer = null;
  }
  pdfNavigateTimer = setTimeout(() => {
    void performLegacyPdfNavigation(0);
  }, 0);
};

const loadTreeForFile = async (fileId) => {
  if (!fileId) {
    treeData.value = null;
    flatNodes.value = [];
    return;
  }
  try {
    const response = await fetch(`/api/file/${fileId}/tree`);
    if (!response.ok) {
      throw new Error('无法加载节点索引');
    }
    const data = await response.json();
    treeData.value = data.tree || null;
    flatNodes.value = Array.isArray(data.flat_nodes) ? data.flat_nodes : [];
  } catch (err) {
    treeData.value = null;
    flatNodes.value = [];
    console.error('加载节点树失败:', err);
  }
};

const loadNodeSource = async (nodeId) => {
  if (!currentFileId.value || !nodeId) return;
  const requestToken = ++sourceRequestToken;
  const requestedFileId = currentFileId.value;
  sourceView.value.loading = true;
  sourceView.value.error = '';
  try {
    const response = await fetch(`/api/file/${requestedFileId}/node/${nodeId}/source?context_lines=2&max_lines=120`);
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
      excerptLines: Array.isArray(data.excerpt_lines) ? data.excerpt_lines : [],
      pdfPageNo: data.pdf_page_no || null,
      pdfBbox: data.pdf_bbox || null,
      pdfYRatio: Number.isFinite(Number(data.pdf_y_ratio)) ? Number(data.pdf_y_ratio) : null,
      hasPreciseAnchor: data.capabilities?.has_precise_anchor ?? false,
      parserBackend: data.capabilities?.parser_backend ?? 'unknown'
    };

    if (data.pdf_page_no) {
      schedulePdfNavigation();
    }
  } catch (err) {
    if (requestToken !== sourceRequestToken || currentFileId.value !== requestedFileId) {
      return;
    }
    sourceView.value.loading = false;
    sourceView.value.error = err.message || '节点原文加载失败';
  }
};

const handleMindmapNodeClick = async (payload) => {
  if (!payload?.nodeId) return;
  selectedNode.value = payload;
  await loadNodeSource(payload.nodeId);
};

const handleMindmapFeedback = (payload) => {
  const message = payload?.message || '操作失败，请重试';
  const type = payload?.type || 'info';
  notify(type, message);
};

// PDF logic decoupled to component

const extractPdfErrorMessage = (err, fallback = 'PDF 加载失败') => {
  if (!err) return fallback;
  const raw = (() => {
    if (typeof err === 'string' && err.trim()) return err.trim();
    if (typeof err?.message === 'string' && err.message.trim()) return err.message.trim();
    if (typeof err?.detail?.message === 'string' && err.detail.message.trim()) return err.detail.message.trim();
    if (typeof err?.reason === 'string' && err.reason.trim()) return err.reason.trim();
    return '';
  })();
  const lower = raw.toLowerCase();
  if (lower.includes('missing pdf') || lower.includes('404') || lower.includes('not found')) {
    return 'PDF 文件不存在或已被删除（404）';
  }
  if (lower.includes('invalid pdf') || lower.includes('format error') || lower.includes('unexpected server response')) {
    return 'PDF 文件损坏或格式不受支持';
  }
  if (lower.includes('network') || lower.includes('failed to fetch')) {
    return '网络异常，PDF 加载失败';
  }
  return raw || fallback;
};

const setPdfError = (err, fallback = 'PDF 加载失败') => {
  sourceView.value.error = extractPdfErrorMessage(err, fallback);
};

// Compatibility logic for legacy PDF embed
const handlePdfLoaded = () => {
  schedulePdfNavigation();
};
const handlePdfRendered = () => {
  schedulePdfNavigation();
};
const handlePdfRenderError = (err, fallback = 'PDF 渲染失败') => {
  setPdfError(err, fallback);
};

watch(
  [() => sourceView.value.pdfPageNo, () => sourceView.value.pdfYRatio, () => systemFeatures.value.FEATURE_VIRTUAL_PDF],
  ([pageNo]) => {
    if (pageNo) schedulePdfNavigation();
  }
);

watch(
  () => pdfScale.value,
  () => {
    if (sourceView.value.pdfPageNo) schedulePdfNavigation();
  }
);

// 加载文件内容
const loadFile = async (fileId) => {
  try {
    resetSourceView();
    const response = await fetch(`/api/file/${fileId}`);
    if (!response.ok) {
      throw new Error('文件加载失败');
    }
    const data = await response.json();
    mindmapData.value = data.content;
    isMindmapReady.value = true;
    currentFileId.value = fileId;
    await loadTreeForFile(fileId);
    isLoading.value = false;
  } catch (err) {
    errorMsg.value = err.message;
    console.error('加载文件失败:', err);
  }
};

// 删除文件
const deleteFile = async (fileId, event) => {
  event.stopPropagation();
  if (!confirm('确定要删除这个文件吗？')) return;
  
  try {
    const response = await fetch(`/api/file/${fileId}`, {
      method: 'DELETE'
    });
    if (response.ok) {
      await loadHistory();
      if (currentFileId.value === fileId) {
        mindmapData.value = DEFAULT_MINDMAP_PLACEHOLDER;
        isMindmapReady.value = false;
        currentFileId.value = null;
        treeData.value = null;
        flatNodes.value = [];
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
    clearInterval(pollTimer.value);
    pollTimer.value = null;
  }
  currentTaskId.value = null;
  pollStartTime = 0;
};

onUnmounted(() => {
  cleanupPoll();
  stopPdfResizing();
  stopSidebarResizing();
  window.removeEventListener('resize', updateViewport);
  if (pdfNavigateTimer) {
    clearTimeout(pdfNavigateTimer);
    pdfNavigateTimer = null;
  }
  for (const timer of toastTimers.values()) {
    clearTimeout(timer);
  }
  toastTimers.clear();
});

// 轮询任务状态
const pollTaskStatus = async (taskId) => {
  try {
    const response = await fetch(`/api/task/${taskId}`);
    
    if (response.status === 404) {
      cleanupPoll();
      isLoading.value = false;
      errorMsg.value = '任务状态不存在，可能是后端重启导致。请重新上传或从历史记录打开文件。';
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
    
    if (data.status === 'completed') {
      cleanupPoll();
      mindmapData.value = data.result;
      isMindmapReady.value = true;
      if (data.file_id) {
        currentFileId.value = data.file_id;
        await loadTreeForFile(data.file_id);
      }
      isLoading.value = false;
      uploadProgress.value = 0;
      if (fileInput.value) fileInput.value.value = '';
      await loadHistory();
    } 
    else if (data.status === 'failed') {
      cleanupPoll();
      isMindmapReady.value = false;
      errorMsg.value = data.error || '处理失败';
      isLoading.value = false;
      uploadProgress.value = 0;
      await loadHistory();
    }
    else if (data.status === 'cancelled') {
      cleanupPoll();
      isMindmapReady.value = false;
      errorMsg.value = data.message || '任务已取消';
      isLoading.value = false;
      uploadProgress.value = 0;
      await loadHistory();
    }
    
  } catch (err) {
    console.error("Poll error:", err);
  }
};

const requestTaskCancel = async (taskId, reason = '已手动取消') => {
  if (!taskId) return;
  try {
    const response = await fetch(`/api/task/${taskId}/cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ reason })
    });
    if (!response.ok) {
      console.warn('取消任务请求失败:', response.status);
    }
  } catch (err) {
    console.warn('取消任务请求异常:', err);
  }
};

const checkPollTimeout = async () => {
  if (pollStartTime && Date.now() - pollStartTime > pollTimeoutMs.value) {
    const timeoutSeconds = Math.round(pollTimeoutMs.value / 1000);
    const taskId = currentTaskId.value;
    await requestTaskCancel(taskId, `前端等待超时（${timeoutSeconds}秒）自动取消`);
    cleanupPoll();
    isMindmapReady.value = false;
    errorMsg.value = `处理超时（>${timeoutSeconds}秒），任务已取消`;
    isLoading.value = false;
    await loadHistory();
  }
};

const uploadPdfFile = (file) => new Promise((resolve, reject) => {
  const formData = new FormData();
  formData.append('file', file);

  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/upload');
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

  xhr.onerror = () => reject(new Error('网络异常，上传失败'));
  xhr.onabort = () => reject(new Error('上传已取消'));
  xhr.send(formData);
});

const handleSelectedFile = async (file, clearInput) => {
  if (!file) return;
  if (!isPdfFile(file)) {
    errorMsg.value = '请上传 PDF 格式的文件';
    if (typeof clearInput === 'function') clearInput();
    return;
  }

  // [新增] 硬件性能检查拦截
  if (hardwareType.value === 'cpu') {
      const confirmCpu = window.confirm(
          "⚠️ 性能效能提醒\n\n" +
          "服务器当前正在使用 CPU 进行运算。\n" +
          "解析大文件可能需要较长时间（预计 2-5 分钟）。\n\n" +
          "建议使用支持 GPU (CUDA) 或 Mac (MPS) 的设备以获得最佳速度。\n\n" +
          "是否仍要继续上传？"
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
  resetSourceView();
  isMindmapReady.value = false;
  errorMsg.value = '';
  
  taskStatus.value = 'pending';
  taskProgress.value = 0;
  uploadProgress.value = 0;
  taskMessage.value = '正在上传文件...';

  try {
    const data = await uploadPdfFile(file);
    
    if (data.error) {
      throw new Error(data.error);
    }

    if (data.is_duplicate) {
      if (data.status === 'completed') {
        mindmapData.value = data.existing_md;
        isMindmapReady.value = true;
        currentFileId.value = data.file_id;
        await loadTreeForFile(data.file_id);
        isLoading.value = false;
        uploadProgress.value = 0;
        notify('info', '该文件已存在，已直接加载历史结果');
        if (typeof clearInput === 'function') clearInput();
        return;
      }

      if (data.status === 'processing' && data.task_id) {
        uploadProgress.value = 0;
        isMindmapReady.value = false;
        currentTaskId.value = data.task_id;
        currentFileId.value = data.file_id;
        pollStartTime = Date.now();
        taskStatus.value = 'processing';
        taskMessage.value = data.message || '检测到相同文件正在处理中，已连接到现有任务';

        pollTimer.value = setInterval(() => {
          void checkPollTimeout();
          if (currentTaskId.value) {
            void pollTaskStatus(currentTaskId.value);
          }
        }, POLL_INTERVAL);
        void pollTaskStatus(data.task_id);
        await loadHistory();
        return;
      }
    }

    if (!data.task_id) {
      throw new Error('未获取到任务ID');
    }

    uploadProgress.value = 0;
    isMindmapReady.value = false;
    currentTaskId.value = data.task_id;
    currentFileId.value = data.file_id;
    pollStartTime = Date.now();
    taskStatus.value = 'processing';
    
    pollTimer.value = setInterval(() => {
      void checkPollTimeout();
      if (currentTaskId.value) {
        void pollTaskStatus(currentTaskId.value);
      }
    }, POLL_INTERVAL);
    
    void pollTaskStatus(data.task_id);
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
    await requestTaskCancel(currentTaskId.value, '用户手动取消任务');
  }
  cleanupPoll();
  isLoading.value = false;
  uploadProgress.value = 0;
  taskProgress.value = 0;
  taskMessage.value = '任务已取消';
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

onMounted(() => {
  updateViewport();
  window.addEventListener('resize', updateViewport);
  loadHistory();
  loadConfig();
  checkHardware();
  loadFeatures();
});

// 获取系统功能开关
const loadFeatures = async () => {
  try {
    const response = await fetch('/api/system/features');
    if (response.ok) {
      const data = await response.json();
      systemFeatures.value = { ...systemFeatures.value, ...data };
    }
    const urlParams = new URLSearchParams(window.location.search);
    if (urlParams.has('vviewer')) {
      const v = urlParams.get('vviewer');
      systemFeatures.value.FEATURE_VIRTUAL_PDF = v === '1' || v === 'true';
    }
  } catch (err) {
    console.warn("Features set fetch failed:", err);
  }
};

// 检查硬件状态
const checkHardware = async () => {
    try {
        const response = await fetch('/api/system/hardware');
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
    const response = await fetch('/api/config');
    if (response.ok) {
      const data = await response.json();
      const normalized = normalizeConfigStore(data);
      profiles.value = normalized.profiles;
      parserConfig.value = normalized.parser;
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
const saveConfig = async (scope = 'all') => {
  let keys = [];
  if (scope === 'parser') keys = parserErrorKeys;
  else if (scope === 'llm') keys = llmErrorKeys;
  else keys = Object.keys(fieldErrors.value);

  const scopedError = firstFieldErrorMessage(keys);
  if (scopedError) {
    notify('warning', scopedError || '请先修正配置项');
    return;
  }
  if (scope === 'all' && hasValidationErrors.value) {
    const firstMessage = Object.values(fieldErrors.value)[0] || '请先修正配置项';
    notify('warning', firstMessage);
    return;
  }
  configLoading.value = true;
  configTestResult.value = null;
  try {
    const payload = buildConfigStorePayload({
      persistCurrentProfile: scope !== 'parser'
    });
    const response = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await parseResponsePayload(response);
    if (isEmptyServerErrorResponse(response, data)) {
      notify('error', backendUnavailableMessage);
      return;
    }
    if (response.ok && data?.success !== false) {
      await loadConfig();
      showLlmSettings.value = false;
      showParserSettings.value = false;
      notify('success', '配置已保存');
      configOperationMsg.value = '配置已保存并生效';
    } else {
      const detail = data?.detail || data;
      const code = detail?.code || data?.code || (response.ok ? 'UNKNOWN_ERROR' : `HTTP_${response.status}`);
      const message = typeof detail === 'string'
        ? detail
        : (detail?.message || data?.message || response.statusText || '未知错误');
      notify('error', `保存失败: ${getErrorHint(code, message)} (${code})`);
    }
  } catch (err) {
    notify('error', `保存失败: ${err.message || backendUnavailableMessage}`);
  }
  configLoading.value = false;
};

// 测试配置
const testConfig = async () => {
  if (!canTestConfig.value) {
    const firstMessage = Object.values(fieldErrors.value)[0] || '请先修正配置项';
    notify('warning', firstMessage);
    return;
  }
  configLoading.value = true;
  configTestResult.value = null;
  try {
    const response = await fetch('/api/config/test', {
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
    const firstMessage = Object.values(fieldErrors.value)[0] || '请先修正配置项';
    notify('warning', firstMessage);
    return;
  }
  modelLoading.value = true;
  modelFetchResult.value = null;
  try {
    const response = await fetch('/api/config/models', {
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
</script>

<template>
  <div
    ref="appShellRef"
    class="app-shell h-screen flex font-sans overflow-hidden relative"
    @dragover.prevent="onDragOver"
    @dragleave.prevent="onDragLeave"
    @drop.prevent="onDrop"
  >
    <!-- 全局拖拽悬浮层 -->
    <div
      v-if="isDraggingFile"
      class="absolute inset-0 z-[100] bg-blue-500/10 backdrop-blur-sm m-4 rounded-3xl border-4 border-dashed border-blue-400 flex items-center justify-center transition-all duration-300 pointer-events-none"
    >
      <div class="bg-white/95 px-10 py-8 rounded-2xl shadow-2xl flex flex-col items-center">
        <svg class="w-20 h-20 text-blue-500 mb-4 animate-bounce" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 16.5V9.75m0 0l3 3m-3-3l-3 3M6.75 19.5a4.5 4.5 0 01-1.41-8.775 5.25 5.25 0 0110.233-2.33 3 3 0 013.758 3.848A3.752 3.752 0 0118 19.5H6.75z"></path>
        </svg>
        <h2 class="text-2xl font-bold text-slate-700 tracking-wide">释放鼠标，立即解析文档</h2>
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
      :class="showSidebar ? 'opacity-100 border-r border-slate-200/60' : 'opacity-0 border-r-0 pointer-events-none'"
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
      <div class="flex-grow overflow-y-auto p-3 bg-slate-50/50">
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
              <div class="flex-grow min-w-0">
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
                    <span v-if="item.status === 'completed'">✓</span>
                    <span v-else-if="item.status === 'processing'">⟳</span>
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
      <div class="p-3 border-t border-slate-200/60 bg-gradient-to-r from-slate-50 to-blue-50/30">
        <div class="text-[10px] text-slate-400 text-center">
          Powered by <span class="font-medium text-slate-500">IBM Docling</span> & <span class="font-medium text-slate-500">DeepSeek</span>
        </div>
      </div>
    </aside>

    <div
      v-if="showSidebar"
      class="w-2 cursor-col-resize bg-slate-200/40 hover:bg-blue-100/70 transition-colors relative flex items-center justify-center"
      :class="{ 'bg-blue-100/90': isSidebarResizing }"
      @mousedown="startSidebarResizing"
    >
      <div class="h-14 w-[2px] rounded-full bg-slate-400/40"></div>
      <div class="absolute inset-y-0 left-0 right-0 flex items-center justify-center">
        <div class="h-7 w-1 rounded-full bg-blue-500/35"></div>
      </div>
    </div>

    <!-- 主内容区 -->
    <div class="flex-grow flex flex-col min-w-0">
      <!-- 顶部导航栏 -->
      <header class="app-toolbar flex-shrink-0 backdrop-blur-xl border-b border-slate-200/40 shadow-sm">
        <div class="h-14 flex items-center justify-between px-4">
          <div class="flex items-center gap-3">
            <button
              @click="showSidebar = !showSidebar"
              class="p-2 rounded-xl text-slate-500 hover:bg-slate-100/80 hover:text-slate-700 transition-all duration-200"
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
              class="hidden md:inline-flex text-[11px] px-2 py-1 rounded-full bg-slate-100 text-slate-500"
            >
              平板宽度已自动隐藏原文区
            </span>
            <button
              @click="showParserSettings = true"
              class="flex items-center gap-2 px-3 py-2 rounded-xl text-slate-500 hover:text-blue-600 hover:bg-blue-50/80 transition-all duration-200 border border-transparent hover:border-blue-100 font-medium"
              title="解析策略配置"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"></path>
              </svg>
              <span class="text-[13px] hidden sm:inline">解析策略</span>
            </button>

            <div class="w-[1px] h-4 bg-slate-200 mx-1"></div>

            <button
              @click="showLlmSettings = true"
              class="flex items-center gap-2 px-3 py-2 rounded-xl text-slate-500 hover:text-indigo-600 hover:bg-indigo-50/80 transition-all duration-200 border border-transparent hover:border-indigo-100 font-medium"
              title="AI 模型配置"
            >
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"></path>
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 2v2m0 16v2M4.929 4.929l1.414 1.414m11.314 11.314l1.414 1.414M2 12h2m16 0h2M6.343 17.657l-1.414 1.414M17.657 6.343l1.414-1.414"></path>
              </svg>
              <span class="text-[13px] hidden sm:inline">AI 模型</span>
            </button>
          </div>
        </div>

        <div v-if="topNoticeVisible" class="px-4 pb-3 space-y-2">
          <div
            v-if="isLoading"
            class="rounded-xl border border-blue-200/70 bg-gradient-to-r from-blue-50 to-indigo-50 px-3 py-2 flex items-center gap-2"
          >
            <div class="flex-1 h-2 bg-white/70 rounded-full overflow-hidden">
              <div
                class="brand-progress h-full rounded-full transition-all duration-300 relative overflow-hidden"
                :class="{ 'animate-pulse': isUploadStage }"
                :style="{ width: `${effectiveTaskProgress}%` }"
              >
                <div class="absolute inset-0 bg-white/20 animate-pulse"></div>
              </div>
            </div>
            <span class="text-[11px] font-semibold text-slate-700 w-11 text-right">{{ Math.round(effectiveTaskProgress) }}%</span>
            <span class="text-[11px] text-slate-500 max-w-[240px] truncate">{{ taskMessage }}</span>
            <button @click="cancelTask" class="p-1 rounded-md text-slate-400 hover:text-rose-500 hover:bg-rose-50 transition-all duration-200">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
              </svg>
            </button>
          </div>
          <div
            v-if="errorMsg"
            class="rounded-xl border border-rose-200/80 bg-gradient-to-r from-rose-50 to-orange-50 px-3 py-2 flex items-center gap-2"
          >
            <div class="p-1 rounded-md bg-rose-100">
              <svg class="w-4 h-4 text-rose-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
              </svg>
            </div>
            <span class="text-xs font-medium text-rose-700 truncate">{{ errorMsg }}</span>
            <button @click="errorMsg = ''" class="ml-auto p-1 rounded-md text-rose-400 hover:text-rose-600 hover:bg-rose-100 transition-all duration-200">
              <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
              </svg>
            </button>
          </div>
        </div>
      </header>

      <!-- 主内容区域（双栏分割容器） -->
      <main class="flex-grow p-6 overflow-hidden bg-slate-100/50 flex">
        <div
          ref="workspaceLayoutRef"
          class="h-full w-full grid items-stretch overflow-hidden"
          :style="workspaceGridStyle"
        >
          <!-- 左侧：思维导图 -->
          <div class="app-card elev-md min-w-0 h-full flex flex-col rounded-xl border border-slate-200/40 overflow-hidden relative">
            <div class="absolute top-4 right-4 flex items-center gap-1 z-20 bg-white/70 backdrop-blur-md p-1 rounded-xl shadow-sm border border-slate-200/40">
              <button @click="triggerExportMd" class="p-2 rounded-lg text-slate-500 hover:text-slate-700 hover:bg-slate-100 transition-colors" title="Export as Markdown">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
              </button>
              <button @click="triggerExportXmind" class="p-2 rounded-lg text-slate-500 hover:text-slate-700 hover:bg-slate-100 transition-colors" title="Export as XMind">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
              </button>
              <button @click="triggerToggleTheme" class="p-2 rounded-lg text-slate-500 hover:text-slate-700 hover:bg-slate-100 transition-colors" title="Toggle Theme">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z"></path></svg>
              </button>
            </div>

            <div class="flex-1 min-h-0 w-full relative">
              <Transition name="fade" mode="out-in">
                <div v-if="!showMindmapCanvas" key="hero-upload" class="absolute inset-0 p-6 md:p-10 bg-gradient-to-b from-slate-50 to-white flex items-center justify-center">
                  <div
                    @click="triggerFileInput"
                    class="group w-full max-w-3xl min-h-[340px] rounded-3xl border-2 border-dashed border-slate-300 hover:border-orange-400 hover:bg-orange-50/60 transition-all duration-300 ease-out cursor-pointer bg-white/90 shadow-sm flex flex-col items-center justify-center px-8 py-10"
                    :class="{ 'border-orange-400 bg-orange-50/70 shadow-md': isDraggingFile }"
                  >
                    <svg class="w-20 h-20 mb-5 text-slate-400 group-hover:text-blue-500 transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M12 16.5V9.75m0 0l3 3m-3-3l-3 3M6.75 19.5a4.5 4.5 0 01-1.41-8.775 5.25 5.25 0 0110.233-2.33 3 3 0 013.758 3.848A3.752 3.752 0 0118 19.5H6.75z"></path>
                    </svg>
                    <h2 class="text-xl md:text-2xl font-semibold text-slate-700 tracking-wide text-center">点击或拖拽 PDF 文件至此</h2>
                    <p class="text-sm text-slate-500 mt-3 text-center">解析完成后自动生成思维导图，并支持右侧原文精准定位</p>
                    <p class="text-xs text-slate-400 mt-4">支持 PDF 格式，最大 50MB</p>

                    <div v-if="isLoading" class="w-full max-w-xl mt-8">
                      <div class="w-full h-3 bg-slate-200 rounded-full overflow-hidden">
                        <div
                          class="brand-progress h-full rounded-full transition-all duration-300 relative"
                          :class="{ 'animate-pulse': isUploadStage }"
                          :style="{ width: `${effectiveTaskProgress}%` }"
                        >
                          <div class="absolute inset-0 bg-white/20 animate-pulse"></div>
                        </div>
                      </div>
                      <div class="mt-2 flex items-center justify-between text-xs">
                        <span class="text-slate-500 truncate pr-3">{{ taskMessage }}</span>
                        <span class="text-slate-600 font-medium">{{ Math.round(effectiveTaskProgress) }}%</span>
                      </div>
                    </div>
                  </div>
                </div>

                <MindMap
                  v-else
                  key="mindmap-canvas"
                  ref="mindMapRef"
                  :markdown="mindmapData"
                  :file-id="currentFileId || ''"
                  :flat-nodes="flatNodes"
                  class="absolute inset-0"
                  @node-click="handleMindmapNodeClick"
                  @feedback="handleMindmapFeedback"
                />
              </Transition>
            </div>
          </div>

          <!-- 分隔拖拽条 -->
          <div
            v-if="showPdfPane"
            class="group cursor-col-resize flex flex-col justify-center items-center rounded-md bg-slate-200/40 hover:bg-blue-100/70 transition-colors relative"
            :class="{ 'bg-blue-100/90': isPdfResizing }"
            @mousedown="startPdfResizing"
          >
            <div class="h-full w-[2px] bg-slate-400/40 rounded-full group-hover:bg-blue-500/45 transition-colors relative">
              <div class="absolute top-1/2 -translate-y-1/2 -left-1 w-4 h-7 bg-blue-500/35 rounded-full"></div>
            </div>
          </div>

          <!-- 右侧：PDF原文查看器 -->
          <aside
            v-if="showPdfPane"
            class="app-card elev-md h-full flex flex-col rounded-xl border border-slate-200/40 overflow-hidden transition-all duration-300 ease-out"
            :class="{ 'duration-0': isPdfResizing }"
            :style="{ width: `${pdfPaneWidth}px`, minWidth: '320px' }"
          >
            <!-- PDF 原文独立工具栏 -->
            <div class="p-3 border-b border-slate-200/40 flex-shrink-0 bg-slate-50/60 backdrop-blur-sm z-10 flex items-center justify-between">
              <div>
                <h3 class="text-sm font-semibold text-slate-700 flex items-center gap-2">
                  <svg class="w-4 h-4 text-blue-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>
                  原文追溯
                </h3>
                <p class="text-[11px] text-slate-500 mt-0.5 truncate max-w-[200px]" :title="sourceView.topic || '选取节点以查看'">
                  {{ sourceView.topic ? sourceView.topic : '选取左侧节点以定位' }}
                </p>
              </div>
              
              <div class="flex items-center gap-1 bg-white p-1 rounded-lg border border-slate-200 shadow-sm" v-if="currentFileId">
                 <button @click="zoomInPdf" class="p-1.5 rounded text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-colors" title="Zoom In">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM10 7v3m0 0v3m0-3h3m-3 0H7"></path></svg>
                 </button>
                 <span class="text-[10px] text-slate-400 font-mono w-8 text-center">{{ Math.round(pdfScale * 100) }}%</span>
                 <button @click="zoomOutPdf" class="p-1.5 rounded text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-colors" title="Zoom Out">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0zM13 10H7"></path></svg>
                 </button>
                 <div class="w-[1px] h-4 bg-slate-200 mx-1"></div>
                 <button @click="toggleFullscreenPdf" class="p-1.5 rounded text-slate-500 hover:text-slate-800 hover:bg-slate-100 transition-colors" title="Fullscreen Document">
                    <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 8V4m0 0h4M4 4l5 5m11-1V4m0 0h-4m4 0l-5 5M4 16v4m0 0h4m-4 0l5-5m11 5l-5-5m5 5v-4m0 4h-4"></path></svg>
                 </button>
              </div>
            </div>

            <div class="flex-1 min-h-0 relative bg-slate-100 flex flex-col pointer-events-auto">
              <!-- Overlay States -->
              <div v-if="!currentFileId" class="absolute inset-0 flex items-center justify-center p-6 bg-slate-50/50">
                <div class="w-full max-w-sm flex flex-col items-center justify-center p-8 border border-slate-200 rounded-2xl bg-white text-center">
                  <svg class="w-12 h-12 text-slate-300 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5A3.375 3.375 0 0010.125 2.25H6.75A2.25 2.25 0 004.5 4.5v15A2.25 2.25 0 006.75 21.75h10.5a2.25 2.25 0 002.25-2.25v-5.25z"></path>
                  </svg>
                  <h4 class="text-sm font-semibold text-slate-700">原文预览区</h4>
                  <p class="text-xs text-slate-500 mt-1 leading-relaxed">上传并生成导图后，点击左侧节点可在这里显示并定位 PDF 原文段落。</p>
                </div>
              </div>
              <div v-else-if="sourceView.loading" class="absolute inset-x-0 top-0 z-20 flex justify-center p-2">
                 <div class="bg-blue-50 text-blue-600 text-[11px] px-3 py-1.5 rounded-full border border-blue-200 shadow-sm flex items-center gap-2 font-medium">
                    <svg class="animate-spin h-3.5 w-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                    </svg>
                    正在锚定页内坐标...
                 </div>
              </div>
              <div v-else-if="sourceView.error" class="absolute inset-0 flex items-center justify-center p-4 z-10">
                <div class="text-xs text-rose-600 bg-rose-50 border border-rose-200 rounded-lg p-4 text-center max-w-[80%] shadow-sm">
                  {{ sourceView.error }}
                </div>
              </div>

              <!-- Content Viewer Container -->
              <div
                v-if="currentFileId"
                ref="pdfScrollContainer"
                class="w-full h-full bg-slate-100 flex flex-col relative"
              >
                <!-- 降级提示（旧版文档或 Marker 回退） -->
                <div v-if="(!sourceView.hasPreciseAnchor || !sourceView.pdfPageNo) && sourceView.topic" class="absolute top-0 left-0 right-0 p-3 bg-amber-50/95 backdrop-blur-sm border-b border-amber-200 text-xs text-amber-700 flex flex-col z-30 shadow-sm transition-all shadow-amber-900/5 max-h-[30vh] overflow-y-auto">
                    <p class="mb-2 font-medium">
                        <svg class="w-4 h-4 inline mr-1 -mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path></svg>
                        当前节点暂无精确页内定位，已显示 PDF 并提供模糊段落对照：
                    </p>
                    <div class="bg-slate-800 rounded px-3 py-2 overflow-x-auto text-emerald-400 font-mono text-[11px] leading-relaxed selection:bg-emerald-700 shadow-inner">
                        <div v-for="line in sourceView.excerptLines" :key="line.line_no" class="flex">
                            <span class="w-6 text-right pr-2 text-slate-500 opacity-80 select-none mr-1">{{ line.line_no }}</span>
                            <span :class="{'bg-emerald-900/50 text-emerald-200 px-1 rounded-sm font-semibold': line.in_range, 'opacity-70': !line.in_range}">{{ line.text || ' ' }}</span>
                        </div>
                    </div>
                </div>
                
                <VirtualPdfViewer
                  v-if="systemFeatures.FEATURE_VIRTUAL_PDF"
                  id="source-pdf-v"
                  class="w-full h-full"
                  :source-url="pdfSourceUrl"
                  :page-no="sourceView.pdfPageNo"
                  :y-ratio="sourceView.pdfYRatio"
                  :scale="pdfScale"
                  @error="setPdfError($event, 'PDF 加载失败')"
                />
                
                <div v-else ref="legacyPdfScrollContainer" class="w-full h-full overflow-auto bg-slate-100 p-2">
                    <VuePdfEmbed
                      id="source-pdf-legacy"
                      class="w-full shadow-sm rounded border border-slate-200 mb-4"
                      :source="pdfSourceUrl"
                      :scale="pdfScale"
                      text-layer
                      annotation-layer
                      @loaded="handlePdfLoaded"
                      @rendered="handlePdfRendered"
                      @loading-failed="(err) => handlePdfRenderError(err, 'PDF 加载失败')"
                      @rendering-failed="(err) => handlePdfRenderError(err, 'PDF 渲染失败')"
                    />
                </div>
              </div>
            </div>
          </aside>
        </div>
      </main>
    </div>
  </div>

  <!-- AI模型设置弹窗 -->
  <Transition name="modal">
    <div v-if="showLlmSettings" class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm flex items-center justify-center z-50 p-4" @click.self="showLlmSettings = false">
    <div class="app-card elev-lg rounded-2xl w-full max-w-2xl mx-4 overflow-hidden flex flex-col max-h-[90vh] transition-all duration-300 ease-out border border-slate-200/40">
      <!-- 弹窗头部 -->
      <div class="flex items-center justify-between px-6 py-4 border-b border-slate-200/40 bg-gradient-to-r from-slate-50/80 to-indigo-50/20 flex-shrink-0">
        <div class="flex items-center gap-3">
          <div class="p-2 bg-indigo-100 rounded-xl">
            <svg class="w-5 h-5 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
               <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"></path>
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 2v2m0 16v2M4.929 4.929l1.414 1.414m11.314 11.314l1.414 1.414M2 12h2m16 0h2M6.343 17.657l-1.414 1.414M17.657 6.343l1.414-1.414"></path>
            </svg>
          </div>
          <h2 class="text-lg font-semibold text-slate-800">AI 模型设置</h2>
        </div>
        <button @click="showLlmSettings = false" class="p-2 rounded-xl text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-all duration-200">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>
        </button>
      </div>
      <input
        ref="configImportInput"
        type="file"
        accept=".json,application/json"
        class="hidden"
        @change="importConfigFromFile"
      />

      <!-- 弹窗内容 -->
      <div class="p-6 space-y-5 max-h-[70vh] overflow-y-auto">
        <div class="flex items-center justify-between gap-2 p-3 bg-blue-50/60 border border-blue-100 rounded-xl">
          <p class="text-xs text-slate-600">支持导出当前配置（不含明文密钥）并在本机或其他环境导入。</p>
          <div class="flex items-center gap-2">
            <button @click="triggerImportConfig" type="button" class="px-3 py-1.5 text-xs rounded-lg border border-slate-300 hover:bg-white">导入</button>
            <button @click="exportConfig" type="button" class="px-3 py-1.5 text-xs rounded-lg border border-slate-300 hover:bg-white">导出</button>
          </div>
        </div>
        <div v-if="configOperationMsg" class="text-xs text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2">
          {{ configOperationMsg }}
        </div>

        <!-- 服务商选择 -->
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

        <!-- Base URL -->
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

        <!-- 模型选择 -->
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
            {{ modelFetchResult.message }}<span v-if="modelFetchResult.source">（source: {{ modelFetchResult.source }}）</span>
            <div v-if="modelFetchResult.code" class="mt-1 opacity-80">{{ getErrorHint(modelFetchResult.code) }}</div>
          </div>
        </div>

        <!-- API Key -->
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
          Ollama 模式下无需 API Key（后台自动处理占位）。
        </div>

        <!-- 账户类型 (仅 MiniMax 2.5 需要) -->
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
            <option value="paid">充值用户 (500 RPM)</option>
          </select>
        </div>

        <!-- 测试结果 -->
        <div v-if="configTestResult"
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

      <!-- 弹窗底部按钮 -->
      <div class="flex items-center justify-end gap-3 px-6 py-4 border-t border-slate-200/60 bg-slate-50 flex-shrink-0">
        <button
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
          @click="saveConfig('llm')"
          :disabled="isLlmSaveDisabled"
          class="px-5 py-2.5 text-sm btn-primary rounded-xl disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {{ configLoading ? '保存中...' : '保存配置' }}
        </button>
      </div>
    </div>
  </div>
  </Transition>

  <!-- 解析策略弹窗 -->
  <Transition name="modal">
    <div v-if="showParserSettings" class="fixed inset-0 bg-slate-900/40 backdrop-blur-sm flex items-center justify-center z-50 p-4" @click.self="showParserSettings = false">
    <div class="app-card elev-lg rounded-2xl w-full max-w-2xl mx-4 overflow-hidden flex flex-col max-h-[90vh] transition-all duration-300 ease-out border border-slate-200/40">
      <!-- 弹窗头部 -->
      <div class="flex items-center justify-between px-6 py-4 border-b border-slate-200/40 bg-gradient-to-r from-slate-50/80 to-blue-50/20 flex-shrink-0">
        <div class="flex items-center gap-3">
          <div class="p-2 bg-blue-100 rounded-xl">
             <svg class="w-5 h-5 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
               <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4"></path>
            </svg>
          </div>
          <h2 class="text-lg font-semibold text-slate-800">解析策略配置</h2>
        </div>
        <button @click="showParserSettings = false" class="p-2 rounded-xl text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-all duration-200">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
          </svg>
        </button>
      </div>

      <!-- 弹窗内容 -->
      <div class="p-6 space-y-5 overflow-y-auto">
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
            <label class="text-xs text-slate-600">任务超时（秒）</label>
            <input
              v-model.number="parserConfig.task_timeout_seconds"
              type="number"
              :data-error="Boolean(fieldErrors.task_timeout_seconds)"
              min="60"
              max="7200"
              step="1"
              class="mt-1 w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
            />
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

      </div>

      <!-- 弹窗底部按钮 -->
      <div class="flex items-center justify-end gap-3 px-6 py-4 border-t border-slate-200/60 bg-slate-50 flex-shrink-0">
        <button
          @click="saveConfig('parser')"
          :disabled="isParserSaveDisabled"
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
</style>
