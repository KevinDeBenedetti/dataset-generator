import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import DatasetView from '../views/DatasetView.vue'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    {
      path: '/',
      name: 'home',
      component: HomeView,
    },
    {
      path: '/datasets',
      name: 'datasets',
      component: DatasetView
    },
    {
      path: '/datasets/:id',
      name: 'dataset-details',
      component: DatasetView
    }
  ],
})

export default router
