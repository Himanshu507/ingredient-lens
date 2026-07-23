"use client";

import { useState } from "react";
import { extractTextFromImage } from "@/utils/ocr";

const MAX_TEXT_LENGTH = 5000;
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

type Mode = "paste" | "photo";

type Props = {
  onSubmit: (text: string) => void;
  isSubmitting: boolean;
};

export default function IngredientInput({ onSubmit, isSubmitting }: Props) {
  const [mode, setMode] = useState<Mode>("paste");
  const [text, setText] = useState("");
  const [isReadingImage, setIsReadingImage] = useState(false);
  const [imageError, setImageError] = useState<string | null>(null);

  async function handleFile(file: File) {
    setImageError(null);

    if (!file.type.startsWith("image/")) {
      setImageError("That's not an image file. Try again or type the list manually.");
      return;
    }
    if (file.size > MAX_IMAGE_BYTES) {
      setImageError("Image too large (max 5MB). Try again or type the list manually.");
      return;
    }

    setIsReadingImage(true);
    try {
      const extracted = await extractTextFromImage(file);
      setText(extracted);
    } catch {
      setImageError("Couldn't read that photo clearly -- try again or type it manually.");
    } finally {
      setIsReadingImage(false);
    }
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = text.trim();
    if (trimmed) onSubmit(trimmed.slice(0, MAX_TEXT_LENGTH));
  }

  return (
    <form onSubmit={handleSubmit} className="flex w-full flex-col gap-4">
      <div className="flex gap-2">
        {(["paste", "photo"] as const).map((m) => (
          <button
            key={m}
            type="button"
            onClick={() => setMode(m)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${
              mode === m
                ? "bg-black text-white dark:bg-white dark:text-black"
                : "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300"
            }`}
          >
            {m === "paste" ? "Paste text" : "Upload photo"}
          </button>
        ))}
      </div>

      {mode === "photo" && (
        <div className="flex flex-col gap-2">
          <input
            type="file"
            accept="image/*"
            onChange={(event) => {
              const file = event.target.files?.[0];
              if (file) handleFile(file);
            }}
            className="text-sm"
          />
          {isReadingImage && (
            <p className="text-sm text-zinc-500 dark:text-zinc-400">reading label…</p>
          )}
          {imageError && <p className="text-sm text-red-600 dark:text-red-400">{imageError}</p>}
        </div>
      )}

      <textarea
        value={text}
        onChange={(event) => setText(event.target.value.slice(0, MAX_TEXT_LENGTH))}
        placeholder="Paste an ingredient list, one per line or comma-separated…"
        rows={8}
        maxLength={MAX_TEXT_LENGTH}
        className="w-full rounded-md border border-zinc-300 bg-white p-3 text-sm dark:border-zinc-700 dark:bg-zinc-900"
      />

      <button
        type="submit"
        disabled={isSubmitting || isReadingImage || !text.trim()}
        className="self-start rounded-md bg-black px-4 py-2 text-sm font-medium text-white disabled:opacity-50 dark:bg-white dark:text-black"
      >
        {isSubmitting ? "Checking…" : "Check ingredients"}
      </button>
    </form>
  );
}
