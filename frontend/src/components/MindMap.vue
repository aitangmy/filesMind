<script setup>
import { ref, shallowRef, watch, nextTick, onMounted, onUnmounted, computed } from 'vue';

let mindMapCoreCtor = null;
let mindMapCoreLoader = null;
let xmindPluginReady = false;
let xmindPluginLoader = null;

const ensureMindMapCore = async () => {
  if (mindMapCoreCtor) return mindMapCoreCtor;
  if (!mindMapCoreLoader) {
    mindMapCoreLoader = (async () => {
      const [{ default: MindMapCore }] = await Promise.all([
        import('simple-mind-map'),
        import('simple-mind-map/dist/simpleMindMap.esm.css')
      ]);
      mindMapCoreCtor = MindMapCore;
      return MindMapCore;
    })().finally(() => {
      mindMapCoreLoader = null;
    });
  }
  return mindMapCoreLoader;
};

const ensureXMindExportPlugin = async () => {
  if (xmindPluginReady) return;
  if (!xmindPluginLoader) {
    xmindPluginLoader = (async () => {
      const MindMapCore = await ensureMindMapCore();
      const [{ default: Export }, { default: ExportXMind }] = await Promise.all([
        import('simple-mind-map/src/plugins/Export.js'),
        import('simple-mind-map/src/plugins/ExportXMind.js')
      ]);
      MindMapCore.usePlugin(Export);
      MindMapCore.usePlugin(ExportXMind);
      if (mindMapInstance.value?.addPlugin) {
        mindMapInstance.value.addPlugin(Export);
        mindMapInstance.value.addPlugin(ExportXMind);
      }
      xmindPluginReady = true;
    })().finally(() => {
      xmindPluginLoader = null;
    });
  }
  await xmindPluginLoader;
};

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
  },
  tree: {
    type: Object,
    default: null
  }
});

const emit = defineEmits(['export', 'node-click', 'feedback', 'zoom-change']);

const containerRef = ref(null);
const mindMapInstance = shallowRef(null);

let resizeObserver = null;
let fitTimer = null;
let updateToken = 0;
let darkThemeEnabled = false;
let initPromise = null;

const normalizeText = (value) => String(value || '').replace(/\s+/g, ' ').trim();

const smartWrapText = (text, maxVisualLength = 36) => {
  const str = String(text || '').replace(/\s+/g, ' ').trim();
  if (!str) return '未命名节点';
  if (str.length <= (maxVisualLength / 2)) return str;

  let result = '';
  let currentLineWidth = 0;
  let currentLineText = '';

  for (let i = 0; i < str.length; i++) {
    const char = str[i];
    const charWeight = char.charCodeAt(0) > 255 ? 2 : 1;
    
    const isAtWrapZone = currentLineWidth >= (maxVisualLength - 4);
    const isBreakableChar = /[\s，。、；：！？,.;:!?]/.test(char);

    if (currentLineWidth + charWeight > maxVisualLength) {
      result += currentLineText + '\n';
      currentLineText = char;
      currentLineWidth = charWeight;
    } else if (isAtWrapZone && isBreakableChar) {
      result += currentLineText + char + '\n';
      currentLineText = '';
      currentLineWidth = 0;
    } else {
      currentLineText += char;
      currentLineWidth += charWeight;
    }
  }

  if (currentLineText) {
    result += currentLineText;
  }

  return result.trim();
};

const hasStructuredTree = (tree) => {
  return Boolean(tree && Array.isArray(tree.children) && tree.children.length > 0);
};

const buildMindMapNodeFromTree = (node, depth = 0) => {
  const topic = normalizeText(node?.topic || '');
  const children = Array.isArray(node?.children)
    ? node.children.map((item) => buildMindMapNodeFromTree(item, depth + 1))
    : [];

  return {
    data: {
      text: smartWrapText(topic || `节点 ${depth}`, 40),
      topic: topic || `节点 ${depth}`,
      nodeId: node?.node_id || '',
      level: Number(node?.level ?? depth),
      sourceLineStart: Number(node?.source_line_start || 0),
      sourceLineEnd: Number(node?.source_line_end || 0)
    },
    children
  };
};

