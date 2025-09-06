<script setup lang="ts">
import { onMounted, computed, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useDatasetStore } from '@/stores/dataset'
import { useQAStore } from '@/stores/qa'
import { useRoute } from 'vue-router'
import DatasetTable from '@/components/dataset/DatasetTable.vue'
import DatasetDetail from '@/components/dataset/DatasetDetail.vue'
import LoadingState from '@/components/dataset/LoadingState.vue'
import EmptyState from '@/components/dataset/EmptyState.vue'

const route = useRoute()
const datasetStore = useDatasetStore()
const qaStore = useQAStore()

const { state } = storeToRefs(datasetStore)

const datasetId = computed(() => route.params.id as string | null)
const isLoading = computed(() => state.value.loading)
const datasets = computed(() => state.value.datasets)
const dataset = computed(() => state.value.dataset)
const pageTitle = computed(() => {
  if (dataset.value) {
    return dataset.value.name
  }
  return 'Datasets'
})

watch(
  datasetId,
  async (newId) => {
    if (newId) {
      await datasetStore.selectDataset(newId as string)
      await qaStore.fetchQAByDataset(newId as string)
    }
  },
  { immediate: true },
)

onMounted(async () => {
  if (route.params.id) {
    await datasetStore.selectDataset(route.params.id as string)
    await qaStore.fetchQAByDataset(route.params.id as string)
  } else {
    await datasetStore.fetchDatasets()
  }
  console.log('Mounted DatasetView with datasets:', state.value.datasets)
})
// TODO : Handle errors globally
// TODO : Add pagination
</script>

<template>
  <section class="max-w-2xl mx-auto flex flex-col gap-4 w-full">
    <h1 class="mt-6 mb-4 text-3xl font-bold text-center">
      {{ pageTitle }}
    </h1>

    <LoadingState v-if="isLoading" />

    <DatasetDetail
      v-if="route.params.id"
      :dataset="dataset"
      :qa-data="state.qaData"
      :qa-metadata="state.qaMetadata"
    />

    <DatasetTable v-else :datasets="datasets" />

    <EmptyState v-if="datasets && datasets.length === 0" />
  </section>
</template>
