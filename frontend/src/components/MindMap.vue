<script setup>
import { ref, onMounted, watch, nextTick, onUnmounted } from 'vue';
import { Transformer } from 'markmap-lib';
import { Markmap } from 'markmap-view';

const props = defineProps({
  markdown: {
    type: String,
    required: true,
    default: ''
  },
  fileId: {
    type: String,
    default: ''
  },
  flatNodes: {
    type: Array,
    default: () => []
  }
});

const emit = defineEmits(['export', 'node-click', 'feedback']);

const containerRef = ref(null);
const svgRef = ref(null);
const transformer = new Transformer();
let mm_instance = null;
let fitTimer = null;
let resizeTimer = null;
let updateToken = 0;
const LARGE_MAP_THRESHOLD = 140;
const TABLE_SEPARATOR_RE = /^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$/;
const PURE_DASH_RE = /^\s*-{5,}\s*$/;

const isTableRowLike = (line) => {
  const text = (line || '').trim();
  if (!text || text.startsWith('#')) return false;
  const pipeMatches = text.match(/\|/g);
  return pipeMatches && pipeMatches.length >= 2;
};

const nearestNonEmptyLine = (lines, index, step) => {
  let i = index + step;
  while (i >= 0 && i < lines.length) {
    const text = lines[i].trim();
    if (text) return text;
    i += step;
  }
  return '';
};

const sanitizeMarkdownForMindmap = (markdown) => {
  if (!markdown) return markdown;
  const lines = markdown.split('\n');
  const cleaned = [];

  for (let i = 0; i < lines.length; i += 1) {
    const raw = lines[i];
    const stripped = raw.trim();
    if (!stripped) {
      cleaned.push(raw);
      continue;
    }

    if (TABLE_SEPARATOR_RE.test(stripped)) {
      continue;
    }

    if (PURE_DASH_RE.test(stripped)) {
      const prev = nearestNonEmptyLine(lines, i, -1);
      const next = nearestNonEmptyLine(lines, i, 1);
      if (isTableRowLike(prev) || isTableRowLike(next)) {
        continue;
      }
    }

    cleaned.push(raw);
  }

  return cleaned.join('\n');
};

const extractNodeLabel = (element) => {
  if (!element) return '';
  const foreign = element.querySelector('foreignObject');
  if (foreign && foreign.textContent) {
    return foreign.textContent.trim();
  }
  const text = element.querySelector('text');
  return text && text.textContent ? text.textContent.trim() : '';
};

const decorateMindmapAppearance = () => {
  if (!svgRef.value) return;

  const nodeElements = Array.from(svgRef.value.querySelectorAll('.markmap-node'));
  nodeElements.forEach((el) => {
    el.classList.remove('fm-root', 'fm-level2', 'fm-leaf', 'fm-branch');
    const datum = el.__data__ || {};
    const depth = Number.isFinite(Number(datum?.depth)) ? Number(datum.depth) : 0;
    const hasChildren = Array.isArray(datum?.children) && datum.children.length > 0;

    el.dataset.depth = String(depth);
    if (depth === 0) el.classList.add('fm-root');
    if (depth === 1) el.classList.add('fm-level2');
    if (hasChildren) el.classList.add('fm-branch');
    else el.classList.add('fm-leaf');
  });

  const links = Array.from(svgRef.value.querySelectorAll('.markmap-link'));
  links.forEach((link) => {
    link.classList.add('fm-link');
    link.setAttribute('fill', 'none');
  });
};

const countNodes = (node) => {
  if (!node) return 0;
  const children = Array.isArray(node.children) ? node.children : [];
  return 1 + children.reduce((acc, child) => acc + countNodes(child), 0);
};

