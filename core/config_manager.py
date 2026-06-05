"""
ConfigManager — read, write, validate, and transform config.json.

All GUI code goes through this module to interact with the configuration
file. It handles merging with defaults, validation, and the
``script_id`` vs ``script_ids`` normalisation that the engine requires.
"""

from __future__ import annotations

import copy
import ipaddress
import json
import os
from pathlib import Path
from typing import Any

# Resolve paths relative to the GUI root (two levels up from core/).
_GUI_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH = _GUI_ROOT / "config.json"
EXAMPLE_CONFIG_PATH = _GUI_ROOT / "engine" / "config.example.json"

_PLACEHOLDER_AUTH_KEYS = {
    "",
    "CHANGE_ME_TO_A_STRONG_SECRET",
    "your-secret-password-here",
}
_PLACEHOLDER_SCRIPT_IDS = {
    "",
    "YOUR_APPS_SCRIPT_DEPLOYMENT_ID",
}


class ConfigManager:
    """
    Centralised configuration manager for the GUI.

    Attributes
    ----------
    config_path : Path
        Absolute path to the ``config.json`` file that is read and written.
    """

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path: Path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> dict[str, Any]:
        """
        Load ``config.json``, merging missing keys from defaults.

        Returns
        -------
        dict
            Fully populated configuration dictionary.
        """
        defaults = self.get_defaults()
        if not self.config_path.exists():
            return defaults

        try:
            with open(self.config_path, encoding="utf-8") as fh:
                user_cfg = json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            raise RuntimeError(f"Failed to read config.json: {exc}") from exc

        merged = copy.deepcopy(defaults)
        _deep_merge(merged, user_cfg)
        return merged

    def save(self, cfg: dict[str, Any]) -> None:
        """
        Validate and write *cfg* to ``config.json``.

        Raises
        ------
        ValueError
            If validation fails.
        OSError
            If the file cannot be written.
        """
        errors = self.validate(cfg)
        if errors:
            raise ValueError("Config validation failed:\n" + "\n".join(f"  • {e}" for e in errors))

        engine_cfg = self.to_engine_format(cfg)
        with open(self.config_path, "w", encoding="utf-8") as fh:
            json.dump(engine_cfg, fh, indent="\t", ensure_ascii=False)

    def get_defaults(self) -> dict[str, Any]:
        """
        Return a deep copy of the example / default configuration.

        Returns
        -------
        dict
            Default configuration values.
        """
        if EXAMPLE_CONFIG_PATH.exists():
            try:
                with open(EXAMPLE_CONFIG_PATH, encoding="utf-8") as fh:
                    return json.load(fh)
            except (json.JSONDecodeError, OSError):
                pass
        return _builtin_defaults()

    def validate(self, cfg: dict[str, Any]) -> list[str]:
        """
        Validate the configuration dict.

        Returns
        -------
        list[str]
            A list of human-readable error messages.  Empty means valid.
        """
        errors: list[str] = []

        # auth_key
        auth_key = cfg.get("auth_key", "")
        if auth_key in _PLACEHOLDER_AUTH_KEYS:
            errors.append("auth_key must be set to a strong secret (not a placeholder).")

        # script_id / script_ids
        script_ids = cfg.get("script_ids") or cfg.get("script_id")
        if not script_ids:
            errors.append("At least one Apps Script deployment ID must be provided.")
        elif isinstance(script_ids, str) and script_ids in _PLACEHOLDER_SCRIPT_IDS:
            errors.append("script_id must be a real Apps Script deployment ID.")
        elif isinstance(script_ids, list):
            valid = [s for s in script_ids if s and s not in _PLACEHOLDER_SCRIPT_IDS]
            if not valid:
                errors.append("script_ids list must contain at least one real deployment ID.")

        # ports
        http_port = cfg.get("http_port", 8085)
        socks_port = cfg.get("socks5_port", 1080)
        for name, val in [("http_port", http_port), ("socks5_port", socks_port)]:
            if not isinstance(val, int) or not (1 <= val <= 65535):
                errors.append(f"{name} must be an integer between 1 and 65535.")
        if isinstance(http_port, int) and isinstance(socks_port, int) and http_port == socks_port:
            errors.append("http_port and socks5_port must be different.")

        # google_ip
        google_ip = cfg.get("google_ip", "")
        try:
            ipaddress.IPv4Address(google_ip)
        except ValueError:
            errors.append(f"google_ip '{google_ip}' is not a valid IPv4 address.")

        # exit_node
        exit_node = cfg.get("exit_node", {})
        if exit_node.get("enabled"):
            url = exit_node.get("url", "")
            if not url.startswith("https://"):
                errors.append("exit_node.url must start with 'https://'.")
            psk = exit_node.get("psk", "")
            if not psk:
                errors.append("exit_node.psk must not be empty when exit node is enabled.")

        return errors

    def to_engine_format(self, cfg: dict[str, Any]) -> dict[str, Any]:
        """
        Convert the GUI config dict to the format expected by the engine.

        The engine accepts either ``script_id`` (string) or ``script_ids``
        (list).  When there is exactly one ID we use the singular form to
        keep the config file human-readable; when there are multiple we
        use the list form.

        Returns
        -------
        dict
            Engine-compatible configuration dictionary.
        """
        out = copy.deepcopy(cfg)

        # Normalise script ID representation
        script_ids: list[str] = out.pop("script_ids", [])
        if not script_ids:
            single = out.get("script_id", "")
            script_ids = [single] if single else []

        # Remove placeholders
        script_ids = [s for s in script_ids if s and s not in _PLACEHOLDER_SCRIPT_IDS]

        if len(script_ids) == 1:
            out["script_id"] = script_ids[0]
            out.pop("script_ids", None)
        elif len(script_ids) > 1:
            out["script_ids"] = script_ids
            out.pop("script_id", None)

        # Engine always expects socks5_enabled = True
        out["socks5_enabled"] = True
        out["mode"] = "apps_script"

        return out

    def config_exists(self) -> bool:
        """Return True if config.json already exists on disk."""
        return self.config_path.exists()

    def import_from(self, path: str | Path) -> dict[str, Any]:
        """
        Load a config from an arbitrary path without writing it.

        Returns
        -------
        dict
            Loaded and default-merged configuration.
        """
        original_path = self.config_path
        self.config_path = Path(path)
        try:
            return self.load()
        finally:
            self.config_path = original_path

    def export_to(self, path: str | Path, cfg: dict[str, Any], strip_sensitive: bool = False) -> None:
        """
        Write configuration to an arbitrary path.

        Parameters
        ----------
        path :
            Destination file path.
        cfg :
            Configuration dictionary to export.
        strip_sensitive :
            When True, replace ``auth_key`` and ``exit_node.psk`` with
            placeholder strings before writing.
        """
        export_cfg = copy.deepcopy(cfg)
        if strip_sensitive:
            export_cfg["auth_key"] = "CHANGE_ME_TO_A_STRONG_SECRET"
            if "exit_node" in export_cfg:
                export_cfg["exit_node"]["psk"] = ""
        engine_fmt = self.to_engine_format(export_cfg)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(engine_fmt, fh, indent="\t", ensure_ascii=False)


