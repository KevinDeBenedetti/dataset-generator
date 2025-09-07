<script setup lang="ts">
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'
import type { GeneratedDataset } from '@/types/dataset'

defineProps<{
  result: GeneratedDataset | null
}>()
</script>

<template>
  <div>
    <div v-if="result">
      <Card>
        <CardHeader>
          <CardTitle>{{ result.dataset_name }}</CardTitle>
          <CardDescription>
            <div class="flex flex-wrap gap-2 mt-2">
              <Badge variant="secondary">Model: {{ result.model_qa }}</Badge>
              <Badge variant="secondary">Threshold: {{ result.similarity_threshold }}</Badge>
              <Badge variant="secondary">Language: {{ result.target_language }}</Badge>
            </div>
          </CardDescription>
        </CardHeader>

        <CardContent>
          <div class="mb-4 flex flex-wrap gap-6">
            <div><strong>Total questions:</strong> {{ result.total_questions }}</div>
            <div><strong>Processing time:</strong> {{ result.processing_time.toFixed(2) }}s</div>
          </div>

          <Separator class="my-2" />

          <h4 class="font-semibold mb-2">Q&A Pairs</h4>
          <ScrollArea class="h-64">
            <div class="space-y-3 p-2">
              <div
                v-for="(pair, index) in result.qa_pairs"
                :key="index"
                class="p-3 border border-gray-200 rounded-md bg-white"
              >
                <p class="font-medium">Q: {{ pair.question }}</p>
                <p class="mt-1 text-gray-700">A: {{ pair.answer }}</p>
              </div>
            </div>
          </ScrollArea>
        </CardContent>
      </Card>
    </div>

    <div v-else class="text-gray-500">No results available</div>
  </div>
</template>