const bindNodeClickHandlers = () => {
  if (!svgRef.value) return;
  const nodeElements = Array.from(svgRef.value.querySelectorAll('.markmap-node'));
  if (!nodeElements.length || !props.flatNodes?.length) return;

  const usedNodeIds = new Set();
  const byLevelAndTopic = new Map();
  const byTopic = new Map();

  for (const item of props.flatNodes) {
    if (!item?.node_id) continue;
    const topic = String(item.topic || '').trim();
    const level = Number(item.level ?? -1);
    const levelKey = `${level}|${topic}`;
    if (!byLevelAndTopic.has(levelKey)) byLevelAndTopic.set(levelKey, []);
    byLevelAndTopic.get(levelKey).push(item);
    if (!byTopic.has(topic)) byTopic.set(topic, []);
    byTopic.get(topic).push(item);
  }

  nodeElements.forEach((el) => {
    const datum = el.__data__ || {};
    let target = null;
    const label = extractNodeLabel(el);
    const depth = Number.isFinite(Number(datum?.depth)) ? Number(datum.depth) : -1;
    const levelKey = `${depth}|${label}`;

    const levelBucket = byLevelAndTopic.get(levelKey) || [];
    while (levelBucket.length) {
      const candidate = levelBucket.shift();
      if (!usedNodeIds.has(candidate.node_id)) {
        target = candidate;
        break;
      }
    }

    if (!target && label) {
      const topicBucket = byTopic.get(label) || [];
      while (topicBucket.length) {
        const candidate = topicBucket.shift();
        if (!usedNodeIds.has(candidate.node_id)) {
          target = candidate;
          break;
        }
      }
    }

    if (!target || !target.node_id) return;
    usedNodeIds.add(target.node_id);
    el.style.cursor = 'pointer';
    el.dataset.nodeId = target.node_id;
    el.onclick = (event) => {
      event.preventDefault();
      event.stopPropagation();
      emit('node-click', {
        nodeId: target.node_id,
        topic: target.topic,
        level: target.level,
        sourceLineStart: target.source_line_start,
        sourceLineEnd: target.source_line_end
      });
    };
  });
};

// 导出为 Markdown 文件
const exportMarkdown = () => {
  if (!props.markdown) return;
  
  const blob = new Blob([props.markdown], { type: 'text/markdown;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'mindmap.md';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
  
  emit('export', 'markdown');
};

// 导出为 XMind 格式
const exportXMind = async () => {
  if (!props.markdown) return;
  
  try {
    const response = props.fileId
      ? await fetch(`/api/export/xmind/${props.fileId}`)
      : await fetch('/api/export/xmind', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            content: props.markdown,
            filename: 'mindmap'
          })
        });
    
    if (!response.ok) {
      throw new Error('导出失败');
    }
    
    const disposition = response.headers.get('Content-Disposition') || '';
    const filenameMatch = disposition.match(/filename="?([^"]+)"?/i);
    const downloadName = filenameMatch ? filenameMatch[1] : 'mindmap.xmind';

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = downloadName;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    
    emit('export', 'xmind');
  } catch (err) {
    console.error('导出 XMind 失败:', err);
    emit('feedback', {
      type: 'error',
      message: '导出失败，请重试'
    });
  }
};

// 导出为 PNG 图片
const exportPNG = async () => {
  if (!svgRef.value || !mm_instance) return;
  
  try {
    const svgElement = svgRef.value;
    const svgData = new XMLSerializer().serializeToString(svgElement);
    
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    const img = new Image();
    
    const bbox = svgElement.getBBox();
    const padding = 40;
    canvas.width = bbox.width + padding * 2;
    canvas.height = bbox.height + padding * 2;
    
    ctx.fillStyle = 'white';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    const svgBlob = new Blob([svgData], { type: 'image/svg+xml;charset=utf-8' });
    const url = URL.createObjectURL(svgBlob);
    
    img.onload = () => {
      ctx.drawImage(img, padding, padding);
      URL.revokeObjectURL(url);
      
      canvas.toBlob((blob) => {
        const pngUrl = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = pngUrl;
        a.download = 'mindmap.png';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(pngUrl);
      }, 'image/png');
    };
    
    img.src = url;
    emit('export', 'png');
  } catch (err) {
    console.error('导出 PNG 失败:', err);
    emit('feedback', {
      type: 'error',
      message: '导出 PNG 失败，请重试'
    });
  }
};

const toggleTheme = () => {
  if (containerRef.value) {
    containerRef.value.classList.toggle('dark-theme');
  }
};

