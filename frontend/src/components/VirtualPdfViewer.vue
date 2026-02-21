<script setup>
import { ref, shallowRef, watch, onMounted, onUnmounted, nextTick, defineAsyncComponent } from 'vue';

const VuePdfEmbed = defineAsyncComponent(async () => {
  await import('vue-pdf-embed/dist/styles/annotationLayer.css');
  const module = await import('vue-pdf-embed');
  return module.default;
});

let pdfApiPromise = null;
const ensurePdfApi = async () => {
  if (pdfApiPromise) return pdfApiPromise;
  pdfApiPromise = (async () => {
    const [{ getDocument, GlobalWorkerOptions }, { default: pdfWorkerUrl }] = await Promise.all([
      import('pdfjs-dist'),
      import('pdfjs-dist/build/pdf.worker.min.mjs?url')
    ]);
    GlobalWorkerOptions.workerSrc = pdfWorkerUrl;
    return { getDocument };
  })();
  return pdfApiPromise;
};

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
  // Max number of pages to mount at once
  maxMountedPages: {
    type: Number,
    default: 8
  },
  // Number of pages to buffer above/below viewport
  bufferPages: {
    type: Number,
    default: 2
  },
  scale: {
    type: Number,
    default: 1.0
  }
});

const emit = defineEmits(['loaded', 'error']);

const loading = ref(true);
const error = ref('');
const pdfDoc = shallowRef(null);
const totalPages = ref(0);

// Default page dimensions
const pageA4Ratio = 1.414;
const estimatedPageHeight = ref(800);
const pageHeights = ref({});

// For tracking mounted pages via IntersectionObserver
const mountedPages = ref(new Set());
const lastVisiblePage = ref(1);

// Container ref
const containerRef = ref(null);
let observer = null;
let destroyTimeout = null;
let currentLoadingTask = null;
let preloadToken = 0;
let loadToken = 0;

const toErrorMessage = (err, fallback = '加载文档失败') => {
  if (!err) return fallback;
  if (typeof err === 'string' && err.trim()) return err.trim();
  if (typeof err?.message === 'string' && err.message.trim()) return err.message.trim();
  if (typeof err?.detail?.message === 'string' && err.detail.message.trim()) return err.detail.message.trim();
  if (typeof err?.reason === 'string' && err.reason.trim()) return err.reason.trim();
  return fallback;
};

const emitViewerError = (err, phase = 'load', fallback = '加载文档失败') => {
  const message = toErrorMessage(err, fallback);
  error.value = message;
  emit('error', { message, phase, raw: err });
};

// Clean up existing PDF proxy to free memory
const disposeCurrentPdf = async () => {
  preloadToken += 1;
  if (currentLoadingTask) {
    try {
      currentLoadingTask.destroy();
    } catch (e) {
      console.warn('Destruction of incomplete task failed', e);
    }
    currentLoadingTask = null;
  }
  
  if (pdfDoc.value) {
    try {
      await pdfDoc.value.destroy();
    } catch (e) {
      console.warn('PDF destruction failed', e);
    }
    pdfDoc.value = null;
  }
  
  mountedPages.value.clear();
  pageHeights.value = {};
  totalPages.value = 0;
};

// Load the PDF proxy
const loadPdf = async () => {
  if (!props.sourceUrl) return;
  const token = ++loadToken;
  let loadingTask = null;
  loading.value = true;
  error.value = '';
  await disposeCurrentPdf();
  if (token !== loadToken) return;

  try {
    const { getDocument } = await ensurePdfApi();
    loadingTask = getDocument(props.sourceUrl);
    currentLoadingTask = loadingTask;
    const doc = await loadingTask.promise;
    if (token !== loadToken) {
      try {
        await doc.destroy();
      } catch (e) {
        console.warn('Stale PDF destruction failed', e);
      }
      return;
    }
    pdfDoc.value = doc;
    totalPages.value = doc.numPages;
    
    // Estimate height
    if (doc.numPages > 0) {
      const page = await doc.getPage(1);
      if (token !== loadToken) return;
      const viewport = page.getViewport({ scale: 1.0 });
      // Calculate aspect ratio dynamically for initial rendering fallback
      let containerWidth = containerRef.value ? containerRef.value.clientWidth : 800;
      if (containerWidth <= 0) containerWidth = 800;
      const ratio = viewport.height / viewport.width;
      estimatedPageHeight.value = (containerWidth * ratio) * props.scale;
      
      // Preload page heights with bounded concurrency to avoid UI stalls on large PDFs.
      const preloadSeq = ++preloadToken;
      preloadAllPageHeights(doc, containerWidth * props.scale, preloadSeq);
    }
    if (token !== loadToken) return;
    // Mount initial pages
    updateMountedPages(1);
    if (token !== loadToken) return;
    emit('loaded', { numPages: doc.numPages });
  } catch (err) {
    if (token !== loadToken) return;
    // Check if it's a cancellation error (which is expected during rapid switching)
    if (err?.name === 'RenderingCancelledException' || err?.name === 'PromiseCancelledException') {
      return;
    }
    console.error('Failed to load PDF Proxy', err);
    emitViewerError(err, 'load', '加载文档失败');
  } finally {
    if (token === loadToken) {
      loading.value = false;
    }
    if (loadingTask && currentLoadingTask === loadingTask) {
      currentLoadingTask = null;
    }
  }
};

