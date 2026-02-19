<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue';
import MindMap from './components/MindMap.vue';

const MASKED_KEY = '***';
const providerOptions = [
  { value: 'minimax', label: 'MiniMax', base_url: 'https://api.minimaxi.com/v1' },
  { value: 'deepseek', label: 'DeepSeek (官方)', base_url: 'https://api.deepseek.com' },
  { value: 'openai', label: 'OpenAI', base_url: 'https://api.openai.com' },
  { value: 'anthropic', label: 'Anthropic (Claude)', base_url: 'https://api.anthropic.com' },
  { value: 'moonshot', label: '月之暗面 (Moonshot)', base_url: 'https://api.moonshot.cn' },
  { value: 'dashscope', label: '阿里云 (DashScope)', base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1' },
  { value: 'ollama', label: 'Ollama (Local)', base_url: 'http://localhost:11434/v1' },
  { value: 'custom', label: 'Custom', base_url: '' }
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
  marker_prefer_api: false
});

const fileInput = ref(null);
const isLoading = ref(false);
const errorMsg = ref('');
const mindmapData = ref('# Welcome to FilesMind\n\n- **Upload a PDF** to generate a Deep Knowledge Map\n- Powered by **IBM Docling** & **DeepSeek R1**\n- **Recursive Reasoning** for profound insights');

// 侧边栏
const showSidebar = ref(true);
const history = ref([]);
const currentFileId = ref(null);

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

