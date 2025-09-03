<script setup lang="ts">
import GenerateStatus from '@/components/GenerateStatus.vue';
import GenerateDataset from '@/components/GenerateDataset.vue';
</script>

<template>
  <main class="p-4 flex flex-col justify-center">
    <section class="min-w-md mx-auto flex flex-col gap-4">
      <h1 class="mt-6 mb-4 text-3xl font-bold text-center">
        Generate a dataset
      </h1>
      <GenerateStatus />
      <GenerateDataset />
    </section>
  </main>
</template>