const preloadAllPageHeights = async (doc, defaultWidth, token) => {
  const numToPreload = Math.min(doc.numPages, 1500);
  const maxConcurrent = 6;
  let pageCursor = 1;

  const worker = async () => {
    while (pageCursor <= numToPreload) {
      if (token !== preloadToken) return;
      const pageIndex = pageCursor;
      pageCursor += 1;
      if (pageHeights.value[pageIndex]) continue;
      try {
        const page = await doc.getPage(pageIndex);
        if (token !== preloadToken) return;
        const viewport = page.getViewport({ scale: 1.0 });
        pageHeights.value[pageIndex] = defaultWidth * (viewport.height / viewport.width);
      } catch {
        // Best-effort preloading only.
      }
    }
  };

  const workers = Array.from({ length: Math.min(maxConcurrent, numToPreload) }, () => worker());
  await Promise.all(workers);
};

// Intersection Observer Setup
const setupObserver = () => {
  if (observer) {
    observer.disconnect();
  }
  
  observer = new IntersectionObserver((entries) => {
    // Find the entry with highest intersection ratio
    let maxIntersection = 0;
    let mostVisiblePage = null;
    
    entries.forEach(entry => {
      const pageIndex = Number(entry.target.dataset.pageIndex);
      if (entry.isIntersecting) {
        if (entry.intersectionRatio > maxIntersection) {
          maxIntersection = entry.intersectionRatio;
          mostVisiblePage = pageIndex;
        }
      }
    });

    if (mostVisiblePage) {
      lastVisiblePage.value = mostVisiblePage;
      updateMountedPages(mostVisiblePage);
    }
  }, {
    root: containerRef.value,
    rootMargin: '200px', // Pre-load slightly before entering viewport
    threshold: [0, 0.1, 0.5, 1.0]
  });
};

const observePlaceholders = () => {
  if (!observer || !containerRef.value) return;
  
  // Re-observe all placeholders
  observer.disconnect();
  const placeholders = containerRef.value.querySelectorAll('.pdf-page-placeholder');
  placeholders.forEach(el => observer.observe(el));
};

const updateMountedPages = (centerPage) => {
  if (destroyTimeout) {
    clearTimeout(destroyTimeout);
  }
  
  // Throttle destruction to avoid stutter during fast scrolling
  destroyTimeout = setTimeout(() => {
    const newMounted = new Set(mountedPages.value);
    
    // Determine the desired window of pages based on bufferPages
    const startPage = Math.max(1, centerPage - props.bufferPages);
    const endPage = Math.min(totalPages.value, centerPage + props.bufferPages);
    
    // Add new pages
    for (let i = startPage; i <= endPage; i++) {
      newMounted.add(i);
    }
    
    // If we exceed our max limit, evict the furthest pages
    if (newMounted.size > props.maxMountedPages) {
      const sortedArray = Array.from(newMounted).sort((a, b) => {
        const distA = Math.abs(a - centerPage);
        const distB = Math.abs(b - centerPage);
        // Desired: sort ascending by distance, so furthest are at end
        return distA - distB;
      });
      
      const kept = sortedArray.slice(0, props.maxMountedPages);
      mountedPages.value = new Set(kept);
    } else {
      mountedPages.value = newMounted;
    }
  }, 300); // 300ms debounce
};

// Listeners
watch(() => props.sourceUrl, () => {
  loadPdf();
});

watch(totalPages, async () => {
  await nextTick();
  observePlaceholders();
});

watch(() => props.scale, () => {
  // Clear the pre-calculated heights so they adapt to new scale
  pageHeights.value = {};
  if (pdfDoc.value && containerRef.value) {
     const containerWidth = containerRef.value.clientWidth > 0 ? containerRef.value.clientWidth : 800;
     const token = ++preloadToken;
     preloadAllPageHeights(pdfDoc.value, containerWidth * props.scale, token);
  }
});

