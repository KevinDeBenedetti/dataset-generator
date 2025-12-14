"use client";

import { useState, useMemo } from "react";
import { Loader2 } from "lucide-react";
import { QAList } from "./qa-list";
import { PaginationWrapper } from "./pagination-wrapper";
import { useQAByDataset } from "@/hooks/use-qa";
import type { DatasetResponse } from "@/api/types";

interface DatasetDetailProps {
  dataset: DatasetResponse | null;
}

export function DatasetDetail({ dataset }: DatasetDetailProps) {
  const [page, setPage] = useState(1);
  const limit = 10;

  const { data: qaResponse, isLoading } = useQAByDataset(dataset?.id || "", {
    limit,
    offset: (page - 1) * limit,
    enabled: !!dataset?.id,
  });

  const currentPage = useMemo(() => {
    return Math.floor((qaResponse?.offset || 0) / (qaResponse?.limit || 1)) + 1;
  }, [qaResponse]);

  const totalPages = useMemo(() => {
    return Math.ceil((qaResponse?.total_count || 0) / (qaResponse?.limit || 1));
  }, [qaResponse]);

  const handlePageChange = (newPage: number) => {
    setPage(newPage);
  };

  if (!dataset) {
    return (
      <div className="bg-white rounded-lg shadow p-6">
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-gray-500" />
          <span className="ml-2 text-gray-500">Loading dataset...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white rounded-lg shadow p-6">
      <div className="mb-6">
        <h2 className="text-xl font-semibold mb-2">{dataset.name}</h2>
        <p className="text-gray-600 mb-4 break-words whitespace-pre-wrap">
          {dataset.description}
        </p>

        <div className="bg-gray-50 p-4 rounded-lg">
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4 text-sm">
            <div>
              <span className="font-medium">Total Q&A:</span>
              <span className="ml-2">{qaResponse?.total_count ?? "-"}</span>
            </div>
            <div>
              <span className="font-medium">Displayed:</span>
              <span className="ml-2">{qaResponse?.returned_count ?? "-"}</span>
            </div>
            <div>
              <span className="font-medium">Dataset ID:</span>
              <span className="ml-2 text-xs text-gray-600">
                {qaResponse?.dataset_id ?? "-"}
              </span>
            </div>
          </div>
        </div>
      </div>

      {isLoading ? (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="h-6 w-6 animate-spin text-gray-500" />
          <span className="ml-2 text-gray-500">Loading Q&A data...</span>
        </div>
      ) : (
        <>
          <QAList
            qaData={qaResponse?.qa_data || []}
            returnedCount={qaResponse?.returned_count ?? 0}
          />

          {totalPages > 1 && (
            <PaginationWrapper
              className="mt-6"
              total={qaResponse?.total_count ?? 0}
              currentPage={currentPage}
              itemsPerPage={qaResponse?.limit ?? 10}
              onPageChange={handlePageChange}
            />
          )}
        </>
      )}
    </div>
  );
}
