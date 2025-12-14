"use client";

import { useMemo } from "react";
import { useParams } from "next/navigation";
import { DatasetDetail, LoadingState } from "@/components/dataset";
import { useDatasets } from "@/hooks";

export default function DatasetDetailPage() {
  const params = useParams();
  const datasetId = params.id as string;

  const { data: datasets, isLoading } = useDatasets();

  const dataset = useMemo(() => {
    return datasets?.find((d) => d.id === datasetId) || null;
  }, [datasets, datasetId]);

  const pageTitle = dataset?.name || "Dataset";

  return (
    <section className="max-w-2xl mx-auto flex flex-col gap-4 w-full p-4">
      <h1 className="mt-6 mb-4 text-3xl font-bold text-center">{pageTitle}</h1>

      {isLoading && <LoadingState />}

      {!isLoading && <DatasetDetail key={dataset?.id} dataset={dataset} />}
    </section>
  );
}