# ------------------------------------------------------------------
# Private helpers
# ------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> None:
    """Recursively merge *override* into *base* in place."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _builtin_defaults() -> dict[str, Any]:
    """Return hard-coded defaults matching config.example.json."""
    return {
        "google_ip": "216.239.38.120",
        "front_domain": "www.google.com",
        "front_domains": [
            "www.google.com",
            "mail.google.com",
            "accounts.google.com",
        ],
        "script_id": "YOUR_APPS_SCRIPT_DEPLOYMENT_ID",
        "script_ids": [],
        "auth_key": "CHANGE_ME_TO_A_STRONG_SECRET",
        "listen_host": "127.0.0.1",
        "http_port": 8085,
        "socks5_port": 1080,
        "verify_ssl": True,
        "lan_sharing": False,
        "relay_ip_literals": True,
        "relay_timeout": 55,
        "tls_connect_timeout": 20,
        "tcp_connect_timeout": 15,
        "parallel_relay": 1,
        "h2_connections": 1,
        "ping_interval": 0.1,
        "enable_batch": True,
        "batch_window_micro": 0.020,
        "batch_window_macro": 0.100,
        "enable_sub_batch": False,
        "block_hosts": [],
        "direct_hosts": [],
        "bypass_hosts": [],
        "youtube_via_relay": False,
        "hosts": {},
        "exit_node": {
            "enabled": False,
            "provider": "cloudflare",
            "url": "",
            "psk": "",
            "mode": "selective",
            "hosts": [
                "claude.ai",
                "anthropic.com",
                "chatgpt.com",
                "openai.com",
                "chat.openai.com",
                "api.openai.com",
                "challenges.cloudflare.com",
                "turnstile.cloudflare.com",
            ],
        },
        "log_level": "INFO",
        "adblock_lists": [
            "https://raw.githubusercontent.com/MasterKia/PersianBlocker/main/PersianBlockerAds-Hosts.txt",
            "https://raw.githubusercontent.com/MasterKia/PersianBlocker/main/PersianBlockerTrackers-Hosts.txt",
            "https://raw.githubusercontent.com/MasterKia/PersianBlocker/main/PersianBlockerAnnoyances-Domains.txt",
            "https://raw.githubusercontent.com/MasterKia/PersianBlocker/main/PersianBlockerHosts.txt",
        ],
        "chunked_download_extensions": [".mp4", ".mkv", ".iso", ".zip", ".rar"],
        "chunked_download_min_size": 10,
        "chunked_download_chunk_size": 4,
        "chunked_download_max_parallel": 4,
        "direct_google_exclude": [],
    }
