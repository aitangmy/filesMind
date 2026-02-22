<script setup>
import { ref, shallowRef, watch, onMounted, onUnmounted, nextTick, defineAsyncComponent, computed } from 'vue';

const VuePdfEmbed = defineAsyncComponent(async () => {
  await import('vue-pdf-embed/dist/styles/annotationLayer.css');
  await import('vue-pdf-embed/dist/styles/textLayer.css');
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
  navigateKey: {
    type: Number,
    default: 0
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
const basePageWidth = ref(595);
const containerWidth = ref(0);

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
let preloadDebounceTimer = null;
let preloadAbortController = null;
let preloadRunPromise = null;
let navigateTimer = null;
let navigateToken = 0;
let containerResizeObserver = null;
let rescaleSettledTimer = null;
let scrollNoticeTimer = null;
let internalScrollAdjusting = false;
const renderEpoch = ref(0);
const scrollLimitNotice = ref('');

const PRELOAD_DEBOUNCE_MS = 160;
const PRELOAD_EAGER_PAGES = 12;
const PRELOAD_MAX_PAGES = 1500;
const PRELOAD_CONCURRENCY = 2;
const PAGE_HORIZONTAL_PADDING_PX = 16; // px-2 on each placeholder

const toErrorMessage = (err, fallback = '加载文档失败') => {
  if (!err) return fallback;
  if (typeof err === 'string' && err.trim()) return err.trim();
  if (typeof err?.message === 'string' && err.message.trim()) return err.message.trim();
  if (typeof err?.detail?.message === 'string' && err.detail.message.trim()) return err.detail.message.trim();
  if (typeof err?.reason === 'string' && err.reason.trim()) return err.reason.trim();
  return fallback;
};

const isTransientRenderConflict = (err, phase = 'load') => {
  const name = String(err?.name || '');
  if (name === 'RenderingCancelledException' || name === 'PromiseCancelledException') {
    return true;
  }
  if (phase !== 'render') return false;
  const message = toErrorMessage(err, '');
  return /Cannot use the same canvas during multiple render\(\) operations/i.test(message);
};

const emitViewerError = (err, phase = 'load', fallback = '加载文档失败') => {
  if (isTransientRenderConflict(err, phase)) {
    // Recover from partial canvas paint during rapid resize.
    renderEpoch.value += 1;
    return;
  }
  const message = toErrorMessage(err, fallback);
  error.value = message;
  emit('error', { message, phase, raw: err });
};

const clearPreloadDebounce = () => {
  if (preloadDebounceTimer) {
    clearTimeout(preloadDebounceTimer);
    preloadDebounceTimer = null;
  }
};

const clearNavigateTimer = () => {
  if (navigateTimer) {
    clearTimeout(navigateTimer);
    navigateTimer = null;
  }
};

const clearRescaleSettledTimer = () => {
  if (rescaleSettledTimer) {
    clearTimeout(rescaleSettledTimer);
    rescaleSettledTimer = null;
  }
};

const clearScrollNoticeTimer = () => {
  if (scrollNoticeTimer) {
    clearTimeout(scrollNoticeTimer);
    scrollNoticeTimer = null;
  }
};

const showScrollLimitNotice = (direction) => {
  scrollLimitNotice.value = direction === 'up'
    ? '已到当前可浏览上限，请选择节点重新定位'
    : '已到当前可浏览下限，请选择节点重新定位';
  clearScrollNoticeTimer();
  scrollNoticeTimer = setTimeout(() => {
    scrollLimitNotice.value = '';
    scrollNoticeTimer = null;
  }, 1500);
};

const resolveMountedScrollBounds = () => {
  const container = containerRef.value;
  if (!container || !mountedPages.value.size) return null;
  const sortedPages = Array.from(mountedPages.value).sort((a, b) => a - b);
  const firstPage = sortedPages[0];
  const lastPage = sortedPages[sortedPages.length - 1];
  const firstEl = container.querySelector(`#vpdf-page-${firstPage}`);
  const lastEl = container.querySelector(`#vpdf-page-${lastPage}`);
  if (!firstEl || !lastEl) return null;
  const minScroll = Math.max(0, firstEl.offsetTop - 8);
  const maxScroll = Math.max(
    minScroll,
    lastEl.offsetTop + Math.max(lastEl.clientHeight, 1) - container.clientHeight + 8
  );
  return { minScroll, maxScroll };
};

const clampScrollWithinMountedRange = (directionHint = null) => {
  const container = containerRef.value;
  if (!container || loading.value || !pdfDoc.value) return;
  const bounds = resolveMountedScrollBounds();
  if (!bounds) return;
  const top = container.scrollTop;
  if (top < bounds.minScroll) {
    internalScrollAdjusting = true;
    container.scrollTop = bounds.minScroll;
    requestAnimationFrame(() => {
      internalScrollAdjusting = false;
    });
    showScrollLimitNotice(directionHint || 'up');
    return;
  }
  if (top > bounds.maxScroll) {
    internalScrollAdjusting = true;
    container.scrollTop = bounds.maxScroll;
    requestAnimationFrame(() => {
      internalScrollAdjusting = false;
    });
    showScrollLimitNotice(directionHint || 'down');
  }
};

const onContainerWheel = (event) => {
  const container = containerRef.value;
  if (!container || !pdfDoc.value || !mountedPages.value.size) return;
  const bounds = resolveMountedScrollBounds();
  if (!bounds) return;
  const top = container.scrollTop;
  const scrollingUp = event.deltaY < 0;
  const scrollingDown = event.deltaY > 0;
  if (scrollingUp && top <= bounds.minScroll + 1) {
    event.preventDefault();
    showScrollLimitNotice('up');
    return;
  }
  if (scrollingDown && top >= bounds.maxScroll - 1) {
    event.preventDefault();
    showScrollLimitNotice('down');
  }
};

const onContainerScroll = () => {
  if (internalScrollAdjusting) return;
  clampScrollWithinMountedRange();
};

const cancelScheduledPreload = () => {
  preloadToken += 1;
  clearPreloadDebounce();
  if (preloadAbortController && !preloadAbortController.signal.aborted) {
    preloadAbortController.abort();
  }
  preloadAbortController = null;
};

const waitForPreloadToStop = async (timeoutMs = 500) => {
  const currentRun = preloadRunPromise;
  if (!currentRun) return;
  try {
    await Promise.race([
      currentRun,
      new Promise(resolve => setTimeout(resolve, timeoutMs))
    ]);
  } catch {
    // Best-effort shutdown path.
  } finally {
    if (preloadRunPromise === currentRun) {
      preloadRunPromise = null;
    }
  }
};

const isPreloadCancelled = (token, signal) => token !== preloadToken || signal?.aborted;

const runWhenBrowserIdle = async () => {
  if (typeof window !== 'undefined' && typeof window.requestIdleCallback === 'function') {
    await new Promise(resolve => {
      window.requestIdleCallback(() => resolve(), { timeout: 250 });
    });
    return;
  }
  await new Promise(resolve => setTimeout(resolve, 0));
};

const resolveEffectivePageWidth = (containerWidth) => {
  const width = Number(containerWidth);
  if (!Number.isFinite(width) || width <= 0) {
    return 800;
  }
  return Math.max(240, width - PAGE_HORIZONTAL_PADDING_PX);
};

const baseScale = computed(() => {
  const n = Number(props.scale);
  if (!Number.isFinite(n) || n <= 0) return 1;
  return n;
});

const effectiveScale = computed(() => {
  const availableWidth = resolveEffectivePageWidth(containerWidth.value || containerRef.value?.clientWidth || 0);
  const rawPageWidth = Number(basePageWidth.value || 0);
  if (!Number.isFinite(rawPageWidth) || rawPageWidth <= 0) {
    return baseScale.value;
  }
  const fitScale = availableWidth / rawPageWidth;
  // Auto-shrink to fit pane width; keep caller-provided scale as upper bound.
  return Math.max(0.35, Math.min(baseScale.value, fitScale));
});
const renderScaleKey = computed(() => Math.round(effectiveScale.value * 1000));

// Clean up existing PDF proxy to free memory
const disposeCurrentPdf = async () => {
  navigateToken += 1;
  clearNavigateTimer();
  cancelScheduledPreload();
  await waitForPreloadToStop();
  if (currentLoadingTask) {
    try {
      await Promise.resolve(currentLoadingTask.destroy());
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
      basePageWidth.value = viewport.width;
      estimatedPageHeight.value = viewport.height * effectiveScale.value;
      if (typeof page.cleanup === 'function') page.cleanup();
      
      // Debounce and lazily preload heights to reduce worker pressure during rapid switches.
      schedulePageHeightPreload(doc, effectiveScale.value);
    }
    if (token !== loadToken) return;
    // Mount initial pages
    updateMountedPages(1);
    scheduleNavigateToTarget(0, 10);
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

const preloadPageHeightsBatch = async (doc, renderScale, token, signal, startPage, endPage) => {
  if (startPage > endPage) return;
  let pageCursor = startPage;

  const worker = async () => {
    while (pageCursor <= endPage) {
      if (isPreloadCancelled(token, signal)) return;
      const pageIndex = pageCursor;
      pageCursor += 1;
      if (pageHeights.value[pageIndex]) continue;
      try {
        const page = await doc.getPage(pageIndex);
        if (isPreloadCancelled(token, signal)) {
          if (typeof page.cleanup === 'function') page.cleanup();
          return;
        }
        const viewport = page.getViewport({ scale: renderScale });
        pageHeights.value[pageIndex] = viewport.height;
        if (typeof page.cleanup === 'function') page.cleanup();
      } catch {
        // Best-effort preloading only.
      }
    }
  };

  const workers = Array.from(
    { length: Math.min(PRELOAD_CONCURRENCY, endPage - startPage + 1) },
    () => worker()
  );
  await Promise.all(workers);
};

const preloadAllPageHeights = async (doc, renderScale, token, signal) => {
  const numToPreload = Math.min(doc.numPages, PRELOAD_MAX_PAGES);
  if (numToPreload <= 0) return;

  const eagerEnd = Math.min(numToPreload, PRELOAD_EAGER_PAGES);
  await preloadPageHeightsBatch(doc, renderScale, token, signal, 1, eagerEnd);
  if (isPreloadCancelled(token, signal) || eagerEnd >= numToPreload) return;

  await runWhenBrowserIdle();
  if (isPreloadCancelled(token, signal)) return;

  await preloadPageHeightsBatch(doc, renderScale, token, signal, eagerEnd + 1, numToPreload);
};

const schedulePageHeightPreload = (doc, renderScale) => {
  if (!doc || !Number.isFinite(renderScale) || renderScale <= 0) return;

  cancelScheduledPreload();
  const token = preloadToken;
  const controller = new AbortController();
  preloadAbortController = controller;

  preloadDebounceTimer = setTimeout(() => {
    preloadDebounceTimer = null;
    const run = preloadAllPageHeights(doc, renderScale, token, controller.signal)
      .catch(() => {
        // Best-effort preloading only.
      })
      .finally(() => {
        if (preloadRunPromise === run) {
          preloadRunPromise = null;
        }
        if (preloadAbortController === controller) {
          preloadAbortController = null;
        }
      });
    preloadRunPromise = run;
  }, PRELOAD_DEBOUNCE_MS);
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
  if (props.pageNo) {
    scheduleNavigateToTarget(40, 8);
  }
});

watch(effectiveScale, () => {
  // Clear the pre-calculated heights so they adapt to fit scale changes
  pageHeights.value = {};
  renderEpoch.value += 1;
  clearRescaleSettledTimer();
  // Run one extra rerender when resize settles to avoid half-drawn pages.
  rescaleSettledTimer = setTimeout(() => {
    renderEpoch.value += 1;
    rescaleSettledTimer = null;
  }, 120);
  if (pdfDoc.value) {
     schedulePageHeightPreload(pdfDoc.value, effectiveScale.value);
  }
  if (props.pageNo) {
    scheduleNavigateToTarget(32, 4);
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
  if (!targetPage || targetPage < 1 || targetPage > totalPages.value) return false;
  
  // Force mount the target page if it's not mounted
  updateMountedPages(targetPage);
  lastVisiblePage.value = targetPage;
  
  await nextTick();
  
  const container = containerRef.value;
  const pageEl = container?.querySelector(`#vpdf-page-${targetPage}`);
  
  if (container && pageEl) {
    const renderedEl = pageEl.querySelector('.vue-pdf-embed');
    const renderedHeight = renderedEl?.clientHeight || 0;
    const cachedHeight = Number(pageHeights.value[targetPage] || 0);
    const pageHeight = (
      (cachedHeight > 100 && cachedHeight) ||
      (renderedHeight > 100 && renderedHeight) ||
      pageEl.clientHeight ||
      estimatedPageHeight.value
    );
    const scrollTarget = pageEl.offsetTop + pageHeight * clampRatio(props.yRatio) - container.clientHeight * 0.18;
    container.scrollTo({ top: Math.max(0, scrollTarget), left: 0, behavior: 'auto' });
    return Boolean(renderedEl && renderedHeight > 100);
  }
  return false;
};

const scheduleNavigateToTarget = (delayMs = 80, retries = 6, token = ++navigateToken) => {
  clearNavigateTimer();
  navigateTimer = setTimeout(async () => {
    if (token !== navigateToken) return;
    const targetPage = Number(props.pageNo);
    if (!Number.isFinite(targetPage) || targetPage < 1) return;
    if (!totalPages.value || targetPage > totalPages.value) {
      if (retries > 0) {
        scheduleNavigateToTarget(120, retries - 1, token);
      }
      return;
    }
    const container = containerRef.value;
    const pageEl = container?.querySelector(`#vpdf-page-${targetPage}`);
    if (!container || !pageEl) {
      if (retries > 0) {
        scheduleNavigateToTarget(120, retries - 1, token);
      }
      return;
    }
    const rendered = await navigateToTarget();
    if (!rendered && retries > 0) {
      scheduleNavigateToTarget(90, retries - 1, token);
    }
  }, delayMs);
};

watch([() => props.pageNo, () => props.yRatio, () => props.navigateKey], () => {
  if (props.pageNo) {
    scheduleNavigateToTarget(80, 8);
  }
}, { immediate: true });

onMounted(() => {
  setupObserver();
  nextTick(() => {
    containerWidth.value = containerRef.value?.clientWidth || 0;
    const container = containerRef.value;
    if (container) {
      container.addEventListener('wheel', onContainerWheel, { passive: false });
      container.addEventListener('scroll', onContainerScroll, { passive: true });
    }
  });
  if (typeof ResizeObserver !== 'undefined') {
    containerResizeObserver = new ResizeObserver(() => {
      containerWidth.value = containerRef.value?.clientWidth || 0;
    });
    if (containerRef.value) {
      containerResizeObserver.observe(containerRef.value);
    }
  }
  loadPdf();
});

onUnmounted(() => {
  loadToken += 1;
  navigateToken += 1;
  clearNavigateTimer();
  clearRescaleSettledTimer();
  clearScrollNoticeTimer();
  if (observer) {
    observer.disconnect();
  }
  if (destroyTimeout) {
    clearTimeout(destroyTimeout);
  }
  if (containerResizeObserver) {
    containerResizeObserver.disconnect();
    containerResizeObserver = null;
  }
  const container = containerRef.value;
  if (container) {
    container.removeEventListener('wheel', onContainerWheel);
    container.removeEventListener('scroll', onContainerScroll);
  }
  void disposeCurrentPdf();
});

// A small helper to emit rendered state for any inner vue-pdf-embed component
const onPageRendered = (pageIndex) => {
  const pageEl = document.getElementById(`vpdf-page-${pageIndex}`);
  if (pageEl) {
    const inner = pageEl.querySelector('.vue-pdf-embed') || pageEl.firstElementChild;
    const height = inner ? inner.clientHeight : pageEl.clientHeight;
    if (height && height > 100) {
      pageHeights.value[pageIndex] = height;
      if (Number(props.pageNo) === Number(pageIndex)) {
        scheduleNavigateToTarget(16, 2);
      }
    }
  }
};

const handlePageLoadingFailed = (err) => {
  emitViewerError(err, 'render', 'PDF 页面加载失败');
};

const handlePageRenderingFailed = (err) => {
  emitViewerError(err, 'render', 'PDF 页面渲染失败');
};
</script>

<template>
  <div ref="containerRef" class="w-full h-full overflow-y-auto overflow-x-auto bg-slate-100 relative custom-scrollbar">
    <div v-if="scrollLimitNotice" class="pointer-events-none sticky top-3 z-30 w-full flex justify-center px-3">
      <div class="rounded-lg border border-amber-200 bg-amber-50/95 px-3 py-1.5 text-[11px] text-amber-700 shadow-sm">
        {{ scrollLimitNotice }}
      </div>
    </div>
    
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
        class="pdf-page-placeholder relative w-full px-2 transition-all shadow-sm rounded-sm"
        :style="{ minHeight: `${pageHeights[pageIndex] || estimatedPageHeight}px` }"
      >
        <div class="bg-white w-full min-h-full rounded shadow-sm overflow-visible flex flex-col relative border border-slate-200/60">
          <!-- Page Overlay Loader -->
          <div v-if="!mountedPages.has(pageIndex)" class="absolute inset-0 flex flex-col items-center justify-center bg-slate-50/50">
            <span class="text-slate-300 font-mono text-xs">{{ pageIndex }}</span>
          </div>
          
          <!-- Actual Page Container -->
          <VuePdfEmbed
            v-if="mountedPages.has(pageIndex)"
            :key="`pdf-page-${pageIndex}-${renderScaleKey}-${renderEpoch}`"
            :source="pdfDoc"
            :page="pageIndex"
            :scale="effectiveScale"
            :text-layer="false"
            annotation-layer
            class="pdf-page-embed w-full"
            @rendered="() => onPageRendered(pageIndex)"
            @loading-failed="handlePageLoadingFailed"
            @rendering-failed="handlePageRenderingFailed"
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

.pdf-page-embed :deep(canvas) {
  width: 100% !important;
  height: auto !important;
}
</style>
