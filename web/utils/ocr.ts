/**
 * Client-side OCR. The image never leaves the browser -- this module hides
 * the Tesseract worker lifecycle behind one call that takes a File and
 * returns text.
 */
import { createWorker } from "tesseract.js";

export async function extractTextFromImage(file: File): Promise<string> {
  const worker = await createWorker("eng");
  try {
    const {
      data: { text },
    } = await worker.recognize(file);
    return text.trim();
  } finally {
    await worker.terminate();
  }
}
