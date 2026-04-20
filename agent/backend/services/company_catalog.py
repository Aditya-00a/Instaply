from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.services.files import DATA_DIR


CATALOG_PATH = DATA_DIR / "large_company_catalog.json"
USCIS_SPONSOR_CATALOG_PATH = DATA_DIR / "uscis_h1b_sponsors.json"
SCAN_STATE_PATH = DATA_DIR / "company_scan_state.json"
DEFAULT_SECTOR_PRIORITY = [
    "Financials",
    "Information Technology",
    "Industrials",
    "Communication Services",
    "Consumer Discretionary",
    "Health Care",
]
USCIS_EXCLUDED_COMPANY_PATTERNS = (
    "Infosys",
    "Tata Consultancy",
    "Cognizant",
    "Wipro",
    "Hcl",
    "Tech Mahindra",
    "Capgemini",
    "Mindtree",
    "Hexaware",
    "Mphasis",
    "Ltimindtree",
    "Persistent Systems",
)


def load_large_company_catalog() -> list[dict[str, Any]]:
    if not CATALOG_PATH.exists():
        return []
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def load_uscis_sponsor_catalog() -> list[dict[str, Any]]:
    if not USCIS_SPONSOR_CATALOG_PATH.exists():
        return []
    return json.loads(USCIS_SPONSOR_CATALOG_PATH.read_text(encoding="utf-8"))


def _load_scan_state() -> dict[str, Any]:
    if not SCAN_STATE_PATH.exists():
        return {"cursors": {}, "updated_at": ""}
    try:
        payload = json.loads(SCAN_STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"cursors": {}, "updated_at": ""}
    payload.setdefault("cursors", {})
    payload.setdefault("updated_at", "")
    return payload


