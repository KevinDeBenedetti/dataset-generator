<script setup lang="ts">
import { RouterView } from 'vue-router'

import AppHeader from '@/components/app/HeaderNav.vue'
import { Toaster } from '@/components/ui/sonner'
import 'vue-sonner/style.css'
</script>

<template>
  <Toaster />
  <div class="min-h-screen">
    <AppHeader />
    <main>
      <RouterView />
    </main>
  </div>
</template>
