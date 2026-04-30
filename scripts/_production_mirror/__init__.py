"""Production mirror layer for backtest harness v1.0.

Mirrors production market-engine module behavior at ~85% fidelity.
Operator-approved 15% gap: no GeoStress/news veto/freshness checks.

Production reference: market-engine HEAD a673359.
"""
MIRROR_VERSION = "1.0"
