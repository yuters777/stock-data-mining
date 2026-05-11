"""Generates markdown audit report with pre-registered GO/NO-GO decision."""

from __future__ import annotations

import hashlib
import logging
import time
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)

# Pre-registered GO triggers (any one triggers GO)
_GO_FALSE_NEGATIVE_RATE_PCT = 5.0
_GO_MATERIAL_TRADE_IMPACT_CASES = 2
_GO_MATERIALITY_MISS_RATE_PCT = 10.0

# Pre-registered NO-GO triggers (ALL must be met)
_NOGO_CONCORDANCE_RATE_PCT = 95.0
_NOGO_DOCUMENTED_TRADE_IMPACTS = 0
_NOGO_FALSE_POSITIVE_RATE_PCT = 2.0


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def generate_report(
    comparison_results: list[dict],
    output_path: Path,
    snapshot_metadata: dict,
) -> None:
    """Compute metrics and write markdown audit report.

    Args:
        comparison_results: Output of comparator.compare_classifications.
        output_path: Where to write the .md report.
        snapshot_metadata: Dict with keys: snapshot_path (Path), run_start_time (float),
            total_sec_requests (int), cache_dir (Path).
    """
    total = len(comparison_results)
    if total == 0:
        logger.warning("No comparison results — writing empty report")

    type_counts = Counter(r["disagreement_type"] for r in comparison_results)

    concordance = type_counts.get("CONCORDANCE", 0)
    false_neg = type_counts.get("FALSE_NEGATIVE", 0)
    false_pos = type_counts.get("FALSE_POSITIVE", 0)
    mat_miss = type_counts.get("MATERIALITY_MISS", 0)
    prod_unknown = type_counts.get("PROD_UNKNOWN", 0)

    denominator = total - prod_unknown if (total - prod_unknown) > 0 else 1

    concordance_rate = concordance / denominator * 100
    false_neg_rate = false_neg / denominator * 100
    false_pos_rate = false_pos / denominator * 100
    mat_miss_rate = mat_miss / denominator * 100

    # Trade impact correlation — best-effort
    material_trade_impact_cases: int | str = snapshot_metadata.get(
        "material_trade_impact_cases", "NOT_AVAILABLE"
    )

    # DR item distribution
    dr_item_counter: Counter = Counter()
    for r in comparison_results:
        for item in r.get("structural_items", []):
            dr_item_counter[item] += 1

    # Parser quality
    regex_avg = (
        sum(len(r.get("regex_items", [])) for r in comparison_results) / total
        if total else 0
    )
    structural_avg = (
        sum(len(r.get("structural_items", [])) for r in comparison_results) / total
        if total else 0
    )

    # GO/NO-GO evaluation
    go_triggers: list[tuple[str, bool, str]] = [
        (
            "false_negative_rate_pct >= 5.0",
            false_neg_rate >= _GO_FALSE_NEGATIVE_RATE_PCT,
            f"{false_neg_rate:.2f}% (threshold: {_GO_FALSE_NEGATIVE_RATE_PCT}%)",
        ),
        (
            "material_trade_impact_cases >= 2",
            (
                isinstance(material_trade_impact_cases, int)
                and material_trade_impact_cases >= _GO_MATERIAL_TRADE_IMPACT_CASES
            ),
            str(material_trade_impact_cases),
        ),
        (
            "materiality_miss_rate_pct >= 10.0",
            mat_miss_rate >= _GO_MATERIALITY_MISS_RATE_PCT,
            f"{mat_miss_rate:.2f}% (threshold: {_GO_MATERIALITY_MISS_RATE_PCT}%)",
        ),
    ]

    nogo_triggers: list[tuple[str, bool, str]] = [
        (
            "concordance_rate_pct >= 95.0",
            concordance_rate >= _NOGO_CONCORDANCE_RATE_PCT,
            f"{concordance_rate:.2f}% (threshold: {_NOGO_CONCORDANCE_RATE_PCT}%)",
        ),
        (
            "documented_trade_impacts == 0",
            material_trade_impact_cases == 0
            or material_trade_impact_cases == "NOT_AVAILABLE",
            str(material_trade_impact_cases),
        ),
        (
            "false_positive_rate_pct <= 2.0",
            false_pos_rate <= _NOGO_FALSE_POSITIVE_RATE_PCT,
            f"{false_pos_rate:.2f}% (threshold: {_NOGO_FALSE_POSITIVE_RATE_PCT}%)",
        ),
    ]

    any_go = any(triggered for _, triggered, _ in go_triggers)
    all_nogo = all(triggered for _, triggered, _ in nogo_triggers)

    if any_go:
        verdict = "**GO** — structural parser adoption recommended"
    elif all_nogo:
        verdict = "**NO-GO** — current production acceptable, no upgrade required"
    else:
        verdict = "**AMBIGUOUS** — pre-registered criteria inconclusive, manual review required"

    run_duration = time.time() - snapshot_metadata.get("run_start_time", time.time())
    snapshot_path: Path | None = snapshot_metadata.get("snapshot_path")
    snapshot_sha = _sha256_file(snapshot_path) if snapshot_path and snapshot_path.exists() else "N/A"
    cache_dir: Path | None = snapshot_metadata.get("cache_dir")
    cache_files = len(list(cache_dir.glob("*.html"))) if cache_dir and cache_dir.exists() else 0
    total_sec_requests = snapshot_metadata.get("total_sec_requests", "N/A")

    tickers = sorted(set(r["ticker"] for r in comparison_results if r.get("ticker")))
    snapshot_date = snapshot_metadata.get("snapshot_date", "unknown")

    def _case_table(records: list[dict]) -> str:
        if not records:
            return "_None found._\n"
        lines = [
            "| Accession | Ticker | Date | Prod Class | DR Class | Regex Items | Structural Items | Body URL |",
            "|-----------|--------|------|------------|----------|-------------|-----------------|----------|",
        ]
        for r in records:
            dr = r["dr_classification"]
            lines.append(
                f"| {r['accession_number']} "
                f"| {r.get('ticker','?')} "
                f"| {r.get('filing_date','?')} "
                f"| {r.get('prod_category','?')} "
                f"| {dr.get('category','?')} "
                f"| {', '.join(r.get('regex_items',[]))} "
                f"| {', '.join(r.get('structural_items',[]))} "
                f"| {r.get('primary_doc_url','')} |"
            )
        return "\n".join(lines) + "\n"

    false_neg_records = [r for r in comparison_results if r["disagreement_type"] == "FALSE_NEGATIVE"]
    false_pos_records = [r for r in comparison_results if r["disagreement_type"] == "FALSE_POSITIVE"]
    mat_miss_records = [r for r in comparison_results if r["disagreement_type"] == "MATERIALITY_MISS"]

    item_dist_rows = "\n".join(
        f"| {item} | {count} |"
        for item, count in sorted(dr_item_counter.items(), key=lambda x: -x[1])
    )

    go_rows = "\n".join(
        f"| {name} | {'YES' if met else 'NO'} | {value} |"
        for name, met, value in go_triggers
    )
    nogo_rows = "\n".join(
        f"| {name} | {'MET' if met else 'NOT MET'} | {value} |"
        for name, met, value in nogo_triggers
    )

    report = f"""# SEC 8-K Retrospective Audit — Phase B Report

**Snapshot date:** {snapshot_date}
**Sample size:** {total} filings ({denominator} with known production classification)
**Tickers covered:** {len(tickers)} ({', '.join(tickers[:20])}{'...' if len(tickers) > 20 else ''})

---

## Summary Metrics

| Metric | Count | Rate (of {denominator} classified) |
|--------|-------|------|
| Concordance | {concordance} | {concordance_rate:.2f}% |
| False Negative (missed hard-veto) | {false_neg} | {false_neg_rate:.2f}% |
| False Positive (spurious hard-veto) | {false_pos} | {false_pos_rate:.2f}% |
| Materiality Miss (wrong category) | {mat_miss} | {mat_miss_rate:.2f}% |
| Production Unknown (no prod data) | {prod_unknown} | — |

---

## Parser Quality Comparison

| Parser | Avg Items/Filing |
|--------|-----------------|
| Regex (production baseline) | {regex_avg:.2f} |
| Structural (DR-recommended) | {structural_avg:.2f} |

The structural parser removes TOC entries and citation references. A lower avg items/filing is
expected and indicates higher precision.

---

## Critical Findings

### FALSE NEGATIVE Cases (production missed hard-veto)

{_case_table(false_neg_records)}

### FALSE POSITIVE Cases (production over-triggered hard-veto)

{_case_table(false_pos_records)}

### MATERIALITY MISS Cases (wrong category classification)

{_case_table(mat_miss_records)}

---

## DR-Corrected Item Distribution

| Item | Count |
|------|-------|
{item_dist_rows}

---

## Decision

### GO Triggers (any one triggers GO)

| Trigger | Triggered? | Value |
|---------|------------|-------|
{go_rows}

### NO-GO Triggers (ALL required for NO-GO)

| Trigger | Status | Value |
|---------|--------|-------|
{nogo_rows}

### Verdict

{verdict}

---

## Caveats and Limitations

- Trade impact correlation requires module trade tables not available in snapshot; `material_trade_impact_cases` marked `{material_trade_impact_cases}`.
- Production classification pulled from `news_events.category` / `news_items.classification_status`; rows with NULL production data classified as `PROD_UNKNOWN` and excluded from rate denominators.
- Structural parser uses context window of 50 chars preceding each Item match to detect citations; edge cases near line breaks may affect precision.
- This is a research audit only — not a production deployment recommendation without operator review.

---

## Reproducibility

| Parameter | Value |
|-----------|-------|
| Snapshot SHA-256 | `{snapshot_sha}` |
| EDGAR cache files | {cache_files} |
| Run duration | {run_duration:.1f}s |
| Total SEC requests | {total_sec_requests} |
"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    logger.info("Report written to %s", output_path)