def _save_scan_state(state: dict[str, Any]) -> None:
    payload = {
        "cursors": {str(key): int(value) for key, value in (state.get("cursors") or {}).items()},
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    SCAN_STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _normalize_company_name(value: str) -> str:
    cleaned = str(value or "").strip().lower()
    cleaned = cleaned.replace("&", " and ")
    cleaned = cleaned.replace(",", " ").replace(".", " ")
    for suffix in (" incorporated", " inc", " corp", " corporation", " company", " co", " holdings", " holding", " group", " llc", " ltd", " plc"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
    return " ".join(cleaned.split())


def _preferred_sectors_for_profile(profile: dict[str, Any]) -> list[str]:
    roles = " ".join(str(item) for item in profile.get("target_roles", []))
    keywords = " ".join(str(item) for item in profile.get("keywords", []))
    text = f"{roles} {keywords}".lower()
    ordered: list[str] = []

    def _add(*sectors: str) -> None:
        for sector in sectors:
            if sector not in ordered:
                ordered.append(sector)

    if any(token in text for token in ("risk", "finance", "financial", "bank", "credit")):
        _add("Financials")
    if any(token in text for token in ("data", "analytics", "ai", "ml", "product", "systems", "implementation", "consult")):
        _add("Information Technology", "Communication Services")
    if any(token in text for token in ("operations", "delivery", "consultant", "strategy")):
        _add("Industrials", "Consumer Discretionary")
    if any(token in text for token in ("health", "care", "biotech", "pharma")):
        _add("Health Care")

    for sector in DEFAULT_SECTOR_PRIORITY:
        if sector not in ordered:
            ordered.append(sector)
    return ordered


def _ranked_catalog(profile: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    catalog = load_large_company_catalog()
    if not profile:
        return catalog

    priority_sectors = _preferred_sectors_for_profile(profile)
    sector_rank = {sector: index for index, sector in enumerate(priority_sectors)}
    return sorted(
        catalog,
        key=lambda item: (
            sector_rank.get(str(item.get("sector") or "").strip(), len(priority_sectors)),
            str(item.get("company") or "").strip().lower(),
        ),
    )


def _rotated_slice(
    records: list[dict[str, Any]],
    *,
    key: str,
    requested: int,
    state: dict[str, Any],
    advance_cursor: bool,
) -> tuple[list[dict[str, Any]], int]:
    if not records or requested <= 0:
        return [], 0
    cursor = int((state.get("cursors") or {}).get(key, 0)) % len(records)
    rotated = records[cursor:] + records[:cursor]
    selected = rotated[: min(requested, len(rotated))]
    if advance_cursor:
        state.setdefault("cursors", {})
        state["cursors"][key] = (cursor + len(selected)) % len(records)
    return selected, cursor


def relevant_company_records(profile: dict[str, Any] | None = None, limit: int = 200) -> list[dict[str, Any]]:
    return _ranked_catalog(profile)[: max(1, int(limit))]


def relevant_company_names(limit: int = 200) -> list[str]:
    catalog = load_large_company_catalog()
    ordered: list[str] = []
    seen: set[str] = set()
    for item in catalog:
        company = str(item.get("company") or "").strip()
        if not company:
            continue
        key = company.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(company)
        if len(ordered) >= max(1, int(limit)):
            break
    return ordered


def select_company_search_pool(
    profile: dict[str, Any],
    limit: int = 200,
    *,
    advance_cursor: bool = False,
) -> dict[str, Any]:
    target_names = [str(name).strip() for name in profile.get("target_companies", []) if str(name).strip()]
    sponsor_names = [str(name).strip() for name in profile.get("sponsor_friendly_companies", []) if str(name).strip()]
    catalog_records = _ranked_catalog(profile)
    uscis_records = load_uscis_sponsor_catalog()
    state = _load_scan_state()
    catalog_keys = {
        _normalize_company_name(str(item.get("company") or "").strip())
        for item in catalog_records
        if str(item.get("company") or "").strip()
    }
    priority_keys = {_normalize_company_name(name) for name in (target_names + sponsor_names)}

    ordered_records: list[dict[str, Any]] = []
    seen: set[str] = set()
    rotating_records: list[dict[str, Any]] = []

    def _push(company: str, reason: str, **extra: Any) -> None:
        key = _normalize_company_name(company)
        if not key or key in seen:
            return
        seen.add(key)
        ordered_records.append({"company": company, "reason": reason, **extra})

    for company in target_names:
        _push(company, "target_company")
    for company in sponsor_names:
        _push(company, "sponsor_friendly")
    remaining_slots = max(0, max(1, int(limit)) - len(ordered_records))

    uscis_source_records = [
        item for item in uscis_records
        if str(item.get("company") or "").strip()
        and (
            _normalize_company_name(str(item.get("company") or "").strip()) in catalog_keys
            or _normalize_company_name(str(item.get("company") or "").strip()) in priority_keys
        )
        and not any(pattern.lower() in str(item.get("company") or "").lower() for pattern in USCIS_EXCLUDED_COMPANY_PATTERNS)
    ]

    raw_target = max(remaining_slots * 2, 200)
    uscis_slice, uscis_cursor = _rotated_slice(
        uscis_source_records,
        key="uscis_h1b_history",
        requested=raw_target,
        state=state,
        advance_cursor=advance_cursor,
    )
    catalog_slice, catalog_cursor = _rotated_slice(
        catalog_records,
        key="large_company_catalog",
        requested=raw_target,
        state=state,
        advance_cursor=advance_cursor,
    )

    max_span = max(len(uscis_slice), len(catalog_slice))
    for index in range(max_span):
        if index < len(uscis_slice):
            item = uscis_slice[index]
            company = str(item.get("company") or "").strip()
            before_count = len(ordered_records)
            _push(
                company,
                "uscis_h1b_history",
                total_approvals=int(item.get("total_approvals") or 0),
                initial_approvals=int(item.get("initial_approvals") or 0),
                top_states=item.get("top_states") or [],
                years=item.get("years") or [],
            )
            if len(ordered_records) > before_count:
                rotating_records.append({"company": company, "reason": "uscis_h1b_history"})
        if len(ordered_records) >= max(1, int(limit)):
            break
        if index < len(catalog_slice):
            item = catalog_slice[index]
            company = str(item.get("company") or "").strip()
            before_count = len(ordered_records)
            _push(
                company,
                "large_company_catalog",
                symbol=str(item.get("symbol") or "").strip(),
                sector=str(item.get("sector") or "").strip(),
                source=str(item.get("source") or "").strip(),
            )
            if len(ordered_records) > before_count:
                rotating_records.append({"company": company, "reason": "large_company_catalog"})
        if len(ordered_records) >= max(1, int(limit)):
            break

    if advance_cursor:
        _save_scan_state(state)

    return {
        "companies": ordered_records[: max(1, int(limit))],
        "cursor_state": state.get("cursors", {}),
        "rotation_start": {
            "uscis_h1b_history": uscis_cursor,
            "large_company_catalog": catalog_cursor,
        },
        "rotating_preview": rotating_records[:10],
    }


def build_company_search_pool(profile: dict[str, Any], limit: int = 200) -> list[dict[str, Any]]:
    return select_company_search_pool(profile, limit=limit, advance_cursor=False)["companies"]
