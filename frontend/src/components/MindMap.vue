<script setup>
import { ref, onMounted, watch, nextTick, onUnmounted } from 'vue';
import { Transformer } from 'markmap-lib';
import { Markmap } from 'markmap-view';
import { Toolbar } from 'markmap-toolbar';
import 'markmap-toolbar/dist/style.css';

const props = defineProps({
  markdown: {
    type: String,
    required: true,
    default: ''
  }
});

const emit = defineEmits(['export']);

const containerRef = ref(null);
const svgRef = ref(null);
const toolbarRef = ref(null);
const transformer = new Transformer();
let mm_instance = null;

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
    const response = await fetch('/api/export/xmind', {
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
    
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = 'mindmap.xmind';
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
    
    emit('export', 'xmind');
  } catch (err) {
    console.error('导出 XMind 失败:', err);
    alert('导出失败，请重试');
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
  }
};

const updateMap = async () => {
    if (!svgRef.value || !props.markdown) return;

    const { root } = transformer.transform(props.markdown);

    if (mm_instance) {
        mm_instance.setData(root);
        await nextTick();
        setTimeout(() => {
            if (mm_instance) {
                mm_instance.fit();
                mm_instance.render();
            }
        }, 100);
    } else {
        const options = {
            initialExpandLevel: 3, 
            colorFreezeLevel: 3,
            zoom: true,
            pan: true,
            embedGlobalCSS: true,
            duration: 500,
            nodeSpacing: 25,
            radius: 10,
        };
        mm_instance = Markmap.create(svgRef.value, options, root);
        
        await nextTick();
        setTimeout(() => {
            if (mm_instance) {
                mm_instance.fit();
            }
        }, 200);
        
        if (toolbarRef.value) {
            const { el } = Toolbar.create(mm_instance);
            toolbarRef.value.innerHTML = ''; 
            toolbarRef.value.append(el);
        }
    }
};

const handleResize = () => {
    if (mm_instance) {
        setTimeout(() => {
            if (mm_instance) {
                mm_instance.fit();
            }
        }, 200);
    }
};

onMounted(() => {
    updateMap();
    window.addEventListener('resize', handleResize);
});

onUnmounted(() => {
    window.removeEventListener('resize', handleResize);
    if (mm_instance) {
        mm_instance.destroy();
        mm_instance = null;
    }
});

watch(() => props.markdown, () => {
    if (mm_instance) {
        mm_instance.destroy();
        mm_instance = null;
    }
    nextTick(updateMap);
});
</script>

<template>
  <div ref="containerRef" class="relative w-full h-full flex flex-col">
    <!-- 顶部工具栏 -->
    <div class="flex-shrink-0 h-14 bg-white/80 backdrop-blur-xl border-b border-slate-200/60 flex items-center justify-between px-4 z-20">
      <!-- Markmap 工具栏容器 -->
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

/* 思维导图节点样式增强 */
.markmap-foreign {
    filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.04));
}
.markmap-foreign:hover {
    filter: drop-shadow(0 4px 12px rgba(0, 0, 0, 0.08));
}

/* 连接线样式优化 */
.markmap-link {
    stroke-opacity: 0.6;
    stroke-width: 2px;
    transition: stroke-opacity 0.3s ease;
}
.markmap-link:hover {
    stroke-opacity: 0.9;
}

/* 节点背景优化 */
.markmap-node > rect {
    rx: 8;
    ry: 8;
    transition: all 0.2s ease;
}
.markmap-node:hover > rect {
    filter: brightness(0.98);
}

/* 根节点特别样式 */
.markmap-node[data-depth="0"] > rect {
    fill: linear-gradient(135deg, #3b82f6, #8b5cf6) !important;
}
</style>
