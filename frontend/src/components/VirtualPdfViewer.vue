<script setup>
import { ref, watch, onUnmounted } from 'vue';
import { apiFetch } from '../services/apiClient';

const props = defineProps({
  sourceUrl: {
    type: String,
    required: true
  },
  pageNo: {
    type: Number,
    default: null
  },
  yRatio: {
    type: Number,
    default: null
  },
  navigateKey: {
    type: Number,
    default: 0
  },
  // Compatibility props kept to avoid parent churn during PDFKit migration.
  maxMountedPages: {
    type: Number,
    default: 8
  },
  bufferPages: {
    type: Number,
    default: 2
  },
  scale: {
    type: Number,
    default: 1.0
  },
  preloadMaxPages: {
    type: Number,
    default: 1500
  },
  preloadConcurrency: {
    type: Number,
    default: 2
  }
});

const emit = defineEmits(['loaded', 'error']);

const frameRef = ref(null);
const loading = ref(true);
const ready = ref(false);
const error = ref('');
const blobUrl = ref('');
const frameSrc = ref('');

let loadToken = 0;
let activeAbortController = null;

const toErrorMessage = (err, fallback = '加载文档失败') => {
  if (!err) return fallback;
  if (typeof err === 'string' && err.trim()) return err.trim();
  if (typeof err?.message === 'string' && err.message.trim()) return err.message.trim();
  if (typeof err?.detail?.message === 'string' && err.detail.message.trim()) return err.detail.message.trim();
  return fallback;
};

const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

const currentPage = () => {
  const page = Number(props.pageNo);
  if (!Number.isFinite(page) || page < 1) return null;
  return Math.trunc(page);
};

const currentRatio = () => {
  const ratio = Number(props.yRatio);
  if (!Number.isFinite(ratio)) return null;
  return clamp(ratio, 0, 1);
};

const currentZoomPercent = () => {
  const scale = Number(props.scale);
  if (!Number.isFinite(scale) || scale <= 0) return 100;
  return clamp(Math.round(scale * 100), 40, 300);
};

const buildPdfFragment = () => {
  const parts = [];
  const page = currentPage();
  const ratio = currentRatio();
  const zoomPercent = currentZoomPercent();

  if (page) {
    parts.push(`page=${page}`);
  }

  if (ratio !== null) {
    const top = Math.round(ratio * 5000);
    parts.push(`zoom=${zoomPercent},0,${top}`);
  } else {
    parts.push(`zoom=${zoomPercent}`);
  }

  const navigateKey = Number(props.navigateKey);
  if (Number.isFinite(navigateKey) && navigateKey > 0) {
    parts.push(`nav=${Math.trunc(navigateKey)}`);
  }

  return parts.join('&');
};

const revokeBlobUrl = () => {
  if (!blobUrl.value) return;
  URL.revokeObjectURL(blobUrl.value);
  blobUrl.value = '';
};

const updateFrameSrc = () => {
  if (!blobUrl.value) {
    frameSrc.value = '';
    return;
  }
  const fragment = buildPdfFragment();
  const nextSrc = fragment ? `${blobUrl.value}#${fragment}` : blobUrl.value;
  if (nextSrc !== frameSrc.value) {
    frameSrc.value = nextSrc;
  }
};

const loadPdf = async () => {
  const source = String(props.sourceUrl || '').trim();
  loadToken += 1;
  const token = loadToken;

  if (activeAbortController && !activeAbortController.signal.aborted) {
    activeAbortController.abort();
  }

  loading.value = true;
  ready.value = false;
  error.value = '';
  revokeBlobUrl();
  frameSrc.value = '';

  if (!source) {
    loading.value = false;
    return;
  }

  const controller = new AbortController();
  activeAbortController = controller;

  try {
    const response = await apiFetch(source, {
      signal: controller.signal,
      cache: 'no-store'
    });
    if (token !== loadToken) return;
    if (!response.ok) {
      throw new Error(`加载文档失败 (${response.status})`);
    }

    const blob = await response.blob();
    if (token !== loadToken) return;
    if (!blob || blob.size <= 0) {
      throw new Error('PDF 文件为空');
    }

    const normalizedBlob = blob.type === 'application/pdf'
      ? blob
      : new Blob([blob], { type: 'application/pdf' });

    blobUrl.value = URL.createObjectURL(normalizedBlob);
    updateFrameSrc();
  } catch (err) {
    if (token !== loadToken) return;
    if (err?.name === 'AbortError') return;
    const message = toErrorMessage(err, '加载文档失败');
    error.value = message;
    emit('error', { message, phase: 'load', raw: err });
  } finally {
    if (token === loadToken) {
      loading.value = false;
      if (activeAbortController === controller) {
        activeAbortController = null;
      }
    }
  }
};

const handleFrameLoad = () => {
  ready.value = true;
  error.value = '';
  emit('loaded', {
    pageNo: currentPage(),
    sourceUrl: props.sourceUrl
  });
};

const handleFrameError = () => {
  ready.value = false;
  const message = 'PDF 渲染失败';
  error.value = message;
  emit('error', { message, phase: 'render' });
};

watch(() => props.sourceUrl, () => {
  void loadPdf();
}, { immediate: true });

watch([() => props.pageNo, () => props.yRatio, () => props.navigateKey, () => props.scale], () => {
  updateFrameSrc();
});

onUnmounted(() => {
  loadToken += 1;
  if (activeAbortController && !activeAbortController.signal.aborted) {
    activeAbortController.abort();
  }
  activeAbortController = null;
  revokeBlobUrl();
});
</script>

<template>
  <div class="relative w-full h-full bg-slate-100">
    <iframe
      v-if="frameSrc && !error"
      ref="frameRef"
      :src="frameSrc"
      class="w-full h-full border-0 bg-white"
      loading="eager"
      @load="handleFrameLoad"
      @error="handleFrameError"
    ></iframe>

    <div
      v-if="loading || (frameSrc && !ready && !error)"
      class="absolute inset-0 flex items-center justify-center p-4 bg-slate-50/85"
    >
      <div class="text-xs text-blue-600 bg-blue-50 border border-blue-200 rounded-lg p-3 shadow-sm flex items-center gap-2">
        <svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        正在使用系统 PDFKit 引擎加载文档...
      </div>
    </div>

    <div
      v-if="error"
      class="absolute inset-0 flex items-center justify-center p-4"
    >
      <div class="text-xs text-rose-600 bg-rose-50 border border-rose-200 rounded-lg p-4 text-center max-w-[80%] shadow-sm">
        {{ error }}
      </div>
    </div>
  </div>
</template>
