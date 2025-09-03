<script setup lang="ts">
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Separator } from '@/components/ui/separator'
import { ScrollArea } from '@/components/ui/scroll-area'

interface QAPair {
  question: string
  answer: string
  context: string
  confidence: number
}

interface DatasetResult {
  qa_pairs: QAPair[]
  new_pairs: number
  exact_duplicates_skipped: number
  similar_duplicates_skipped: number
  similarity_threshold: number
}

defineProps<{
  result: DatasetResult
}>()
</script>

<template>
  <div class="space-y-6">
    <!-- General Statistics -->
    <Card>
      <CardHeader>
        <CardTitle>Generation Summary</CardTitle>
        <CardDescription>Generated dataset statistics</CardDescription>
      </CardHeader>
      <CardContent>
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
          <div class="text-center">
            <div class="text-2xl font-bold text-green-600">{{ result.new_pairs }}</div>
            <div class="text-sm text-muted-foreground">New pairs</div>
          </div>
          <div class="text-center">
            <div class="text-2xl font-bold text-orange-600">
              {{ result.exact_duplicates_skipped }}
            </div>
            <div class="text-sm text-muted-foreground">Exact duplicates</div>
          </div>
          <div class="text-center">
            <div class="text-2xl font-bold text-blue-600">
              {{ result.similar_duplicates_skipped }}
            </div>
            <div class="text-sm text-muted-foreground">Similar duplicates</div>
          </div>
          <div class="text-center">
            <div class="text-2xl font-bold">{{ result.similarity_threshold }}</div>
            <div class="text-sm text-muted-foreground">Similarity threshold</div>
          </div>
        </div>
      </CardContent>
    </Card>

    <!-- Q&A Pairs List -->
    <Card>
      <CardHeader>
        <CardTitle>Question-Answer Pairs ({{ result.qa_pairs.length }})</CardTitle>
        <CardDescription>Generated dataset with context and confidence level</CardDescription>
      </CardHeader>
      <CardContent>
        <ScrollArea class="h-[600px]">
          <div class="space-y-4">
            <div
              v-for="(pair, index) in result.qa_pairs"
              :key="index"
              class="border rounded-lg p-4 space-y-3"
            >
              <!-- Header with index and confidence -->
              <div class="flex items-center justify-between">
                <Badge variant="outline">Pair {{ index + 1 }}</Badge>
                <Badge
                  :variant="pair.confidence === 1 ? 'default' : 'secondary'"
                  class="flex items-center gap-1"
                >
                  <span class="text-xs">⭐</span>
                  {{ pair.confidence }}
                </Badge>
              </div>

              <!-- Question -->
              <div>
                <h4 class="font-semibold text-blue-700 mb-2">❓ Question</h4>
                <p class="text-sm">{{ pair.question }}</p>
              </div>

              <Separator />

              <!-- Answer -->
              <div>
                <h4 class="font-semibold text-green-700 mb-2">✅ Answer</h4>
                <p class="text-sm">{{ pair.answer }}</p>
              </div>

              <Separator />

              <!-- Context -->
              <div>
                <h4 class="font-semibold text-gray-700 mb-2">📄 Context</h4>
                <p class="text-xs text-muted-foreground italic bg-gray-50 p-2 rounded">
                  {{ pair.context }}
                </p>
              </div>
            </div>
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  </div>
</template>
