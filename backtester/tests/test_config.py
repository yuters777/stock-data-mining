"""Tests for backtester.config — DEFAULT_CONFIG, load_config, validate_config."""

import json
import pytest
from pathlib import Path

from backtester.config import (
    DEFAULT_CONFIG, REQUIRED_KEYS,
    load_config, validate_config,
)


class TestDefaultConfig:
    def test_has_all_required_keys(self):
        """DEFAULT_CONFIG must contain every required key."""
        assert set(DEFAULT_CONFIG.keys()) == REQUIRED_KEYS

    def test_l005_params(self):
        """Key L-005.1 parameters match CLAUDE.md best config."""
        assert DEFAULT_CONFIG["fractal_depth"] == 10
        assert DEFAULT_CONFIG["tolerance_cents"] == 0.05
        assert DEFAULT_CONFIG["tolerance_pct"] == 0.001
        assert DEFAULT_CONFIG["atr_period"] == 5
        assert DEFAULT_CONFIG["min_level_score"] == 5
        assert DEFAULT_CONFIG["tail_ratio_min"] == 0.10
        assert DEFAULT_CONFIG["lp2_engulfing_required"] is True
        assert DEFAULT_CONFIG["clp_min_bars"] == 3
        assert DEFAULT_CONFIG["atr_block_threshold"] == 0.30
        assert DEFAULT_CONFIG["atr_entry_threshold"] == 0.80
        assert DEFAULT_CONFIG["min_rr"] == 3.0  # L-005.1 spec
        assert DEFAULT_CONFIG["max_stop_atr_pct"] == 0.10
        assert DEFAULT_CONFIG["risk_pct"] == 0.003
        assert DEFAULT_CONFIG["slippage_per_share"] == 0.02

    def test_tier_config(self):
        tc = DEFAULT_CONFIG["tier_config"]
        assert tc["mode"] == "2tier_trail"
        assert tc["t1_pct"] == 0.30
        assert tc["trail_factor"] == 0.7

    def test_direction_filter(self):
        df = DEFAULT_CONFIG["direction_filter"]
        assert df["TSLA"] == "long"
        assert df["DEFAULT"] == "short"

    def test_capital_positive(self):
        assert DEFAULT_CONFIG["capital"] > 0

    def test_config_count(self):
        """There should be approximately 60 parameters."""
        # Count leaf params (tier_config is a nested dict with 5 keys)
        flat_count = len(DEFAULT_CONFIG) - 1 + len(DEFAULT_CONFIG["tier_config"])
        assert flat_count >= 55  # ~60 params


class TestValidateConfig:
    def test_valid_default_config(self):
        """DEFAULT_CONFIG should pass validation."""
        errors = validate_config(DEFAULT_CONFIG)
        assert errors == []

    def test_missing_key_raises(self):
        """Missing a required key should raise ValueError."""
        config = {k: v for k, v in DEFAULT_CONFIG.items() if k != "min_rr"}
        with pytest.raises(ValueError, match="Missing required config keys"):
            validate_config(config)

    def test_missing_multiple_keys(self):
        config = {k: v for k, v in DEFAULT_CONFIG.items()
                  if k not in ("min_rr", "capital", "risk_pct")}
        with pytest.raises(ValueError, match="Missing required config keys"):
            validate_config(config)

    def test_bad_type_numeric(self):
        """Non-numeric value for a numeric key should raise."""
        config = DEFAULT_CONFIG.copy()
        config["min_rr"] = "high"
        with pytest.raises(ValueError, match="must be numeric"):
            validate_config(config)

    def test_risk_pct_out_of_range(self):
        config = DEFAULT_CONFIG.copy()
        config["risk_pct"] = 0.50  # 50% — way too high
        with pytest.raises(ValueError, match="risk_pct must be in"):
            validate_config(config)

    def test_negative_capital(self):
        config = DEFAULT_CONFIG.copy()
        config["capital"] = -1000
        with pytest.raises(ValueError, match="capital must be positive"):
            validate_config(config)

    def test_negative_min_rr(self):
        config = DEFAULT_CONFIG.copy()
        config["min_rr"] = -1.0
        with pytest.raises(ValueError, match="min_rr must be positive"):
            validate_config(config)

    def test_bad_tier_config(self):
        config = DEFAULT_CONFIG.copy()
        config["tier_config"] = {"mode": "2tier_trail"}  # missing keys
        with pytest.raises(ValueError, match="tier_config missing keys"):
            validate_config(config)

    def test_tier_config_none_is_valid(self):
        config = DEFAULT_CONFIG.copy()
        config["tier_config"] = None
        errors = validate_config(config)
        assert errors == []


class TestLoadConfig:
    def test_load_overrides(self, tmp_path):
        """Overrides should merge over defaults."""
        override_file = tmp_path / "config.json"
        override_file.write_text(json.dumps({
            "min_rr": 2.0,
            "capital": 200_000.0,
        }))
        config = load_config(override_file)
        assert config["min_rr"] == 2.0
        assert config["capital"] == 200_000.0
        # Non-overridden key stays at default
        assert config["fractal_depth"] == DEFAULT_CONFIG["fractal_depth"]

    def test_load_preserves_defaults(self, tmp_path):
        """Loading an empty override file should return defaults."""
        override_file = tmp_path / "empty.json"
        override_file.write_text("{}")
        config = load_config(override_file)
        assert config == DEFAULT_CONFIG

    def test_load_nonexistent_raises(self):
        with pytest.raises(FileNotFoundError):
            load_config("/nonexistent/path/config.json")

    def test_load_bad_json_raises(self, tmp_path):
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("not json {{{")
        with pytest.raises(json.JSONDecodeError):
            load_config(bad_file)

    def test_load_does_not_mutate_defaults(self, tmp_path):
        """Loading should not modify DEFAULT_CONFIG itself."""
        import copy
        original = copy.deepcopy(DEFAULT_CONFIG)
        override_file = tmp_path / "config.json"
        override_file.write_text(json.dumps({"capital": 999_999.0}))
        load_config(override_file)
        assert DEFAULT_CONFIG == original
