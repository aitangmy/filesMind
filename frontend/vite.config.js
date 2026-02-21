import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// https://vitejs.dev/config/
export default defineConfig({
    plugins: [vue()],
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
