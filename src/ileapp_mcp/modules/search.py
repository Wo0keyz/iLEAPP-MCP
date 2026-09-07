from typing import Any

from pydantic import BaseModel

from ileapp_mcp.case import CaseManager
from ileapp_mcp.models import PaginatedResult


class SearchHit(BaseModel):
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
    filtered: list[SearchHit] = []

    # Fast path: search through all TSV files (which are iLEAPP's unified text exports)
    for tsv_path in case.get_all_tsv_files():
        artifact_name = tsv_path.stem
        try:
            for row in case.read_tsv_records(tsv_path):
                # Check if keyword in any string value
                match_found = False
                matched_text = ""
                for k, v in row.items():
                    if v and isinstance(v, str):
                        if kw_lower in v.lower():
                            match_found = True
                            # Snippet extraction
                            idx = v.lower().find(kw_lower)
                            start = max(0, idx - 40)
                            end = min(len(v), idx + len(keyword) + 40)
                            matched_text = (
                                ("..." if start > 0 else "")
                                + v[start:end]
                                + ("..." if end < len(v) else "")
                            )
                            break

                if match_found:
                    total_count += 1
                    if len(filtered) < offset + limit:
                        filtered.append(
                            SearchHit(
                                artifact_name=artifact_name,
                                matched_text=matched_text.strip(),
                                row_data=row,
                            )
                        )
        except Exception:
            pass

    page = filtered[offset : offset + limit]
    has_more = (offset + limit) < total_count

    return PaginatedResult[SearchHit](
        items=page,
        total_count=total_count,
        has_more=has_more,
        limit=limit,
        offset=offset,
        next_offset=(offset + limit) if has_more else None,
    )