const updateMap = async () => {
    if (!svgRef.value || !props.markdown) return;
    const token = ++updateToken;

    const { root } = transformer.transform(sanitizeMarkdownForMindmap(props.markdown));
    const nodeCount = countNodes(root);
    const isLargeMap = nodeCount >= LARGE_MAP_THRESHOLD;
    if (containerRef.value) {
        containerRef.value.classList.toggle('fm-perf-light', isLargeMap);
    }

    if (mm_instance) {
        mm_instance.setData(root);
        await nextTick();
        if (token !== updateToken || !mm_instance) return;
        if (fitTimer) clearTimeout(fitTimer);
        fitTimer = setTimeout(() => {
            if (!mm_instance || token !== updateToken) return;
            mm_instance.fit();
            decorateMindmapAppearance();
            bindNodeClickHandlers();
        }, 100);
    } else {
        // Remove default Markmap toolbar rendering
        const options = {
            autoFit: true,
            style: (id) => `${id} * { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }`,
            colorFreezeLevel: 3,
            zoom: true,
            pan: true,
            embedGlobalCSS: true,
            duration: isLargeMap ? 0 : 220,
            maxWidth: isLargeMap ? 380 : 460,
            spacingHorizontal: 90,
            spacingVertical: isLargeMap ? 10 : 14,
            nodeSpacing: isLargeMap ? 12 : 18,
            radius: 10,
        };
        mm_instance = Markmap.create(svgRef.value, options, root);
        
        await nextTick();
        if (token !== updateToken || !mm_instance) return;
        if (fitTimer) clearTimeout(fitTimer);
        fitTimer = setTimeout(() => {
            if (!mm_instance || token !== updateToken) return;
            mm_instance.fit();
            decorateMindmapAppearance();
            bindNodeClickHandlers();
        }, 200);
    }
};

const handleResize = () => {
    if (!mm_instance) return;
    if (resizeTimer) clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
        if (mm_instance) mm_instance.fit();
    }, 180);
};

onMounted(() => {
    updateMap();
    window.addEventListener('resize', handleResize);
});

onUnmounted(() => {
    window.removeEventListener('resize', handleResize);
    if (fitTimer) {
        clearTimeout(fitTimer);
        fitTimer = null;
    }
    if (resizeTimer) {
        clearTimeout(resizeTimer);
        resizeTimer = null;
    }
    if (mm_instance) {
        mm_instance.destroy();
        mm_instance = null;
    }
});

watch(() => props.markdown, () => {
    nextTick(updateMap);
});

watch(() => props.flatNodes, () => {
    nextTick(() => {
        decorateMindmapAppearance();
        bindNodeClickHandlers();
    });
}, { deep: true });

defineExpose({
  exportMarkdown,
  exportXMind,
  exportPNG,
  toggleTheme,
});
</script>

<template>
  <div ref="containerRef" class="relative w-full h-full flex flex-col">
    <!-- 顶部工具栏 -->
    <div class="flex-shrink-0 h-14 bg-white/80 backdrop-blur-xl border-b border-slate-200/60 flex items-center justify-between px-4 z-20">
      <!-- 工具栏占位：原生已废弃，转移至外部组件 -->
      <div ref="toolbarRef" class="flex items-center"></div>

      <!-- 导出按钮组 -->
      <div class="flex gap-2">
        <button
          @click="exportMarkdown"
          class="px-3 py-1.5 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-xl hover:bg-gradient-to-r hover:from-blue-50 hover:to-indigo-50 hover:border-blue-300 hover:text-blue-600 transition-all duration-200 shadow-sm hover:shadow-md"
          title="导出 Markdown"
        >
          <span class="flex items-center gap-1.5">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path>
            </svg>
            MD
          </span>
        </button>
        <button
          @click="exportXMind"
          class="px-3 py-1.5 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-xl hover:bg-gradient-to-r hover:from-amber-50 hover:to-orange-50 hover:border-amber-300 hover:text-amber-600 transition-all duration-200 shadow-sm hover:shadow-md"
          title="导出 XMind"
        >
          <span class="flex items-center gap-1.5">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4-4m0 0L8 8m4-4v12"></path>
            </svg>
            XM
          </span>
        </button>
        <button
          @click="exportPNG"
          class="px-3 py-1.5 text-xs font-medium text-slate-600 bg-white border border-slate-200 rounded-xl hover:bg-gradient-to-r hover:from-emerald-50 hover:to-teal-50 hover:border-emerald-300 hover:text-emerald-600 transition-all duration-200 shadow-sm hover:shadow-md"
          title="导出 PNG"
        >
          <span class="flex items-center gap-1.5">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z"></path>
            </svg>
            PNG
          </span>
        </button>
      </div>
    </div>

    <!-- SVG 容器 - 占据剩余空间 -->
    <div class="flex-grow w-full h-full relative overflow-hidden bg-gradient-to-br from-white via-slate-50/30 to-white">
      <svg ref="svgRef" class="w-full h-full outline-none block"></svg>
    </div>
  </div>
