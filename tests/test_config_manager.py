"""
Unit tests for core.config_manager.ConfigManager.
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config_manager import ConfigManager, _builtin_defaults


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _valid_config() -> dict:
    cfg = _builtin_defaults()
    cfg["auth_key"] = "myStrongSecret123456"
    cfg["script_id"] = "AKfycbyRealDeploymentId1234567890abcdef"
    return cfg


@pytest.fixture()
def tmp_cm(tmp_path):
    cfg_path = tmp_path / "config.json"
    return ConfigManager(config_path=cfg_path)


# ── get_defaults ──────────────────────────────────────────────────────────────

def test_get_defaults_returns_dict(tmp_cm):
    defaults = tmp_cm.get_defaults()
    assert isinstance(defaults, dict)
    assert "auth_key" in defaults
    assert "script_id" in defaults
    assert "http_port" in defaults


def test_get_defaults_has_required_fields(tmp_cm):
    d = tmp_cm.get_defaults()
    for key in ("google_ip", "front_domains", "exit_node", "adblock_lists"):
        assert key in d, f"Missing default key: {key}"


# ── validate ──────────────────────────────────────────────────────────────────

def test_validate_valid_config(tmp_cm):
    errors = tmp_cm.validate(_valid_config())
    assert errors == []


def test_validate_empty_auth_key(tmp_cm):
    cfg = _valid_config()
    cfg["auth_key"] = ""
    errors = tmp_cm.validate(cfg)
    assert any("auth_key" in e for e in errors)


def test_validate_placeholder_auth_key(tmp_cm):
    cfg = _valid_config()
    cfg["auth_key"] = "CHANGE_ME_TO_A_STRONG_SECRET"
    errors = tmp_cm.validate(cfg)
    assert any("auth_key" in e for e in errors)


def test_validate_no_script_id(tmp_cm):
    cfg = _valid_config()
    cfg["script_id"] = ""
    cfg["script_ids"] = []
    errors = tmp_cm.validate(cfg)
    assert any("script" in e.lower() for e in errors)


def test_validate_placeholder_script_id(tmp_cm):
    cfg = _valid_config()
    cfg["script_id"] = "YOUR_APPS_SCRIPT_DEPLOYMENT_ID"
    errors = tmp_cm.validate(cfg)
    assert any("script" in e.lower() for e in errors)


def test_validate_duplicate_ports(tmp_cm):
    cfg = _valid_config()
    cfg["http_port"] = 8085
    cfg["socks5_port"] = 8085
    errors = tmp_cm.validate(cfg)
    assert any("port" in e.lower() for e in errors)


def test_validate_invalid_port(tmp_cm):
    cfg = _valid_config()
    cfg["http_port"] = 99999
    errors = tmp_cm.validate(cfg)
    assert any("http_port" in e for e in errors)


def test_validate_invalid_google_ip(tmp_cm):
    cfg = _valid_config()
    cfg["google_ip"] = "not.an.ip.address"
    errors = tmp_cm.validate(cfg)
    assert any("google_ip" in e for e in errors)


def test_validate_exit_node_no_url(tmp_cm):
    cfg = _valid_config()
    cfg["exit_node"]["enabled"] = True
    cfg["exit_node"]["url"] = ""
    cfg["exit_node"]["psk"] = "somepsk"
    errors = tmp_cm.validate(cfg)
    assert any("exit_node.url" in e for e in errors)


def test_validate_exit_node_bad_url_scheme(tmp_cm):
    cfg = _valid_config()
    cfg["exit_node"]["enabled"] = True
    cfg["exit_node"]["url"] = "http://bad-scheme.example.com"
    cfg["exit_node"]["psk"] = "somepsk"
    errors = tmp_cm.validate(cfg)
    assert any("exit_node.url" in e for e in errors)


def test_validate_exit_node_no_psk(tmp_cm):
    cfg = _valid_config()
    cfg["exit_node"]["enabled"] = True
    cfg["exit_node"]["url"] = "https://worker.workers.dev"
    cfg["exit_node"]["psk"] = ""
    errors = tmp_cm.validate(cfg)
    assert any("exit_node.psk" in e for e in errors)


# ── save / load ───────────────────────────────────────────────────────────────

def test_save_creates_file(tmp_cm):
    cfg = _valid_config()
    tmp_cm.save(cfg)
    assert tmp_cm.config_path.exists()


def test_save_writes_valid_json(tmp_cm):
    cfg = _valid_config()
    tmp_cm.save(cfg)
    with open(tmp_cm.config_path) as fh:
        loaded = json.load(fh)
    assert loaded["auth_key"] == cfg["auth_key"]


def test_load_merges_defaults(tmp_cm):
    partial = {"auth_key": "secret123", "script_id": "AKfycbyTest123"}
    tmp_cm.config_path.write_text(json.dumps(partial))
    loaded = tmp_cm.load()
    assert loaded["auth_key"] == "secret123"
    # Should have defaults for missing keys
    assert "http_port" in loaded
    assert "exit_node" in loaded


def test_load_nonexistent_returns_defaults(tmp_cm):
    loaded = tmp_cm.load()
    defaults = tmp_cm.get_defaults()
    assert loaded["google_ip"] == defaults["google_ip"]


def test_save_raises_on_invalid_config(tmp_cm):
    cfg = _valid_config()
    cfg["auth_key"] = ""
    with pytest.raises(ValueError):
        tmp_cm.save(cfg)


# ── to_engine_format ──────────────────────────────────────────────────────────

def test_to_engine_format_single_id(tmp_cm):
    cfg = _valid_config()
    cfg["script_id"] = "AKfycbySingle"
    cfg["script_ids"] = []
    out = tmp_cm.to_engine_format(cfg)
    assert out.get("script_id") == "AKfycbySingle"
    assert "script_ids" not in out


def test_to_engine_format_multiple_ids(tmp_cm):
    cfg = _valid_config()
    cfg["script_ids"] = ["AKfycbyFirst", "AKfycbySecond"]
    cfg.pop("script_id", None)
    out = tmp_cm.to_engine_format(cfg)
    assert "script_ids" in out
    assert len(out["script_ids"]) == 2
    assert "script_id" not in out


def test_to_engine_format_strips_placeholders(tmp_cm):
    cfg = _valid_config()
    cfg["script_ids"] = [
        "AKfycbyReal",
        "YOUR_APPS_SCRIPT_DEPLOYMENT_ID",
    ]
    out = tmp_cm.to_engine_format(cfg)
    ids = out.get("script_ids") or [out.get("script_id")]
    assert all(sid != "YOUR_APPS_SCRIPT_DEPLOYMENT_ID" for sid in ids)


def test_to_engine_format_sets_mode(tmp_cm):
    out = tmp_cm.to_engine_format(_valid_config())
    assert out.get("mode") == "apps_script"
    assert out.get("socks5_enabled") is True


# ── export_to / import_from ───────────────────────────────────────────────────

def test_export_import_roundtrip(tmp_cm, tmp_path):
    cfg = _valid_config()
    tmp_cm.save(cfg)

    export_path = tmp_path / "exported.json"
    tmp_cm.export_to(export_path, cfg, strip_sensitive=False)
    assert export_path.exists()

    imported = tmp_cm.import_from(export_path)
    assert imported["auth_key"] == cfg["auth_key"]


def test_export_strips_sensitive(tmp_cm, tmp_path):
    cfg = _valid_config()
    cfg["exit_node"]["psk"] = "super_secret"
    export_path = tmp_path / "stripped.json"
    tmp_cm.export_to(export_path, cfg, strip_sensitive=True)

    with open(export_path) as fh:
        data = json.load(fh)
    assert data["auth_key"] != cfg["auth_key"]
    assert data.get("exit_node", {}).get("psk", "") == ""
