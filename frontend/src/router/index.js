import { createRouter, createWebHistory } from 'vue-router';

const WorkspaceShell = () => import('../WorkspaceShell.vue');

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
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
    }
  ]
});

export default router;
