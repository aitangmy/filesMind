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
    <!-- 导出按钮 - 右上角悬浮 -->
    <div class="absolute top-3 right-3 z-20 flex gap-1.5">
      <button 
        @click="exportMarkdown"
        class="px-2.5 py-1.5 text-xs font-medium text-slate-600 bg-white/90 backdrop-blur border border-slate-200 rounded-lg hover:bg-white hover:border-slate-300 transition-all shadow-sm"
        title="导出 Markdown"
      >
        MD
      </button>
      <button 
        @click="exportXMind"
        class="px-2.5 py-1.5 text-xs font-medium text-slate-600 bg-white/90 backdrop-blur border border-slate-200 rounded-lg hover:bg-white hover:border-slate-300 transition-all shadow-sm"
        title="导出 XMind"
      >
        XM
      </button>
      <button 
        @click="exportPNG"
        class="px-2.5 py-1.5 text-xs font-medium text-slate-600 bg-white/90 backdrop-blur border border-slate-200 rounded-lg hover:bg-white hover:border-slate-300 transition-all shadow-sm"
        title="导出 PNG"
      >
        PNG
      </button>
    </div>
    
    <!-- Markmap 工具栏 -->
    <div ref="toolbarRef" class="absolute top-3 left-3 z-20"></div>
    
    <!-- SVG 容器 -->
    <svg ref="svgRef" class="w-full h-full outline-none"></svg>
  </div>
</template>

<style>
.markmap-toolbar {
    background: white !important;
    border: 1px solid #e2e8f0 !important;
    box-shadow: 0 2px 4px rgba(0,0,0,0.1) !important;
    border-radius: 8px !important;
    padding: 4px !important;
}
.markmap-toolbar .mm-toolbar-item {
    color: #64748b !important;
    border-radius: 4px !important;
}
.markmap-toolbar .mm-toolbar-item:hover {
    background-color: #f1f5f9 !important;
    color: #334155 !important;
}
</style>
