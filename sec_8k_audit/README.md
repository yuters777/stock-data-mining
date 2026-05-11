# SEC 8-K Retrospective Audit — Phase B

Empirically measures the classification quality gap between `market-engine`'s
current production SEC 8-K handling (naïve regex parser) and a DR-recommended
structural parser approach. Computes disagreement metrics against a SQLite
snapshot of production data and emits a pre-registered GO/NO-GO report.

No LLM calls. No MCP. Pure deterministic Python.

---

## Setup

```bash
python -m venv .venv
# Windows PowerShell
.venv\Scripts\Activate.ps1
# Linux/macOS
source .venv/bin/activate

pip install -r requirements.txt
```

---

## Obtaining the Snapshot

The operator must SSH to the production VPS and run a SQLite dump:

```bash
# On the VPS — run this once, then scp the file locally
sqlite3 /var/lib/market-engine/market_engine.db ".backup /tmp/market_engine_snapshot_$(date +%Y%m%d).db"
scp user@vps-host:/tmp/market_engine_snapshot_*.db ./data/snapshot/
```

Place the `.db` file in `data/snapshot/`. That directory is gitignored.

---

## Run Tests

```bash
pytest tests/ -v
```

All tests use local HTML fixtures; no network calls are made.

---

## Dry Run (subset of 20 filings)

```bash
python -m src.main \
  --snapshot data/snapshot/<snapshot_file>.db \
  --limit 20 \
  --output data/reports/dryrun.md
```

## Full Audit Run

```bash
python -m src.main \
  --snapshot data/snapshot/<snapshot_file>.db \
  --output data/reports/audit_report_$(date +%Y%m%d).md
```

The report is written to `data/reports/` and should be committed after review.

---

## Data Directories

| Directory | Purpose | Committed? |
|-----------|---------|------------|
| `data/snapshot/` | SQLite snapshot from VPS | No (gitignored) |
| `data/bodies/` | Cached EDGAR HTML bodies | No (gitignored) |
| `data/reports/` | Generated markdown reports | Yes |
