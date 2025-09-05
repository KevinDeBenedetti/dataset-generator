<script setup lang="ts">
import { storeToRefs } from 'pinia'
import { useDatasetStore } from '@/stores/dataset'
import {
  Table,
  TableBody,
  TableCaption,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import DatasetRow from '@/components/dataset/DatasetRow.vue'

const datasetStore = useDatasetStore()
const { datasets } = storeToRefs(datasetStore)
</script>

<template>
  <div class="border rounded-lg overflow-x-auto">
    <Table class="w-full">
      <TableCaption> List of {{ datasets?.length || 0 }} available dataset(s) </TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead>ID</TableHead>
          <TableHead>Name</TableHead>
          <TableHead>Description</TableHead>
          <TableHead class="text-center">Actions</TableHead>
        </TableRow>
      </TableHeader> 
      <TableBody>
        <DatasetRow 
          v-for="dataset in datasets" 
          :key="dataset.id"
          :dataset="dataset"
        />
      </TableBody>
    </Table>
  </div>
</template>
