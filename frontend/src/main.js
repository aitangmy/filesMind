import { createApp } from 'vue';
import './style.css';
import App from './App.vue';
import router from './router';

if (typeof window !== 'undefined') {
  window.addEventListener('vite:preloadError', (event) => {
    event.preventDefault();
    console.warn('Chunk preload failed, reloading page to recover.', event);
    window.location.reload();
  });
}

createApp(App).use(router).mount('#app');
