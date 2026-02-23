import { createRouter, createWebHashHistory, createWebHistory } from 'vue-router';
import WorkspaceShell from '../WorkspaceShell.vue';

// Use hash history in production bundles to avoid blank screens at /index.html
// under desktop webviews (e.g. tauri.localhost).
const useHashHistory = !import.meta.env.DEV;

const router = createRouter({
  history: useHashHistory ? createWebHashHistory() : createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/workspace'
    },
    {
      path: '/index.html',
      redirect: '/workspace'
    },
    {
      path: '/workspace',
      name: 'workspace',
      component: WorkspaceShell,
      props: { routeMode: 'workspace' }
    },
    {
      path: '/settings',
      name: 'settings',
      component: WorkspaceShell,
      props: { routeMode: 'settings' }
    },
    {
      path: '/:pathMatch(.*)*',
      name: 'fallback-workspace',
      component: WorkspaceShell,
      props: { routeMode: 'workspace' }
    }
  ]
});

export default router;
