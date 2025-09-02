<script setup lang="ts">
import GenerateStatus from '@/components/GenerateStatus.vue';
import GenerateDataset from '@/components/GenerateDataset.vue';
</script>

<template>
  <main class="p-4 flex justify-center">
    <section class="min-w-md mx-auto flex flex-col gap-4">
      <GenerateStatus />
      <GenerateDataset />
    </section>
  </main>
</template>
