import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vitejs.dev/config/
export default defineConfig({
    plugins: [vue()],
    build: {
        rollupOptions: {
            output: {
                entryFileNames: 'assets/[name]-[hash].js',
                chunkFileNames: 'assets/[name]-[hash].js',
                assetFileNames: 'assets/[name]-[hash][extname]',
                manualChunks(id) {
                    if (!id.includes('node_modules')) return;
                    if (id.includes('simple-mind-map/src/plugins/Export')) return 'export-xmind';
                    if (id.includes('pdfjs-dist')) return 'pdfjs';
                    if (id.includes('vue-pdf-embed')) return 'pdf-viewer';
                    if (id.includes('simple-mind-map')) return 'mindmap-vendor';
                    return 'vendor';
                }
            }
        }
    },
    test: {
        include: ['src/**/*.{test,spec}.?(c|m)[jt]s?(x)'],
        environment: 'jsdom'
    },
    resolve: {
        alias: {
            stream: "stream-browserify",
            events: "events"
        }
    },
    server: {
        port: 5173,
        proxy: {
            '/api': {
                target: 'http://localhost:8000',
                changeOrigin: true,
                rewrite: (path) => path.replace(/^\/api/, '')
            }
        }
    }
})
