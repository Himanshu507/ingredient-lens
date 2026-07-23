import type { CheckResponse } from "@/lib/api";

const STATUS_LABELS: Record<string, string> = {
  permitted_with_claim: "Permitted (health claim)",
  caution_flagged: "Caution flagged",
  not_a_dietary_ingredient: "Not a dietary ingredient",
  excluded_from_definition: "Excluded from definition",
  safety_standard_unmet: "Safety standard unmet",
  new_ingredient_unmet_safety: "New ingredient, safety unmet",
  premarket_notification_required: "Premarket notification required",
  not_in_database: "Not FDA-flagged",
};

const STATUS_COLORS: Record<string, string> = {
  permitted_with_claim: "bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200",
  not_in_database: "bg-zinc-100 text-zinc-700 dark:bg-zinc-800 dark:text-zinc-300",
};
const DEFAULT_STATUS_COLOR = "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200";

type Props = {
  response: CheckResponse;
};

export default function ResultsList({ response }: Props) {
  return (
    <div className="flex w-full flex-col gap-4">
      <p className="text-sm text-zinc-600 dark:text-zinc-400">{response.summary}</p>
      <ul className="flex flex-col gap-3">
        {response.results.map((result, index) => (
          <li
            key={`${result.submitted_name}-${index}`}
            className="rounded-md border border-zinc-200 p-3 dark:border-zinc-800"
          >
            <div className="flex items-center justify-between gap-2">
              <span className="font-medium">{result.submitted_name}</span>
              <span
                className={`rounded-full px-2 py-1 text-xs font-semibold ${
                  STATUS_COLORS[result.status] ?? DEFAULT_STATUS_COLOR
                }`}
              >
                {STATUS_LABELS[result.status] ?? result.status}
              </span>
            </div>
            {result.reasoning && (
              <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">{result.reasoning}</p>
            )}
            {result.citation && (
              <a
                href={result.citation}
                target="_blank"
                rel="noopener noreferrer"
                className="mt-1 inline-block text-sm text-blue-600 underline dark:text-blue-400"
              >
                Source
              </a>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