const clampRatio = (ratio) => {
  const n = Number(ratio);
  if (!Number.isFinite(n)) return 0.3;
  if (n < 0) return 0;
  if (n > 1) return 1;
  return n;
};

// Navigation
const navigateToTarget = async () => {
  const targetPage = props.pageNo;
  if (!targetPage || targetPage < 1 || targetPage > totalPages.value) return;
  
  // Force mount the target page if it's not mounted
  updateMountedPages(targetPage);
  lastVisiblePage.value = targetPage;
  
  await nextTick();
  
  const container = containerRef.value;
  const pageEl = document.getElementById(`vpdf-page-${targetPage}`);
  
  if (container && pageEl) {
    const pageHeight = pageEl.clientHeight || estimatedPageHeight.value;
    const scrollTarget = pageEl.offsetTop + pageHeight * clampRatio(props.yRatio) - container.clientHeight * 0.3;
    container.scrollTo({ top: scrollTarget, behavior: 'smooth' });
  }
};

watch([() => props.pageNo, () => props.yRatio], () => {
  if (props.pageNo) {
    setTimeout(navigateToTarget, 100);
  }
});

onMounted(() => {
  setupObserver();
  loadPdf();
});

onUnmounted(() => {
  loadToken += 1;
  if (observer) {
    observer.disconnect();
  }
  if (destroyTimeout) {
    clearTimeout(destroyTimeout);
  }
  disposeCurrentPdf();
});

// A small helper to emit rendered state for any inner vue-pdf-embed component
const onPageRendered = (pageIndex) => {
  const pageEl = document.getElementById(`vpdf-page-${pageIndex}`);
  if (pageEl) {
    const inner = pageEl.querySelector('.vue-pdf-embed') || pageEl.firstElementChild;
    const height = inner ? inner.clientHeight : pageEl.clientHeight;
    if (height && height > 100) {
      pageHeights.value[pageIndex] = height;
    }
  }
};
</script>

<template>
  <div ref="containerRef" class="w-full h-full overflow-y-auto overflow-x-hidden bg-slate-100 relative custom-scrollbar">
    
    <div v-if="loading" class="absolute inset-0 flex items-center justify-center p-4">
      <div class="text-xs text-blue-600 bg-blue-50 border border-blue-200 rounded-lg p-3 shadow-sm flex items-center gap-2">
        <svg class="animate-spin h-4 w-4" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
        正在初始化高性能 PDF 引擎...
      </div>
    </div>
    
    <div v-else-if="error" class="absolute inset-0 flex items-center justify-center p-4">
      <div class="text-xs text-red-600 bg-red-50 border border-red-200 rounded-lg p-3 text-center">
        {{ error }}
      </div>
    </div>
    
    <div v-else class="w-full flex flex-col items-center py-4 space-y-4">
      <!-- Virtual Scroller List -->
      <div
        v-for="pageIndex in totalPages"
        :key="pageIndex"
        :data-page-index="pageIndex"
        :id="'vpdf-page-' + pageIndex"
        class="pdf-page-placeholder relative w-full px-4 max-w-4xl mx-auto transition-all shadow-sm rounded-sm"
        :style="{ minHeight: `${pageHeights[pageIndex] || estimatedPageHeight}px` }"
      >
        <div class="bg-white w-full h-full rounded shadow-sm overflow-hidden flex flex-col relative border border-slate-200/60">
          <!-- Page Overlay Loader -->
          <div v-if="!mountedPages.has(pageIndex)" class="absolute inset-0 flex flex-col items-center justify-center bg-slate-50/50">
            <span class="text-slate-300 font-mono text-xs">{{ pageIndex }}</span>
          </div>
          
          <!-- Actual Page Container -->
          <VuePdfEmbed
            v-if="mountedPages.has(pageIndex)"
            :source="pdfDoc"
            :page="pageIndex"
            :scale="props.scale"
            text-layer
            annotation-layer
            class="w-full h-full"
            @rendered="() => onPageRendered(pageIndex)"
            @loading-failed="(err) => emitViewerError(err, 'render', 'PDF 页面加载失败')"
            @rendering-failed="(err) => emitViewerError(err, 'render', 'PDF 页面渲染失败')"
          />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.custom-scrollbar::-webkit-scrollbar {
  width: 8px;
}
.custom-scrollbar::-webkit-scrollbar-track {
  background: transparent;
}
.custom-scrollbar::-webkit-scrollbar-thumb {
  background: rgba(148, 163, 184, 0.4);
  border-radius: 4px;
}
.custom-scrollbar::-webkit-scrollbar-thumb:hover {
  background: rgba(148, 163, 184, 0.6);
}
</style>
