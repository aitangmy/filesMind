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

// 设置弹窗
const showSettings = ref(false);
const config = ref({
  base_url: 'https://api.deepseek.com',  // 不要加 /v1，库会自动添加
  model: 'deepseek-chat',
  api_key: ''
});
const configLoading = ref(false);
const configTestResult = ref(null);

// 预设服务商列表
const providerOptions = [
  { value: 'https://api.deepseek.com', label: 'DeepSeek (官方)' },
  { value: 'https://api.openai.com', label: 'OpenAI' },
  { value: 'https://api.anthropic.com', label: 'Anthropic (Claude)' },
  { value: 'https://api.moonshot.cn', label: '月之暗面 (Moonshot)' },
  { value: 'https://dashscope.aliyuncs.com/compatible-mode/v1', label: '阿里云 (DashScope)' }
];

// 预设模型列表
const modelOptions = [
  { value: 'deepseek-chat', label: 'DeepSeek V3 (非思考)' },
  { value: 'deepseek-reasoner', label: 'DeepSeek R1 (思考)' },
  { value: 'gpt-4o', label: 'GPT-4o' },
  { value: 'gpt-4o-mini', label: 'GPT-4o Mini' },
  { value: 'claude-3-5-sonnet-20241022', label: 'Claude 3.5 Sonnet' },
  { value: 'moonshot-v1-8k-vision-preview', label: 'Moonshot V1 8K' },
  { value: 'qwen-plus', label: '通义千问 Plus' }
];

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
});

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
  <div class="h-screen flex bg-slate-50 font-sans text-slate-900 overflow-hidden">
    <!-- 侧边栏 - 可折叠 -->
    <aside 
      class="w-56 flex-shrink-0 bg-white border-r border-slate-200 flex flex-col transition-all duration-300"
      :class="showSidebar ? 'translate-x-0' : '-translate-x-full absolute h-full'"
    >
      <!-- Logo 区域 -->
      <div class="h-12 px-4 flex items-center border-b border-slate-100">
        <div class="flex items-center gap-2">
          <div class="w-6 h-6 bg-blue-600 rounded flex items-center justify-center text-white text-xs font-bold">
            FM
          </div>
          <span class="text-sm font-bold text-slate-700">FilesMind</span>
        </div>
      </div>
      
      <!-- 文件列表 -->
      <div class="flex-grow overflow-y-auto p-3">
        <div class="text-xs font-medium text-slate-400 uppercase tracking-wider mb-2">
          历史文件
        </div>
        
        <div v-if="history.length === 0" class="text-xs text-slate-400 text-center py-4">
          暂无文件
        </div>
        
        <div v-else class="space-y-1">
          <div 
            v-for="item in history" 
            :key="item.file_id"
            @click="loadFile(item.file_id)"
            class="group p-2 rounded cursor-pointer transition-all duration-150 border text-xs"
            :class="currentFileId === item.file_id 
              ? 'bg-blue-50 border-blue-200' 
              : 'bg-white border-transparent hover:bg-slate-50'"
          >
            <div class="flex items-center justify-between gap-1">
              <div class="flex-grow min-w-0">
                <div class="font-medium text-slate-700 truncate">{{ item.filename }}</div>
                <div class="flex items-center gap-1 mt-0.5">
                  <span 
                    class="text-[10px] px-1 rounded"
                    :class="item.status === 'completed' 
                      ? 'bg-green-100 text-green-600' 
                      : item.status === 'processing'
                        ? 'bg-yellow-100 text-yellow-600'
                        : 'bg-red-100 text-red-600'"
                  >
                    {{ item.status === 'completed' ? '✓' : item.status === 'processing' ? '...' : '✗' }}
                  </span>
                  <span class="text-slate-400">{{ formatDate(item.created_at) }}</span>
                </div>
              </div>
              
              <button 
                @click="deleteFile(item.file_id, $event)"
                class="opacity-0 group-hover:opacity-100 p-1 rounded text-slate-400 hover:text-red-500 hover:bg-red-50"
              >
                <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
                </svg>
              </button>
            </div>
          </div>
        </div>
      </div>
    </aside>

    <!-- 主内容区 -->
    <div class="flex-grow flex flex-col min-w-0">
      <!-- 顶部导航栏 - 更紧凑 -->
      <header class="h-12 flex-shrink-0 bg-white border-b border-slate-200 flex items-center justify-between px-4">
        <!-- 左侧：侧边栏开关 + 上传按钮 -->
        <div class="flex items-center gap-3">
          <button 
            @click="showSidebar = !showSidebar"
            class="p-1.5 rounded text-slate-500 hover:bg-slate-100"
            :title="showSidebar ? '隐藏侧边栏' : '显示侧边栏'"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 6h16M4 12h16M4 18h7"></path>
            </svg>
          </button>
          
          <label 
              class="inline-flex items-center px-3 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg cursor-pointer hover:bg-blue-700 transition-colors disabled:opacity-50"
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
              
              <span v-if="isLoading" class="flex items-center gap-1.5">
                  <svg class="animate-spin w-3.5 h-3.5" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                      <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
                      <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"></path>
                  </svg>
                  处理中
              </span>
              <span v-else class="flex items-center gap-1.5">
                  <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12"></path>
                  </svg>
                  上传 PDF
              </span>
          </label>
        </div>
        
        <!-- 右侧：设置按钮 + Powered by -->
        <div class="flex items-center gap-3">
          <button 
            @click="showSettings = true"
            class="p-1.5 rounded text-slate-500 hover:bg-slate-100"
            title="设置"
          >
            <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z"></path>
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 12a3 3 0 11-6 0 3 3 0 016 0z"></path>
            </svg>
          </button>
          <div class="flex items-center gap-2 text-xs text-slate-400">
            <span>Powered by</span>
            <span class="font-medium text-slate-600">IBM Docling</span>
            <span>+</span>
            <span class="font-medium text-slate-600">DeepSeek</span>
          </div>
        </div>
      </header>

      <!-- 进度条区域 -->
      <div v-if="isLoading" class="flex-shrink-0 bg-white border-b border-slate-100 px-4 py-2">
        <div class="flex items-center gap-3">
          <div class="flex-grow h-1.5 bg-slate-100 rounded-full overflow-hidden">
            <div 
              class="h-full bg-gradient-to-r from-blue-500 to-indigo-500 rounded-full transition-all duration-300"
              :style="{ width: `${taskProgress}%` }"
            ></div>
          </div>
          <span class="text-xs text-slate-500 whitespace-nowrap">{{ taskProgress }}% - {{ taskMessage }}</span>
          <button @click="cancelTask" class="text-slate-400 hover:text-red-500">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
            </svg>
          </button>
        </div>
      </div>

      <!-- 错误提示 -->
      <div v-if="errorMsg" class="flex-shrink-0 bg-red-50 border-b border-red-100 px-4 py-2 flex items-center gap-2">
        <svg class="w-4 h-4 text-red-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"></path>
        </svg>
        <span class="text-sm text-red-600">{{ errorMsg }}</span>
        <button @click="errorMsg = ''" class="ml-auto text-red-400 hover:text-red-600">
          <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
          </svg>
        </button>
      </div>

      <!-- 思维导图区域 -->
      <main class="flex-grow p-3 overflow-hidden">
        <div class="h-full bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
          <MindMap :markdown="mindmapData" class="h-full" />
        </div>
      </main>
    </div>
  </div>

  <!-- 设置弹窗 -->
  <div v-if="showSettings" class="fixed inset-0 bg-black/50 flex items-center justify-center z-50" @click.self="showSettings = false">
    <div class="bg-white rounded-xl shadow-xl w-full max-w-md mx-4">
      <!-- 弹窗头部 -->
      <div class="flex items-center justify-between px-5 py-4 border-b border-slate-200">
        <h2 class="text-lg font-semibold text-slate-800">LLM 模型设置</h2>
        <button @click="showSettings = false" class="p-1 rounded text-slate-400 hover:text-slate-600 hover:bg-slate-100">
          <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path>
          </svg>
        </button>
      </div>
      
      <!-- 弹窗内容 -->
      <div class="p-5 space-y-4">
        <!-- 服务商选择 -->
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1">服务商</label>
          <select 
            v-model="config.base_url" 
            class="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            <option v-for="opt in providerOptions" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
        </div>
        
        <!-- Base URL (可选自定义) -->
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1">API Base URL</label>
          <input 
            v-model="config.base_url" 
            type="text" 
            class="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            placeholder="https://api.deepseek.com/v1"
          />
          <p class="text-xs text-slate-400 mt-1">如需使用其他服务商，请在上方选择或自定义输入</p>
        </div>
        
        <!-- 模型选择 -->
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1">模型</label>
          <select 
            v-model="config.model" 
            class="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
          >
            <option v-for="opt in modelOptions" :key="opt.value" :value="opt.value">
              {{ opt.label }}
            </option>
          </select>
        </div>
        
        <!-- API Key -->
        <div>
          <label class="block text-sm font-medium text-slate-700 mb-1">API Key</label>
          <input 
            v-model="config.api_key" 
            type="password" 
            class="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            placeholder="请输入 API Key"
          />
        </div>
        
        <!-- 测试结果 -->
        <div v-if="configTestResult" 
          class="p-3 rounded-lg text-sm"
          :class="configTestResult.success ? 'bg-green-50 text-green-700' : 'bg-red-50 text-red-700'"
        >
          {{ configTestResult.message }}
        </div>
      </div>
      
      <!-- 弹窗底部按钮 -->
      <div class="flex items-center justify-end gap-3 px-5 py-4 border-t border-slate-200 bg-slate-50 rounded-b-xl">
        <button 
          @click="testConfig" 
          :disabled="configLoading || !config.api_key"
          class="px-4 py-2 text-sm font-medium text-slate-700 bg-white border border-slate-300 rounded-lg hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {{ configLoading ? '测试中...' : '测试连接' }}
        </button>
        <button 
          @click="saveConfig" 
          :disabled="configLoading || !config.api_key"
          class="px-4 py-2 text-sm font-medium text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {{ configLoading ? '保存中...' : '保存' }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
</style>