</template>

<style>
.markmap-toolbar {
    background: rgba(255, 255, 255, 0.9) !important;
    backdrop-filter: blur(8px);
    border: 1px solid rgba(203, 213, 225, 0.4) !important;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04) !important;
    padding: 6px !important;
    border-radius: 10px !important;
    display: flex !important;
    gap: 6px !important;
}
.markmap-toolbar .mm-toolbar-item {
    color: #64748b !important;
    border-radius: 8px !important;
    width: 32px !important;
    height: 32px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
}
.markmap-toolbar .mm-toolbar-item:hover {
    background: linear-gradient(135deg, rgba(59, 130, 246, 0.1), rgba(147, 51, 234, 0.1)) !important;
    color: #3b82f6 !important;
    transform: translateY(-1px);
    box-shadow: 0 2px 8px rgba(59, 130, 246, 0.2) !important;
}

/* 节点容器与悬停 */
.markmap-node .markmap-foreign {
    transform-origin: center center;
    transition: box-shadow 0.16s ease;
}
.markmap-node:hover .markmap-foreign {
    box-shadow: 0 2px 8px rgba(15, 23, 42, 0.12);
}

/* 默认节点底色 */
.markmap-node .markmap-foreign > div,
.markmap-node foreignObject > div {
    border-radius: 10px !important;
    padding: 4px 8px !important;
    border: 1px solid #cbd5e1 !important;
    background: #f8fafc !important;
    color: #0f172a !important;
    line-height: 1.35 !important;
    white-space: normal !important;
    word-break: break-word !important;
    overflow: visible !important;
    box-sizing: border-box !important;
}

/* 根节点：主色渐变 + 大号粗体 */
.markmap-node.fm-root .markmap-foreign > div,
.markmap-node.fm-root foreignObject > div {
    background: linear-gradient(90deg, #2563eb, #4f46e5) !important;
    color: #ffffff !important;
    border: 0 !important;
    font-size: 1rem !important;
    font-weight: 700 !important;
    padding: 6px 12px !important;
}

/* 二级节点：白底 + 主色边框 */
.markmap-node.fm-level2 .markmap-foreign > div,
.markmap-node.fm-level2 foreignObject > div {
    background: #ffffff !important;
    border: 1px solid #bfdbfe !important;
    color: #1e3a8a !important;
    font-weight: 600 !important;
}

/* 叶子节点：浅灰底 */
.markmap-node.fm-leaf:not(.fm-root):not(.fm-level2) .markmap-foreign > div,
.markmap-node.fm-leaf:not(.fm-root):not(.fm-level2) foreignObject > div {
    background: #f8fafc !important;
    border: 1px solid #e2e8f0 !important;
    color: #334155 !important;
}

/* 连线：浅蓝色曲线风格 */
.markmap-link,
.markmap-link.fm-link {
    stroke: #93c5fd !important;
    stroke-width: 1.8px !important;
    stroke-opacity: 0.8 !important;
    fill: none !important;
}

/* 大图性能模式：禁用高开销效果 */
.fm-perf-light .markmap-node .markmap-foreign {
    transition: none !important;
}
.fm-perf-light .markmap-node:hover .markmap-foreign {
    transform: none !important;
}
</style>
