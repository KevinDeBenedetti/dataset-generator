<script setup lang="ts">
import DatasetRow from '@/components/dataset/DatasetRow.vue'

import type { DatasetResponse } from '@/api/types.gen'

import {
  Table,
  TableBody,
  TableCaption,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'

const props = defineProps<{
  datasets: DatasetResponse[]
}>()
</script>

<template>
  <div class="border rounded-lg overflow-x-auto">
    <Table class="w-full">
      <TableCaption> List of {{ props.datasets?.length || 0 }} available dataset(s) </TableCaption>
      <TableHeader>
        <TableRow>
          <TableHead class="text-center">ID</TableHead>
          <TableHead class="text-center">Name</TableHead>
          <TableHead class="text-center">Description</TableHead>
          <TableHead class="text-center">Actions</TableHead>
          <TableHead class="text-center">Langfuse</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        <DatasetRow
          v-for="dataset in props.datasets"
          :key="dataset.id"
          :dataset="{ ...dataset, description: dataset.description || '' }"
        />
      </TableBody>
    </Table>
  </div>
</template>