const makeProfileId = () => {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
  return `profile_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
};

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
};

const getErrorHint = (code, fallback = '') => ERROR_CODE_HINTS[code] || fallback || '操作失败，请检查配置';

const createProfile = (overrides = {}) => ({
  id: overrides.id || makeProfileId(),
  name: overrides.name || 'New Profile',
  provider: overrides.provider || 'custom',
  base_url: overrides.base_url || 'https://api.deepseek.com',
  model: overrides.model || 'deepseek-chat',
  api_key: '',
  has_api_key: Boolean(overrides.has_api_key || (overrides.api_key && overrides.api_key !== MASKED_KEY)),
  account_type: overrides.account_type || 'free',
  manual_models_text: (overrides.manual_models || []).join(', ')
});

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

  const name = config.value.name?.trim() || '';
  if (!name) errors.name = '配置档案名称不能为空';
  else if (name.length > 60) errors.name = '配置档案名称长度不能超过 60';

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

  return errors;
});

const hasValidationErrors = computed(() => Object.keys(fieldErrors.value).length > 0);
const canTestConfig = computed(() => Boolean(config.value.base_url?.trim() && config.value.model?.trim()) && !Boolean(fieldErrors.value.base_url || fieldErrors.value.model || fieldErrors.value.api_key));
const isSaveDisabled = computed(() => {
  if (configLoading.value) return true;
  return hasValidationErrors.value;
});

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

const onProfileChange = (event) => {
  persistEditorProfile();
  loadProfileIntoEditor(event.target.value);
};

const addProfile = () => {
  persistEditorProfile();
  const profile = createProfile({ name: `Profile ${profiles.value.length + 1}` });
  profiles.value.push(profile);
  loadProfileIntoEditor(profile.id);
};

const removeProfile = () => {
  if (profiles.value.length <= 1) {
    alert('至少保留一个配置档案');
    return;
  }
  const removeId = activeProfileId.value;
  const next = profiles.value.find((item) => item.id !== removeId);
  profiles.value = profiles.value.filter((item) => item.id !== removeId);
  if (modelCatalogByProfile.value[removeId]) {
    delete modelCatalogByProfile.value[removeId];
  }
  if (next) loadProfileIntoEditor(next.id);
};

const clearStoredKey = () => {
  config.value.has_api_key = false;
  config.value.api_key = '';
};

const applyProviderPreset = () => {
  const preset = providerOptions.find((item) => item.value === config.value.provider);
  if (!preset) return;
  if (preset.base_url) {
    config.value.base_url = preset.base_url;
  }
  if (config.value.provider === 'ollama' && !config.value.model) {
    config.value.model = 'qwen2.5:7b';
  }
  modelFetchResult.value = null;
};

const buildConfigStorePayload = () => {
  persistEditorProfile();
  const parser = {
    parser_backend: String(parserConfig.value.parser_backend || 'docling').trim().toLowerCase(),
    hybrid_noise_threshold: Number(parserConfig.value.hybrid_noise_threshold ?? 0.2),
    hybrid_docling_skip_score: Number(parserConfig.value.hybrid_docling_skip_score ?? 70),
    hybrid_switch_min_delta: Number(parserConfig.value.hybrid_switch_min_delta ?? 2),
    hybrid_marker_min_length: Number(parserConfig.value.hybrid_marker_min_length ?? 200),
    marker_prefer_api: Boolean(parserConfig.value.marker_prefer_api)
  };
  return {
    active_profile_id: activeProfileId.value,
    parser,
    profiles: profiles.value.map((item) => ({
      id: item.id,
      name: item.name?.trim() || 'Unnamed Profile',
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
    name: config.value.name?.trim() || 'Unnamed Profile',
    provider: config.value.provider || 'custom',
    base_url: config.value.base_url?.trim() || '',
    model: config.value.model?.trim() || '',
    api_key: config.value.api_key?.trim() ? config.value.api_key.trim() : (config.value.has_api_key ? MASKED_KEY : ''),
    account_type: config.value.account_type || 'free',
    manual_models: normalizeManualModels(config.value.manual_models_text)
  }
});

const normalizeBackendError = async (response, fallbackMessage) => {
  try {
    const data = await response.json();
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
      alert(`${getErrorHint(err.code, err.message)} (${err.code})`);
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
  } catch (err) {
    alert(`导出配置失败: ${err.message}`);
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
      alert(`${getErrorHint(err.code, err.message)} (${err.code})`);
      return;
    }
    const result = await response.json();
    await loadConfig();
    configOperationMsg.value = `${result.message || '配置导入成功'}，请检查后保存`;
  } catch (err) {
    alert(`导入配置失败: ${err.message}`);
  }
};

const normalizeConfigStore = (raw) => {
  // 兼容 legacy 单配置格式
  if (!raw?.profiles || !Array.isArray(raw.profiles)) {
    const fallback = createProfile({
      name: 'Default',
      provider: 'custom',
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

  const normalizedProfiles = raw.profiles.map((item) => createProfile({
    ...item,
    has_api_key: Boolean(item.has_api_key || item.api_key === MASKED_KEY || item.api_key),
    manual_models: item.manual_models || []
  }));

  const active = normalizedProfiles.find((item) => item.id === raw.active_profile_id) || normalizedProfiles[0];
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
    marker_prefer_api: toBoolean(parserRaw.marker_prefer_api, false)
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

const MAX_POLL_TIME = 600000;
const POLL_INTERVAL = 1500;
let pollStartTime = 0;

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

// 加载文件内容
const loadFile = async (fileId) => {
  try {
    const response = await fetch(`/api/file/${fileId}`);
    if (!response.ok) {
      throw new Error('文件加载失败');
    }
    const data = await response.json();
    mindmapData.value = data.content;
    currentFileId.value = fileId;
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
        mindmapData.value = '# Welcome to FilesMind\n\n- **Upload a PDF** to generate a Deep Knowledge Map';
        currentFileId.value = null;
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
      if (data.file_id) {
        currentFileId.value = data.file_id;
      }
      isLoading.value = false;
      if (fileInput.value) fileInput.value.value = '';
      await loadHistory();
    } 
    else if (data.status === 'failed') {
      cleanupPoll();
      errorMsg.value = data.error || '处理失败';
      isLoading.value = false;
      await loadHistory();
    }
    
  } catch (err) {
    console.error("Poll error:", err);
  }
};

const checkPollTimeout = () => {
  if (pollStartTime && Date.now() - pollStartTime > MAX_POLL_TIME) {
    cleanupPoll();
    errorMsg.value = '处理超时，请重试';
    isLoading.value = false;
  }
};

const handleFileUpload = async (event) => {
  const file = event.target.files[0];
  if (!file) return;

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
          event.target.value = ''; // 清空选择
          return; // 终止上传
      }
  }

  if (currentTaskId.value) {
    cleanupPoll();
  }

  isLoading.value = true;
  errorMsg.value = '';
  
  taskStatus.value = 'pending';
  taskProgress.value = 0;
  taskMessage.value = '正在上传文件...';
  
  const formData = new FormData();
  formData.append('file', file);

  try {
    const response = await fetch('/api/upload', {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      throw new Error(`Upload failed: ${response.statusText}`);
    }

    const data = await response.json();
    
    if (data.error) {
      throw new Error(data.error);
    }

    if (data.is_duplicate) {
      mindmapData.value = data.existing_md;
      currentFileId.value = data.file_id;
      isLoading.value = false;
      alert('该文件已存在，直接加载已有结果');
      if (fileInput.value) fileInput.value.value = '';
      return;
    }

    if (!data.task_id) {
      throw new Error('未获取到任务ID');
    }

    currentTaskId.value = data.task_id;
    currentFileId.value = data.file_id;
    pollStartTime = Date.now();
    taskStatus.value = 'processing';
    
    pollTimer.value = setInterval(() => {
      checkPollTimeout();
      if (currentTaskId.value) {
        pollTaskStatus(currentTaskId.value);
      }
    }, POLL_INTERVAL);
    
    pollTaskStatus(data.task_id);
    await loadHistory();
    
  } catch (err) {
    errorMsg.value = err.message;
    console.error("Upload error:", err);
    isLoading.value = false;
    cleanupPoll();
  }
};

const cancelTask = () => {
  cleanupPoll();
  isLoading.value = false;
  taskProgress.value = 0;
  taskMessage.value = '';
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
  loadHistory();
  loadConfig();
  checkHardware();
});

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

// 保存配置
const saveConfig = async () => {
  if (hasValidationErrors.value) {
    const firstMessage = Object.values(fieldErrors.value)[0] || '请先修正配置项';
    alert(firstMessage);
    return;
  }
  configLoading.value = true;
  configTestResult.value = null;
  try {
    const payload = buildConfigStorePayload();
    const response = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await response.json();
    if (response.ok && data.success !== false) {
      await loadConfig();
      showSettings.value = false;
      alert('配置已保存');
      configOperationMsg.value = '配置已保存并生效';
    } else {
      const detail = data?.detail || data;
      const code = detail?.code || data?.code || 'UNKNOWN_ERROR';
      const message = typeof detail === 'string' ? detail : (detail?.message || data?.message || '未知错误');
      alert(`保存失败: ${getErrorHint(code, message)} (${code})`);
    }
  } catch (err) {
    alert('保存失败: ' + err.message);
  }
  configLoading.value = false;
};

// 测试配置
const testConfig = async () => {
  if (!canTestConfig.value) {
    const firstMessage = Object.values(fieldErrors.value)[0] || '请先修正配置项';
    alert(firstMessage);
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
    const result = await response.json();
    configTestResult.value = {
      ...result,
      message: `${result.message || ''}${result.code ? ` (${result.code})` : ''}`,
      hint: getErrorHint(result.code, result.message)
    };
  } catch (err) {
    configTestResult.value = { success: false, message: err.message };
  }
  configLoading.value = false;
};

const loadModels = async () => {
  if (!canTestConfig.value) {
    const firstMessage = Object.values(fieldErrors.value)[0] || '请先修正配置项';
    alert(firstMessage);
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
    const data = await response.json();
    modelFetchResult.value = data;
    if (data?.success && Array.isArray(data.models)) {
      modelCatalogByProfile.value[config.value.id] = data.models;
      if (!config.value.model && data.models.length > 0) {
        config.value.model = data.models[0];
      }
    } else if (data?.code) {
      modelFetchResult.value.message = `${data.message || ''} (${data.code})`;
    }
  } catch (err) {
    modelFetchResult.value = { success: false, message: err.message, source: 'none', code: 'NETWORK_ERROR' };
  }
  modelLoading.value = false;
};
</script>

<template>
  <div class="h-screen flex bg-gradient-to-br from-slate-50 via-blue-50/30 to-slate-50 font-sans text-slate-900 overflow-hidden">
    <!-- 侧边栏 - 可折叠 -->
    <aside
      class="w-64 flex-shrink-0 bg-white/80 backdrop-blur-xl border-r border-slate-200/60 flex flex-col transition-all duration-300 shadow-medium"
      :class="showSidebar ? 'translate-x-0' : '-translate-x-full absolute h-full'"
    >
      <!-- Logo 区域 -->
      <div class="h-14 px-4 flex items-center border-b border-slate-200/60 bg-gradient-to-r from-blue-600 to-indigo-600">
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
              ? 'bg-gradient-to-r from-blue-50 to-indigo-50 border-blue-200 shadow-sm'
              : 'bg-white/80 border-transparent hover:bg-white hover:border-slate-200/60 hover:shadow-soft'"
          >
            <div class="flex items-start justify-between gap-2">
              <div class="flex-grow min-w-0">
                <div class="font-medium text-slate-700 truncate text-sm">{{ item.filename }}</div>
                <div class="flex items-center gap-2 mt-1.5">
                  <span
                    class="text-[10px] px-1.5 py-0.5 rounded-full font-medium flex items-center gap-0.5"
                    :class="item.status === 'completed'
                      ? 'bg-green-100 text-green-600'
                      : item.status === 'processing'
                        ? 'bg-amber-100 text-amber-600'
                        : 'bg-red-100 text-red-600'"
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
                class="opacity-0 group-hover:opacity-100 p-1.5 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 transition-all duration-200"
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

    <!-- 主内容区 -->
    <div class="flex-grow flex flex-col min-w-0">
      <!-- 顶部导航栏 -->
      <header class="h-14 flex-shrink-0 bg-white/80 backdrop-blur-xl border-b border-slate-200/60 flex items-center justify-between px-4 shadow-soft">
        <!-- 左侧：侧边栏开关 + 上传按钮 -->
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
              class="inline-flex items-center px-4 py-2 btn-primary text-sm rounded-xl cursor-pointer disabled:opacity-50 shadow-lg shadow-blue-500/20"
              :class="{ 'pointer-events-none opacity-50': isLoading }"
          >
              <input
                  ref="fileInput"
                  type="file"
                  accept=".pdf"
                  class="hidden"
                  @change="handleFileUpload"
                  :disabled="isLoading"
              />

              <span v-if="isLoading" class="flex items-center gap-2">
                  <svg class="animate-spin w-4 h-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                  </svg>
                  处理中...
              </span>
              <span v-else class="flex items-center gap-2">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path>
                  </svg>
                  上传 PDF
              </span>
          </label>
        </div>

        <!-- 右侧：设置按钮 -->
        <div class="flex items-center gap-2">
          <button
            @click="showSettings = true"
            class="p-2 rounded-xl text-slate-500 hover:bg-slate-100/80 hover:text-slate-700 transition-all duration-200"
            title="设置"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path>
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path>
            </svg>
          </button>
        </div>
      </header>

      <!-- 进度条区域 -->
      <div v-if="isLoading" class="flex-shrink-0 bg-white/80 backdrop-blur-xl border-b border-slate-200/60 px-4 py-3">
        <div class="flex items-center gap-3">
          <div class="flex-grow h-2 bg-slate-100 rounded-full overflow-hidden">
            <div
              class="h-full bg-gradient-to-r from-blue-500 via-indigo-500 to-purple-500 rounded-full transition-all duration-300 relative overflow-hidden"
              :style="{ width: `${taskProgress}%` }"
            >
              <div class="absolute inset-0 bg-white/20 animate-pulse"></div>
            </div>
          </div>
          <span class="text-xs font-medium text-slate-600 whitespace-nowrap bg-slate-100 px-2 py-1 rounded-md">{{ taskProgress }}%</span>
          <span class="text-xs text-slate-500 max-w-[200px] truncate">{{ taskMessage }}</span>
          <button @click="cancelTask" class="p-1.5 rounded-lg text-slate-400 hover:text-red-500 hover:bg-red-50 transition-all duration-200">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
            </svg>
          </button>
        </div>
      </div>

      <!-- 错误提示 -->
      <div v-if="errorMsg" class="flex-shrink-0 bg-gradient-to-r from-red-50 to-orange-50 border-b border-red-200/60 px-4 py-3 flex items-center gap-3">
        <div class="p-1.5 bg-red-100 rounded-lg">
          <svg class="w-4 h-4 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
          </svg>
        </div>
        <span class="text-sm font-medium text-red-700">{{ errorMsg }}</span>
        <button @click="errorMsg = ''" class="ml-auto p-1.5 rounded-lg text-red-400 hover:text-red-600 hover:bg-red-100 transition-all duration-200">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
          </svg>
        </button>
      </div>

      <!-- 思维导图区域 -->
      <main class="flex-grow p-4 overflow-hidden">
        <div class="h-full bg-white rounded-2xl shadow-medium border border-slate-200/60 overflow-hidden gradient-border">
          <MindMap :markdown="mindmapData" :file-id="currentFileId || ''" class="h-full" />
        </div>
      </main>
    </div>
  </div>

  <!-- 设置弹窗 -->
  <div v-if="showSettings" class="fixed inset-0 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center z-50 p-4" @click.self="showSettings = false">
    <div class="bg-white rounded-2xl shadow-2xl w-full max-w-2xl mx-4 overflow-hidden">
      <!-- 弹窗头部 -->
      <div class="flex items-center justify-between px-6 py-4 border-b border-slate-200/60 bg-gradient-to-r from-slate-50 to-blue-50/30">
        <div class="flex items-center gap-3">
          <div class="p-2 bg-blue-100 rounded-xl">
            <svg class="w-5 h-5 text-blue-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path>
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path>
            </svg>
          </div>
          <h2 class="text-lg font-semibold text-slate-800">LLM 模型设置</h2>
        </div>
        <button @click="showSettings = false" class="p-2 rounded-xl text-slate-400 hover:text-slate-600 hover:bg-slate-100 transition-all duration-200">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
          </svg>
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

        <!-- 配置档案 -->
        <div class="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-3">
          <label class="flex items-center gap-2 text-sm font-medium text-slate-700">
            配置档案
          </label>
          <div class="flex items-center gap-2">
            <select
              :value="activeProfileId"
              @change="onProfileChange"
              class="flex-1 px-3 py-2.5 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
            >
              <option v-for="item in profiles" :key="item.id" :value="item.id">
                {{ item.name }}
              </option>
            </select>
            <button @click="addProfile" type="button" class="px-3 py-2 text-xs rounded-lg border border-slate-300 hover:bg-slate-100">新增</button>
            <button @click="removeProfile" type="button" class="px-3 py-2 text-xs rounded-lg border border-red-200 text-red-600 hover:bg-red-50">删除</button>
          </div>
          <input
            v-model="config.name"
            type="text"
            class="w-full px-3 py-2.5 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
            placeholder="配置档案名称"
          />
          <p v-if="fieldErrors.name" class="text-xs text-red-600">{{ fieldErrors.name }}</p>
        </div>

        <!-- 服务商选择 -->
        <div>
          <label class="flex items-center gap-2 text-sm font-medium text-slate-700 mb-2">
            服务商
          </label>
          <select
            v-model="config.provider"
            @change="applyProviderPreset"
            class="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-200 bg-white hover:border-slate-300"
          >
            <option v-for="opt in providerOptions" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
        </div>

        <!-- 解析引擎 -->
        <div class="p-4 bg-slate-50 border border-slate-200 rounded-xl space-y-3">
          <label class="flex items-center gap-2 text-sm font-medium text-slate-700">
            解析引擎
          </label>
          <select
            v-model="parserConfig.parser_backend"
            class="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
          >
            <option v-for="opt in parserBackendOptions" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
          <p v-if="fieldErrors.parser_backend" class="text-xs text-red-600">{{ fieldErrors.parser_backend }}</p>

          <div v-if="isHybridParser" class="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label class="text-xs text-slate-600">噪声阈值 (0-1)</label>
              <input
                v-model.number="parserConfig.hybrid_noise_threshold"
                type="number"
                min="0"
                max="1"
                step="0.01"
                class="mt-1 w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
              />
              <p v-if="fieldErrors.hybrid_noise_threshold" class="text-xs text-red-600 mt-1">{{ fieldErrors.hybrid_noise_threshold }}</p>
            </div>
            <div>
              <label class="text-xs text-slate-600">Docling 跳过分数 (0-100)</label>
              <input
                v-model.number="parserConfig.hybrid_docling_skip_score"
                type="number"
                min="0"
                max="100"
                step="0.5"
                class="mt-1 w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
              />
              <p v-if="fieldErrors.hybrid_docling_skip_score" class="text-xs text-red-600 mt-1">{{ fieldErrors.hybrid_docling_skip_score }}</p>
            </div>
            <div>
              <label class="text-xs text-slate-600">切换分差阈值 (0-50)</label>
              <input
                v-model.number="parserConfig.hybrid_switch_min_delta"
                type="number"
                min="0"
                max="50"
                step="0.5"
                class="mt-1 w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
              />
              <p v-if="fieldErrors.hybrid_switch_min_delta" class="text-xs text-red-600 mt-1">{{ fieldErrors.hybrid_switch_min_delta }}</p>
            </div>
            <div>
              <label class="text-xs text-slate-600">Marker 最小长度（字符）</label>
              <input
                v-model.number="parserConfig.hybrid_marker_min_length"
                type="number"
                min="0"
                max="1000000"
                step="1"
                class="mt-1 w-full px-3 py-2 border border-slate-200 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 bg-white"
              />
              <p v-if="fieldErrors.hybrid_marker_min_length" class="text-xs text-red-600 mt-1">{{ fieldErrors.hybrid_marker_min_length }}</p>
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

        <!-- Base URL -->
        <div>
          <label class="flex items-center gap-2 text-sm font-medium text-slate-700 mb-2">
            API Base URL
          </label>
          <input
            v-model="config.base_url"
            type="text"
            class="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-200 bg-white hover:border-slate-300 placeholder:text-slate-400"
            placeholder="https://api.deepseek.com"
          />
          <p v-if="fieldErrors.base_url" class="text-xs text-red-600 mt-1">{{ fieldErrors.base_url }}</p>
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
            class="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-200 bg-white hover:border-slate-300"
          >
            <option v-for="model in activeProfileModels" :key="model" :value="model">
              {{ model }}
            </option>
          </select>
          <input
            v-model="config.model"
            type="text"
            class="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-200 bg-white hover:border-slate-300 placeholder:text-slate-400"
            placeholder="手动输入模型名"
          />
          <textarea
            v-model="config.manual_models_text"
            rows="2"
            class="w-full px-4 py-2 border border-slate-200 rounded-xl text-xs focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-200 bg-white hover:border-slate-300 placeholder:text-slate-400"
            placeholder="手动白名单（逗号或换行分隔），用于 /models 不可用时回退"
          ></textarea>
          <p v-if="fieldErrors.model" class="text-xs text-red-600">{{ fieldErrors.model }}</p>
          <p v-if="fieldErrors.manual_models" class="text-xs text-red-600">{{ fieldErrors.manual_models }}</p>
          <div
            v-if="modelFetchResult"
            class="text-xs p-2 rounded-lg border"
            :class="modelFetchResult.success ? 'bg-green-50 border-green-200 text-green-700' : 'bg-amber-50 border-amber-200 text-amber-700'"
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
            class="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-200 bg-white hover:border-slate-300 placeholder:text-slate-400"
            placeholder="sk-..."
          />
          <div v-if="config.has_api_key && !config.api_key" class="mt-2 flex items-center justify-between text-xs text-slate-500">
            <span>已保存密钥（未显示）。留空表示继续使用已保存密钥。</span>
            <button @click="clearStoredKey" type="button" class="text-red-600 hover:text-red-700">清空密钥</button>
          </div>
          <p v-if="fieldErrors.api_key" class="text-xs text-red-600 mt-1">{{ fieldErrors.api_key }}</p>
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
          :class="configTestResult.success ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'"
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
      <div class="flex items-center justify-end gap-3 px-6 py-4 border-t border-slate-200/60 bg-slate-50">
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
          @click="saveConfig"
          :disabled="isSaveDisabled"
          class="px-5 py-2.5 text-sm btn-primary rounded-xl disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {{ configLoading ? '保存中...' : '保存配置' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
</style>
