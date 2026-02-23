<script setup>
import { ref, shallowRef, watch, nextTick, onMounted, onUnmounted, computed } from 'vue';
import { apiFetch } from '../services/apiClient';

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
  },
  features: {
    type: Object,
    default: () => ({})
  },
  darkMode: {
    type: Boolean,
    default: false
  }
});

const emit = defineEmits(['export', 'node-click', 'feedback', 'zoom-change']);

const containerRef = ref(null);
const mindMapInstance = shallowRef(null);

let resizeObserver = null;
let fitTimer = null;
let highlightTimer = null;
let updateToken = 0;
let initPromise = null;
let lastHighlightedNode = null;

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

const hasIndexedNodeInTree = (treeRoot) => {
  if (!treeRoot || typeof treeRoot !== 'object') return false;
  const stack = [treeRoot];
  let scanned = 0;
  const MAX_SCAN_NODES = 12000;
  while (stack.length && scanned < MAX_SCAN_NODES) {
    const current = stack.pop();
    scanned += 1;
    const nodeId = String(current?.node_id || '').trim();
    if (nodeId) return true;
    const children = Array.isArray(current?.children) ? current.children : [];
    for (const child of children) {
      if (child && typeof child === 'object') {
        stack.push(child);
      }
    }
  }
  return false;
};

const hasUsableIndexedNodes = computed(() => {
  if (Array.isArray(props.flatNodes) && props.flatNodes.some((node) => {
    if (!node || typeof node !== 'object') return false;
    return String(node.node_id || '').trim() !== '';
  })) {
    return true;
  }
  return hasIndexedNodeInTree(props.tree);
});

const countTreeNodes = (node) => {
  if (!node || !Array.isArray(node.children)) return 0;
  let total = 1;
  for (const child of node.children) {
    total += countTreeNodes(child);
  }
  return total;
};

