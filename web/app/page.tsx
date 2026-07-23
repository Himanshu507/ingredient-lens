"use client";

import { useState } from "react";
import IngredientInput from "@/components/IngredientInput";
import ResultsList from "@/components/ResultsList";
import { checkIngredients, type CheckResponse } from "@/lib/api";

export default function Home() {
  const [response, setResponse] = useState<CheckResponse | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(text: string) {
    setIsSubmitting(true);
    setError(null);
    try {
      const result = await checkIngredients(text);
      setResponse(result);
    } catch {
      setError("Couldn't reach the checker. Try again in a moment.");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <div className="flex flex-1 flex-col items-center bg-zinc-50 dark:bg-black">
      <main className="flex w-full max-w-2xl flex-col gap-8 px-6 py-16">
        <header>
          <h1 className="text-2xl font-semibold">ingredient lens</h1>
          <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
            Paste an ingredient list or upload a label photo to check FDA regulatory status.
            No login, nothing saved.
          </p>
        </header>

        <IngredientInput onSubmit={handleSubmit} isSubmitting={isSubmitting} />

        {error && <p className="text-sm text-red-600 dark:text-red-400">{error}</p>}
        {response && <ResultsList response={response} />}
      </main>
    </div>
  );
}