const buildMindMapNodeFromMarkdown = (markdown) => {
  const root = {
    data: {
      text: '文档导图',
      topic: '文档导图',
      nodeId: '',
      level: 0,
      sourceLineStart: 0,
      sourceLineEnd: 0
    },
    children: []
  };

  if (!markdown) return root;

  const lines = String(markdown).split('\n');
  const stack = [{ level: 0, node: root }];
  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const match = line.match(/^(#{1,6})\s+(.+)$/);
    if (!match) continue;

    const level = match[1].length;
    const topic = normalizeText(match[2]);
    if (!topic) continue;

    const node = {
      data: {
        text: smartWrapText(topic, 40),
        topic,
        nodeId: '',
        level,
        sourceLineStart: i + 1,
        sourceLineEnd: i + 1
      },
      children: []
    };

    while (stack.length > 1 && stack[stack.length - 1].level >= level) {
      stack.pop();
    }

    stack[stack.length - 1].node.children.push(node);
    stack.push({ level, node });
  }

  if (!root.children.length) {
    const rawText = lines.find((line) => normalizeText(line)) || '空文档';
    const fallbackTopic = normalizeText(rawText);
    root.children.push({
      data: {
        text: smartWrapText(fallbackTopic, 40),
        topic: fallbackTopic,
        nodeId: '',
        level: 1,
        sourceLineStart: 1,
        sourceLineEnd: 1
      },
      children: []
    });
  }

  return root;
};

const mindMapData = computed(() => {
  if (hasStructuredTree(props.tree)) {
    return buildMindMapNodeFromTree(props.tree, 0);
  }
  return buildMindMapNodeFromMarkdown(props.markdown);
});

const getThemeConfig = () => {
  if (darkThemeEnabled) {
    return {
      backgroundColor: '#0f172a',
      lineColor: '#475569',
      lineWidth: 2,
      root: {
        fillColor: '#1d4ed8',
        color: '#f8fafc',
        borderColor: '#1e40af',
        borderWidth: 0,
        borderRadius: 8,
        fontSize: 16,
        fontWeight: 'bold',
        paddingX: 20,
        paddingY: 10
      },
      second: {
        fillColor: '#1e293b',
        color: '#e2e8f0',
        borderColor: '#334155',
        borderWidth: 1,
        borderRadius: 7,
        fontSize: 14,
        fontWeight: 'normal',
        paddingX: 16,
        paddingY: 8
      },
      node: {
        fillColor: '#0b1220',
        color: '#cbd5e1',
        borderColor: '#334155',
        borderWidth: 1,
        borderRadius: 7,
        fontSize: 13,
        fontWeight: 'normal',
        paddingX: 14,
        paddingY: 7
      }
    };
  }

  return {
    backgroundColor: '#f8fafc',
    lineColor: '#94a3b8',
    lineWidth: 2,
    root: {
      fillColor: '#2563eb',
      color: '#ffffff',
      borderColor: '#1d4ed8',
      borderWidth: 0,
      borderRadius: 8,
      fontSize: 16,
      fontWeight: 'bold',
      paddingX: 20,
      paddingY: 10
    },
    second: {
      fillColor: '#ffffff',
      color: '#1e293b',
      borderColor: '#bfdbfe',
      borderWidth: 1,
      borderRadius: 7,
      fontSize: 14,
      fontWeight: 'normal',
      paddingX: 16,
      paddingY: 8
    },
    node: {
      fillColor: '#f8fafc',
      color: '#334155',
      borderColor: '#e2e8f0',
      borderWidth: 1,
      borderRadius: 7,
      fontSize: 13,
      fontWeight: 'normal',
      paddingX: 14,
      paddingY: 7
    }
  };
};

const applyTheme = () => {
  if (!mindMapInstance.value) return;
  mindMapInstance.value.setThemeConfig(getThemeConfig());
};

const getZoomPercent = () => {
  const scale = Number(mindMapInstance.value?.view?.scale || 1);
  if (!Number.isFinite(scale) || scale <= 0) return 100;
  return Math.round(scale * 100);
};

const emitZoomChange = () => {
  emit('zoom-change', {
    zoomPercent: getZoomPercent()
  });
};

const scheduleFit = (delay = 120, token = updateToken) => {
  if (fitTimer) clearTimeout(fitTimer);
  fitTimer = setTimeout(() => {
    if (!mindMapInstance.value || token !== updateToken) return;
    if (typeof mindMapInstance.value.resize === 'function') {
      mindMapInstance.value.resize();
    }
    if (mindMapInstance.value.view && typeof mindMapInstance.value.view.fit === 'function') {
      mindMapInstance.value.view.fit();
    }
    emitZoomChange();
  }, delay);
};

const waitForContainerReady = async () => {
  for (let i = 0; i < 20; i += 1) {
    await nextTick();
    const el = containerRef.value;
    if (el && el.clientWidth > 0 && el.clientHeight > 0) {
      return true;
    }
    await new Promise((resolve) => setTimeout(resolve, 30));
  }
  return false;
};

const handleNodeClick = (node) => {
  const payload = node?.nodeData?.data || {};
  emit('node-click', {
    nodeId: payload.nodeId || '',
    topic: payload.topic || payload.text || '',
    level: Number(payload.level || 0),
    sourceLineStart: Number(payload.sourceLineStart || 0),
    sourceLineEnd: Number(payload.sourceLineEnd || 0)
  });
};

const handleScaleChange = () => {
  emitZoomChange();
};

const initMindMap = async () => {
  if (mindMapInstance.value) return;
  if (initPromise) {
    await initPromise;
    return;
  }
  initPromise = (async () => {
    if (!containerRef.value) return;
    const ready = await waitForContainerReady();
    if (!ready || !containerRef.value || mindMapInstance.value) return;
    const MindMapCore = await ensureMindMapCore();

    const instance = new MindMapCore({
      el: containerRef.value,
      data: mindMapData.value,
      readonly: true,
      layout: 'logicalStructure',
      fit: true,
      textAutoWrapWidth: 280,
      mousewheelAction: 'move',
      openPerformance: true,
      performanceConfig: {
        time: 200,
        padding: 150,
        removeNodeWhenOutCanvas: false
      }
    });

    instance.on('node_click', handleNodeClick);
    instance.on('scale', handleScaleChange);
    mindMapInstance.value = instance;
    applyTheme();
    scheduleFit(140, updateToken);
    emitZoomChange();
  })();
  try {
    await initPromise;
  } finally {
    initPromise = null;
  }
};

const refreshMindMap = async () => {
  const token = ++updateToken;
  if (!mindMapInstance.value) {
    await initMindMap();
    return;
  }
  mindMapInstance.value.setData(mindMapData.value);
  applyTheme();
  scheduleFit(120, token);
};

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

const exportXMind = async () => {
  if (!mindMapInstance.value) return;

  try {
    await ensureXMindExportPlugin();
    await mindMapInstance.value.export('xmind', true, 'mindmap');
    emit('export', 'xmind');
  } catch (err) {
    console.error('导出 XMind 失败:', err);
    emit('feedback', {
      type: 'error',
      message: '导出失败，请重试'
    });
  }
};

const exportPNG = async () => {
  if (!mindMapInstance.value) return;

  try {
    const { svgHTML, rect } = mindMapInstance.value.getSvgData({});
    const svgBlob = new Blob([svgHTML], { type: 'image/svg+xml;charset=utf-8' });
    const svgUrl = URL.createObjectURL(svgBlob);

    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    const img = new Image();

    const width = Math.max(1, Math.ceil(rect?.width || 1));
    const height = Math.max(1, Math.ceil(rect?.height || 1));
    canvas.width = width + 40;
    canvas.height = height + 40;

    img.onload = () => {
      if (!ctx) return;
      ctx.fillStyle = '#ffffff';
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 20, 20, width, height);
      URL.revokeObjectURL(svgUrl);

      canvas.toBlob((blob) => {
        if (!blob) return;
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

    img.src = svgUrl;
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
  darkThemeEnabled = !darkThemeEnabled;
  applyTheme();
};

const expandAll = () => {
  if (!mindMapInstance.value) return;
  if (typeof mindMapInstance.value.execCommand === 'function') {
    mindMapInstance.value.execCommand('EXPAND_ALL');
  }
  scheduleFit(100, updateToken);
};

const collapseAll = () => {
  if (!mindMapInstance.value) return;
  if (typeof mindMapInstance.value.execCommand === 'function') {
    mindMapInstance.value.execCommand('UNEXPAND_ALL', false);
  }
  scheduleFit(100, updateToken);
};

const fitView = () => {
  if (!mindMapInstance.value?.view || typeof mindMapInstance.value.view.fit !== 'function') return;
  mindMapInstance.value.view.fit();
  emitZoomChange();
};

const zoomIn = () => {
  if (!mindMapInstance.value?.view || typeof mindMapInstance.value.view.enlarge !== 'function') return;
  mindMapInstance.value.view.enlarge();
  emitZoomChange();
};

const zoomOut = () => {
  if (!mindMapInstance.value?.view || typeof mindMapInstance.value.view.narrow !== 'function') return;
  mindMapInstance.value.view.narrow();
  emitZoomChange();
};

onMounted(async () => {
  await initMindMap();
  if (containerRef.value && typeof ResizeObserver !== 'undefined') {
    resizeObserver = new ResizeObserver(() => {
      if (!mindMapInstance.value) return;
      scheduleFit(100, updateToken);
    });
    resizeObserver.observe(containerRef.value);
  }
});

onUnmounted(() => {
  if (fitTimer) {
    clearTimeout(fitTimer);
    fitTimer = null;
  }
  if (resizeObserver) {
    resizeObserver.disconnect();
    resizeObserver = null;
  }
  if (mindMapInstance.value) {
    mindMapInstance.value.off('node_click', handleNodeClick);
    mindMapInstance.value.off('scale', handleScaleChange);
    mindMapInstance.value.destroy();
    mindMapInstance.value = null;
  }
  initPromise = null;
});

watch(() => props.tree, () => {
  void refreshMindMap();
});

watch(() => props.markdown, () => {
  if (!hasStructuredTree(props.tree)) {
    void refreshMindMap();
  }
});

defineExpose({
  exportMarkdown,
  exportXMind,
  exportPNG,
  toggleTheme,
  expandAll,
  collapseAll,
  fitView,
  zoomIn,
  zoomOut,
  getZoomPercent,
});
</script>

<template>
  <div ref="containerRef" class="mindmap-host w-full h-full bg-slate-50"></div>
</template>

<style scoped>
.mindmap-host {
  min-height: 0;
}
</style>
