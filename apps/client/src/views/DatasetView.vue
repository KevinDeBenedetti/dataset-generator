<script setup lang="ts">
import { onMounted, computed } from 'vue'
import { storeToRefs } from 'pinia'
import { useDatasetStore } from '@/stores/dataset'
import DatasetTable from '@/components/dataset/DatasetTable.vue'
import LoadingState from '@/components/dataset/LoadingState.vue'
import ErrorState from '@/components/dataset/ErrorState.vue'
import EmptyState from '@/components/dataset/EmptyState.vue'

const datasetStore = useDatasetStore()
const { datasets, loading, error } = storeToRefs(datasetStore)

const hasDatasets = computed(() => datasets.value && datasets.value.length > 0)

onMounted(() => {
  datasetStore.fetchDatasets()
})
</script>

<template>
  <section class="max-w-2xl mx-auto flex flex-col gap-4 w-full">
    <h1 class="mt-6 mb-4 text-3xl font-bold text-center">Datasets</h1>

    <LoadingState v-if="loading" />
    <ErrorState v-else-if="error" />
    <DatasetTable v-else-if="hasDatasets" />
    <EmptyState v-else />
  </section>
</template>
