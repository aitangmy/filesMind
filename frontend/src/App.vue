<script setup>
import { ref, onMounted, onUnmounted } from 'vue';
import MindMap from './components/MindMap.vue';

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
const config = ref({
  base_url: 'https://api.deepseek.com',  // 不要加 /v1，库会自动添加
  model: 'deepseek-chat',
  api_key: '',
  account_type: 'free'  // 新增：账户类型 (free/paid)
});
const configLoading = ref(false);
const configTestResult = ref(null);

// 预设服务商列表
const providerOptions = [
  { value: 'https://api.minimaxi.com/v1', label: 'MiniMax' },
  { value: 'https://api.deepseek.com', label: 'DeepSeek (官方)' },
  { value: 'https://api.openai.com', label: 'OpenAI' },
  { value: 'https://api.anthropic.com', label: 'Anthropic (Claude)' },
  { value: 'https://api.moonshot.cn', label: '月之暗面 (Moonshot)' },
  { value: 'https://dashscope.aliyuncs.com/compatible-mode/v1', label: '阿里云 (DashScope)' }
];

// 预设模型列表
const modelOptions = [
  { value: 'MiniMax-M2.5', label: 'MiniMax 2.5' },
  { value: 'deepseek-chat', label: 'DeepSeek V3 (非思考)' },
  { value: 'deepseek-reasoner', label: 'DeepSeek R1 (思考)' },
  { value: 'gpt-4o', label: 'GPT-4o' },
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini' },
  { value: 'claude-3-5-sonnet-20241022', label: 'Claude 3.5 Sonnet' },
  { value: 'moonshot-v1-8k-vision-preview', label: 'Moonshot V1 8K' },
  { value: 'qwen-plus', label: '通义千问 Plus' }
];

// 检测是否为 MiniMax 2.5 系列模型
const isMiniMax25 = (model) => {
  if (!model) return false;
  const minimaxModels = ['MiniMax-M2.5', 'MiniMax-M2.5-highspeed', 'abab6.5s-chat', 'abab6.5g-chat'];
  return minimaxModels.some(m => model.toLowerCase().includes(m.toLowerCase()));
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
      currentFileId.value = data.file_id;
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
      config.value = await response.json();
    }
  } catch (err) {
    console.error('加载配置失败:', err);
  }
};

// 保存配置
const saveConfig = async () => {
  configLoading.value = true;
  configTestResult.value = null;
  try {
    const response = await fetch('/api/config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config.value)
    });
    if (response.ok) {
      showSettings.value = false;
      alert('配置已保存');
    } else {
      const data = await response.json();
      alert('保存失败: ' + (data.detail || '未知错误'));
    }
  } catch (err) {
    alert('保存失败: ' + err.message);
  }
  configLoading.value = false;
};

// 测试配置
const testConfig = async () => {
  configLoading.value = true;
  configTestResult.value = null;
  try {
    const response = await fetch('/api/config/test', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config.value)
    });
    configTestResult.value = await response.json();
  } catch (err) {
    configTestResult.value = { success: false, message: err.message };
  }
  configLoading.value = false;
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
          <MindMap :markdown="mindmapData" class="h-full" />
        </div>
      </main>
    </div>
  </div>

  <!-- 设置弹窗 -->
  <div v-if="showSettings" class="fixed inset-0 bg-slate-900/50 backdrop-blur-sm flex items-center justify-center z-50 p-4" @click.self="showSettings = false">
    <div class="bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden">
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

      <!-- 弹窗内容 -->
      <div class="p-6 space-y-5">
        <!-- 服务商选择 -->
        <div>
          <label class="flex items-center gap-2 text-sm font-medium text-slate-700 mb-2">
            <svg class="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10"></path>
            </svg>
            服务商
          </label>
          <select
            v-model="config.base_url"
            class="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-200 bg-white hover:border-slate-300"
          >
            <option v-for="opt in providerOptions" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
        </div>

        <!-- Base URL (可选自定义) -->
        <div>
          <label class="flex items-center gap-2 text-sm font-medium text-slate-700 mb-2">
            <svg class="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"></path>
            </svg>
            API Base URL
          </label>
          <input
            v-model="config.base_url"
            type="text"
            class="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-200 bg-white hover:border-slate-300 placeholder:text-slate-400"
            placeholder="https://api.deepseek.com/v1"
          />
          <p class="text-xs text-slate-400 mt-1.5 flex items-center gap-1">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
            </svg>
            如需使用其他服务商，请在上方选择或自定义输入
          </p>
        </div>

        <!-- 模型选择 -->
        <div>
          <label class="flex items-center gap-2 text-sm font-medium text-slate-700 mb-2">
            <svg class="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z"></path>
            </svg>
            模型
          </label>
          <select
            v-model="config.model"
            class="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-200 bg-white hover:border-slate-300"
          >
            <option v-for="opt in modelOptions" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
        </div>

        <!-- API Key -->
        <div>
          <label class="flex items-center gap-2 text-sm font-medium text-slate-700 mb-2">
            <svg class="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z"></path>
            </svg>
            API Key
          </label>
          <input
            v-model="config.api_key"
            type="password"
            class="w-full px-4 py-2.5 border border-slate-200 rounded-xl text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 transition-all duration-200 bg-white hover:border-slate-300 placeholder:text-slate-400"
            placeholder="sk-..."
          />
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
          <p class="text-xs text-amber-700 mt-2 flex items-center gap-1">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
            </svg>
            选择账户类型以适配 API 速率限制
          </p>
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
          {{ configTestResult.message }}
        </div>
      </div>

      <!-- 弹窗底部按钮 -->
      <div class="flex items-center justify-end gap-3 px-6 py-4 border-t border-slate-200/60 bg-slate-50">
        <button
          @click="testConfig"
          :disabled="configLoading || !config.api_key"
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
          :disabled="configLoading || !config.api_key"
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
