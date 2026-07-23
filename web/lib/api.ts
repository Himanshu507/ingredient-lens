/**
 * Talks to the one backend route. Hides the fetch call, base URL, and error
 * shape behind a single function -- callers just get typed results or a throw.
 */
export type IngredientCheckResult = {
  submitted_name: string;
  matched_ingredient: string | null;
  status: string;
  reasoning: string | null;
  citation: string | null;
  confidence: number | null;
};

export type CheckResponse = {
  results: IngredientCheckResult[];
  summary: string;
};

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export async function checkIngredients(ingredientsText: string): Promise<CheckResponse> {
  const response = await fetch(`${API_URL}/api/check`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ingredients_text: ingredientsText }),
  });

  if (!response.ok) {
    throw new Error(`check request failed: ${response.status}`);
  }

  return response.json();
}
