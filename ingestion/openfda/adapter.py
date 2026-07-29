from collections.abc import Iterator

import httpx

from ingestion.openfda.client import DEFAULT_PAGE_SIZE, iter_pages
from ingestion.openfda.models import OpenFdaDrugLabelRecord
from ingestion.openfda.parser import parse_drug_label_record


def fetch_and_parse_drug_labels(
    client: httpx.Client,
    *,
    api_key: str | None = None,
    search: str | None = None,
    page_size: int = DEFAULT_PAGE_SIZE,
    start_skip: int = 0,
) -> Iterator[OpenFdaDrugLabelRecord]:
    """Stream parsed `drug/label` records, one page fetched and processed at a time.

    No canonical model, no database writes here — validate()/transform()/save()
    are Brick 6. This is fetch() + parse() only (ROADMAP.md Brick 5).
    """
    for page in iter_pages(
        client,
        endpoint="drug/label",
        api_key=api_key,
        search=search,
        page_size=page_size,
        start_skip=start_skip,
    ):
        for raw_record in page:
            yield parse_drug_label_record(raw_record)
