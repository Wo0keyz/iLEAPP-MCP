from typing import Any

from ileapp_mcp.case import CaseManager, evidence_fields
from ileapp_mcp.models import PaginatedResult, Sourced


class SearchHit(Sourced):
    artifact_name: str
    matched_text: str
    row_data: dict[str, Any]


def global_keyword_search(
    case: CaseManager,
    keyword: str,
    limit: int = 50,
    offset: int = 0,
) -> PaginatedResult[SearchHit]:
    """Perform a global keyword search across all extracted iLEAPP TSV/CSV artifacts."""
    if not case.is_loaded:
        raise ValueError("No case loaded. Please call load_case first.")

    limit = max(1, min(limit, 250))
    offset = max(0, offset)

    kw_lower = keyword.lower()
    total_count = 0
    page: list[SearchHit] = []

    # Rows are read through the csv parser (not split by hand) so that quoted fields and line
    # breaks inside a field keep their record number, which is the provenance of the hit.
    for tsv_path in case.get_all_tsv_files():
        for row in case.iter_tsv_rows(tsv_path):
            value = next((v for v in row.values() if v and kw_lower in v.lower()), None)
            if value is None:
                continue
            total_count += 1
            if offset < total_count <= offset + limit:
                idx = value.lower().find(kw_lower)
                start = max(0, idx - 40)
                end = min(len(value), idx + len(keyword) + 40)
                matched = ("..." if start > 0 else "") + value[start:end]
                matched += "..." if end < len(value) else ""
                page.append(
                    SearchHit(
                        artifact_name=tsv_path.stem,
                        matched_text=matched.strip(),
                        row_data=dict(row),
                        **evidence_fields(row),
                    )
                )

    has_more = (offset + limit) < total_count
    return PaginatedResult[SearchHit](
        items=page,
        total_count=total_count,
        has_more=has_more,
        limit=limit,
        offset=offset,
        next_offset=(offset + limit) if has_more else None,
    )