const estimateMarkdownRichness = (markdown) => {
  if (!markdown) return 0;
  const lines = String(markdown).split('\n');
  let count = 0;
  for (const line of lines) {
    if (/^(#{1,6})\s+.+$/.test(line)) {
      count += 1;
      continue;
    }
    if (/^(\s*)([-*+]|\d+[.)])\s+\S.+$/.test(line)) {
      count += 1;
    }
  }
  return count;
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
  const MAX_MARKDOWN_RENDER_NODES = 1800;
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
  const stack = [{ level: 0, node: root, kind: 'root' }];
  let nodeCount = 0;

  const appendNode = (node, level, kind) => {
    while (stack.length > 1 && stack[stack.length - 1].level >= level) {
      stack.pop();
    }
    stack[stack.length - 1].node.children.push(node);
    stack.push({ level, node, kind });
    nodeCount += 1;
  };

  const extractListTopic = (body) => {
    const normalized = normalizeText(body || '');
    if (!normalized) return '';
    return normalizeText(
      normalized
        .replace(/\*\*(.*?)\*\*/g, '$1')
        .replace(/__(.*?)__/g, '$1')
        .replace(/`([^`]+)`/g, '$1')
    );
  };

  const nearestHeadingLevel = () => {
    for (let i = stack.length - 1; i >= 0; i -= 1) {
      if (stack[i].kind === 'heading') return stack[i].level;
    }
    return 1;
  };

  for (let i = 0; i < lines.length; i += 1) {
    const line = lines[i];
    const headingMatch = line.match(/^(#{1,6})\s+(.+)$/);
    const listMatch = line.match(/^(\s*)([-*+]|\d+[.)])\s+(.+)$/);

    if (headingMatch) {
      const level = headingMatch[1].length;
      const topic = normalizeText(headingMatch[2]);
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
      appendNode(node, level, 'heading');
      continue;
    }

    if (!listMatch) continue;
    if (nodeCount >= MAX_MARKDOWN_RENDER_NODES) continue;

    const indentText = (listMatch[1] || '').replace(/\t/g, '    ');
    const listDepth = Math.floor(indentText.length / 2) + 1;
    const baseLevel = nearestHeadingLevel();
    const level = Math.min(12, Math.max(2, baseLevel + listDepth));
    const topic = extractListTopic(listMatch[3]);
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
    appendNode(node, level, 'list');
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

const shouldPreferMarkdown = computed(() => {
  if (!props.markdown) return false;
  const markdownRichness = estimateMarkdownRichness(props.markdown);
  if (!hasStructuredTree(props.tree)) {
    return markdownRichness > 0;
  }
  const treeRichness = countTreeNodes(props.tree);
  // When we already have a usable indexed tree, keep it to preserve stable nodeId-based interactions.
  if (hasUsableIndexedNodes.value && treeRichness > 2) {
    return false;
  }
  if (treeRichness <= 0) return markdownRichness > 0;
  return markdownRichness >= Math.max(treeRichness * 1.8, treeRichness + 40);
});

const mindMapData = computed(() => {
  if (hasStructuredTree(props.tree) && !shouldPreferMarkdown.value) {
    return buildMindMapNodeFromTree(props.tree, 0);
  }
  return buildMindMapNodeFromMarkdown(props.markdown);
});

const canUseServerPngExport = computed(() => Boolean(props.features?.FEATURE_SERVER_PNG_EXPORT));

const getThemeConfig = () => {
  if (props.darkMode) {
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

const scheduleViewportSync = (delay = 120, token = updateToken, options = {}) => {
  const shouldFit = options.fit !== false;
  if (fitTimer) clearTimeout(fitTimer);
  fitTimer = setTimeout(() => {
    if (!mindMapInstance.value || token !== updateToken) return;
    if (typeof mindMapInstance.value.resize === 'function') {
      mindMapInstance.value.resize();
    }
    if (shouldFit && mindMapInstance.value.view && typeof mindMapInstance.value.view.fit === 'function') {
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

const walkRenderNode = (node, visit) => {
  if (!node) return false;
  if (visit(node)) return true;
  const children = Array.isArray(node.children) ? node.children : [];
  for (const child of children) {
    if (walkRenderNode(child, visit)) return true;
  }
  return false;
};

const findRenderNode = ({ nodeId = '', topic = '' } = {}) => {
  const root = mindMapInstance.value?.renderer?.root;
  if (!root) return null;
  const normalizedTopic = String(topic || '').trim().toLowerCase();
  let matched = null;
  walkRenderNode(root, (node) => {
    const data = typeof node?.getData === 'function' ? node.getData() : (node?.nodeData?.data || {});
    const currentId = String(data?.nodeId || '').trim();
    const currentTopic = String(data?.topic || data?.text || '').trim().toLowerCase();
    if (nodeId && currentId && currentId === nodeId) {
      matched = node;
      return true;
    }
    if (!nodeId && normalizedTopic && currentTopic === normalizedTopic) {
      matched = node;
      return true;
    }
    return false;
  });
  return matched;
};

const focusNode = async (nodeId = '', topic = '') => {
  if (!mindMapInstance.value) {
    await initMindMap();
  }
  const instance = mindMapInstance.value;
  const renderer = instance?.renderer;
  if (!instance || !renderer) return false;

  const target = findRenderNode({ nodeId, topic });
  if (!target) return false;

  if (highlightTimer) {
    clearTimeout(highlightTimer);
    highlightTimer = null;
  }
  if (lastHighlightedNode && typeof lastHighlightedNode.closeHighlight === 'function') {
    lastHighlightedNode.closeHighlight();
  }

  renderer.goTargetNode(target, (resolvedNode) => {
    const finalNode = resolvedNode || target;
    if (finalNode && typeof finalNode.highlight === 'function') {
      finalNode.highlight();
      lastHighlightedNode = finalNode;
      highlightTimer = setTimeout(() => {
        if (finalNode && typeof finalNode.closeHighlight === 'function') {
          finalNode.closeHighlight();
        }
        if (lastHighlightedNode === finalNode) {
          lastHighlightedNode = null;
        }
        highlightTimer = null;
      }, 1600);
    }
  });
  return true;
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
    scheduleViewportSync(140, updateToken, { fit: true });
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
  scheduleViewportSync(120, token, { fit: true });
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

const blobToDataUrl = (blob) => new Promise((resolve, reject) => {
  const reader = new FileReader();
  reader.onload = () => resolve(String(reader.result || ''));
  reader.onerror = () => reject(new Error('Failed to convert blob to data URL'));
  reader.readAsDataURL(blob);
});

const getImageHref = (el) => {
  const href = el.getAttribute('href');
  if (href) return href;
  return el.getAttributeNS('http://www.w3.org/1999/xlink', 'href') || '';
};

const setImageHref = (el, value) => {
  el.setAttribute('href', value);
  el.setAttributeNS('http://www.w3.org/1999/xlink', 'href', value);
};

const STYLE_URL_RE = /url\((['"]?)([^'")]+)\1\)/gi;

const replaceStyleUrls = async (text, resolver) => {
  const src = String(text || '');
  const matches = Array.from(src.matchAll(STYLE_URL_RE));
  if (!matches.length) return src;

  let result = src;
  for (const match of matches) {
    const original = match[0];
    const url = String(match[2] || '').trim();
    if (!url || url.startsWith('data:') || url.startsWith('blob:')) continue;
    const dataUrl = await resolver(url);
    if (!dataUrl) continue;
    result = result.split(original).join(`url("${dataUrl}")`);
  }
  return result;
};

const inlineSvgImageResources = async (svgHTML) => {
  if (!svgHTML) return { svg: svgHTML, unresolved: 0 };
  let doc = null;
  try {
    doc = new DOMParser().parseFromString(svgHTML, 'image/svg+xml');
  } catch {
    return { svg: svgHTML, unresolved: 0 };
  }
  if (!doc) return { svg: svgHTML, unresolved: 0 };

  const images = Array.from(doc.querySelectorAll('image'));
  let unresolved = 0;

  const resolveToDataUrl = async (rawHref) => {
    const source = String(rawHref || '').trim();
    if (!source || source.startsWith('data:') || source.startsWith('blob:')) {
      return source;
    }
    try {
      const absoluteUrl = new URL(source, window.location.origin).toString();
      const resp = await fetch(absoluteUrl, {
        mode: 'cors',
        credentials: 'same-origin'
      });
      if (!resp.ok) {
        unresolved += 1;
        return null;
      }
      const imgBlob = await resp.blob();
      const dataUrl = await blobToDataUrl(imgBlob);
      if (!dataUrl) {
        unresolved += 1;
        return null;
      }
      return dataUrl;
    } catch {
      unresolved += 1;
      return null;
    }
  };

  const tasks = images.map(async (imgEl) => {
    const rawHref = String(getImageHref(imgEl) || '').trim();
    if (!rawHref || rawHref.startsWith('data:') || rawHref.startsWith('blob:')) {
      return;
    }
    const dataUrl = await resolveToDataUrl(rawHref);
    if (dataUrl) {
      setImageHref(imgEl, dataUrl);
    }
  });

  await Promise.all(tasks);

  const styledNodes = Array.from(doc.querySelectorAll('[style]'));
  for (const el of styledNodes) {
    const styleText = el.getAttribute('style');
    if (!styleText || !styleText.includes('url(')) continue;
    const replaced = await replaceStyleUrls(styleText, resolveToDataUrl);
    if (replaced !== styleText) {
      el.setAttribute('style', replaced);
    }
  }

  const styleTags = Array.from(doc.querySelectorAll('style'));
  for (const styleTag of styleTags) {
    const css = styleTag.textContent || '';
    if (!css.includes('url(')) continue;
    const replacedCss = await replaceStyleUrls(css, resolveToDataUrl);
    if (replacedCss !== css) {
      styleTag.textContent = replacedCss;
    }
  }

  return {
    svg: new XMLSerializer().serializeToString(doc),
    unresolved
  };
};

const downloadBlobAsFile = (blob, filename) => {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
};

const exportPngViaServer = async ({ svg, width, height, padding = 20 }) => {
  const response = await apiFetch('/api/export/png', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      svg,
      width,
      height,
      padding,
      background: '#ffffff'
    })
  });

  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const data = await response.json();
      const detail = data?.detail || data;
      message = detail?.message || detail || message;
    } catch {
      // Keep fallback status message.
    }
    throw new Error(message);
  }

  const blob = await response.blob();
  if (!blob || blob.size <= 0) {
    throw new Error('Server PNG export returned empty content');
  }
  downloadBlobAsFile(blob, 'mindmap.png');
};

const exportPNG = async () => {
  if (!mindMapInstance.value) return;

  try {
    const { svgHTML, rect } = mindMapInstance.value.getSvgData({});
    const { svg: safeSvg, unresolved } = await inlineSvgImageResources(svgHTML);

    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    const img = new Image();
    img.crossOrigin = 'anonymous';

    const width = Math.max(1, Math.ceil(rect?.width || 1));
    const height = Math.max(1, Math.ceil(rect?.height || 1));
    canvas.width = width + 40;
    canvas.height = height + 40;

    let localExportError = null;
    if (unresolved === 0) {
      try {
        const svgBlob = new Blob([safeSvg], { type: 'image/svg+xml;charset=utf-8' });
        const svgUrl = URL.createObjectURL(svgBlob);
        const pngBlob = await new Promise((resolve, reject) => {
          img.onload = () => {
            try {
              if (!ctx) {
                reject(new Error('Canvas context is unavailable'));
                return;
              }
              ctx.fillStyle = '#ffffff';
              ctx.fillRect(0, 0, canvas.width, canvas.height);
              ctx.drawImage(img, 20, 20, width, height);

              canvas.toBlob((blob) => {
                if (!blob) {
                  reject(new Error('Canvas export failed: possible CORS taint'));
                  return;
                }
                resolve(blob);
              }, 'image/png');
            } catch (err) {
              reject(err instanceof Error ? err : new Error('PNG rendering failed'));
            } finally {
              URL.revokeObjectURL(svgUrl);
            }
          };
          img.onerror = () => {
            URL.revokeObjectURL(svgUrl);
            reject(new Error('Failed to load generated SVG for PNG export'));
          };
          img.src = svgUrl;
        });
        downloadBlobAsFile(pngBlob, 'mindmap.png');
      } catch (err) {
        localExportError = err instanceof Error ? err : new Error('Local PNG export failed');
      }
    } else {
      localExportError = new Error(`Unresolved SVG assets detected: ${unresolved}`);
    }

    if (localExportError && canUseServerPngExport.value) {
      await exportPngViaServer({ svg: safeSvg, width, height, padding: 20 });
    } else if (localExportError) {
      throw localExportError;
    }

    emit('export', 'png');
  } catch (err) {
    console.error('导出 PNG 失败:', err);
    emit('feedback', {
      type: 'error',
      message: '导出 PNG 失败，请重试'
    });
  }
};

const expandAll = () => {
  if (!mindMapInstance.value) return;
  if (typeof mindMapInstance.value.execCommand === 'function') {
    mindMapInstance.value.execCommand('EXPAND_ALL');
  }
  scheduleViewportSync(100, updateToken, { fit: true });
};

const collapseAll = () => {
  if (!mindMapInstance.value) return;
  if (typeof mindMapInstance.value.execCommand === 'function') {
    mindMapInstance.value.execCommand('UNEXPAND_ALL', false);
  }
  scheduleViewportSync(100, updateToken, { fit: true });
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
      scheduleViewportSync(100, updateToken, { fit: false });
    });
    resizeObserver.observe(containerRef.value);
  }
});

onUnmounted(() => {
  if (fitTimer) {
    clearTimeout(fitTimer);
    fitTimer = null;
  }
  if (highlightTimer) {
    clearTimeout(highlightTimer);
    highlightTimer = null;
  }
  if (lastHighlightedNode && typeof lastHighlightedNode.closeHighlight === 'function') {
    lastHighlightedNode.closeHighlight();
    lastHighlightedNode = null;
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

watch(() => props.darkMode, () => {
  applyTheme();
});

defineExpose({
  exportMarkdown,
  exportXMind,
  exportPNG,
  expandAll,
  collapseAll,
  fitView,
  zoomIn,
  zoomOut,
  getZoomPercent,
  focusNode,
});
</script>

<template>
  <div ref="containerRef" class="mindmap-host w-full h-full bg-slate-50 dark:bg-slate-900"></div>
</template>

<style scoped>
.mindmap-host {
  min-height: 0;
}
</style>
