"""
config.py — Központi konfiguráció betöltő

Használat:
    from config import cfg

    api_url = cfg.api.url
    nas_folders = cfg.nas.folders
    gmail_recipient = cfg.gmail.recipient
"""
from __future__ import annotations
import os
from pathlib import Path
from typing import Any
from dotenv import load_dotenv

load_dotenv()

# Config fájl helye
CONFIG_FILE = os.getenv("CONFIG_FILE", "config.yaml")


class ConfigSection:
    """Egyszerű config szekció — dict értékeket attribútumként éri el."""
    def __init__(self, data: dict):
        for key, value in data.items():
            if isinstance(value, dict):
                setattr(self, key, ConfigSection(value))
            elif isinstance(value, list) and value and isinstance(value[0], dict):
                setattr(self, key, [ConfigSection(i) if isinstance(i, dict) else i for i in value])
            else:
                setattr(self, key, value)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class Config:
    """Fő konfiguráció osztály — YAML + .env kombinálva."""

    def __init__(self, config_file: str = CONFIG_FILE):
        try:
            import yaml
            with open(config_file, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except FileNotFoundError:
            print(f"[Config] FIGYELEM: {config_file} nem található, defaults használva")
            data = {}
        except Exception as e:
            print(f"[Config] Hiba a config betöltésnél: {e}")
            data = {}

        # Szekciók betöltése
        self.api            = ConfigSection(data.get("api", {}))
        self.qdrant         = ConfigSection(data.get("qdrant", {}))
        self.ai             = ConfigSection(data.get("ai", {}))
        self.postgres       = ConfigSection(data.get("postgres", {}))
        self.gmail          = ConfigSection(data.get("gmail", {}))
        self.nas            = ConfigSection(data.get("nas", {}))
        self.system_params  = ConfigSection(data.get("system_params", {}))
        self.discord        = ConfigSection(data.get("discord", {}))
        self.n8n            = ConfigSection(data.get("n8n", {}))
        self.rbac           = ConfigSection(data.get("rbac", {}))
        self.logging        = ConfigSection(data.get("logging", {}))

        # .env értékek felülírják a YAML-t ahol szükséges
        self._override_from_env()

    def _override_from_env(self):
        """Kritikus értékek .env-ből felülírják a YAML-t."""
        # Qdrant
        if os.getenv("QDRANT_HOST"):
            self.qdrant.host = os.getenv("QDRANT_HOST")
        if os.getenv("QDRANT_PORT"):
            self.qdrant.port = int(os.getenv("QDRANT_PORT"))
        if os.getenv("QDRANT_COLLECTION"):
            self.qdrant.collection = os.getenv("QDRANT_COLLECTION")

        # AI modellek
        if os.getenv("EMBEDDING_MODEL"):
            self.ai.embedding_model = os.getenv("EMBEDDING_MODEL")
        if os.getenv("EMBEDDING_DIM"):
            self.ai.embedding_dim = int(os.getenv("EMBEDDING_DIM"))
        if os.getenv("CLAUDE_MODEL"):
            self.ai.claude_model = os.getenv("CLAUDE_MODEL")

        # Gmail
        if os.getenv("GMAIL_CREDENTIALS_FILE"):
            self.gmail.credentials_file = os.getenv("GMAIL_CREDENTIALS_FILE")
        if os.getenv("GMAIL_TOKEN_FILE"):
            self.gmail.token_file = os.getenv("GMAIL_TOKEN_FILE")
        if os.getenv("GMAIL_RECIPIENT"):
            self.gmail.recipient = os.getenv("GMAIL_RECIPIENT")

        # Discord
        if os.getenv("DISCORD_ALLOWED_USER_ID"):
            self.discord.allowed_user_id = os.getenv("DISCORD_ALLOWED_USER_ID")

        # API
        if os.getenv("API_URL"):
            self.api.url = os.getenv("API_URL")

    @property
    def nas_folders(self) -> list[dict]:
        """NAS mappák listája dict formátumban."""
        folders = getattr(self.nas, "folders", [])
        if not folders:
            return []
        return [
            {"path": f.path, "tag": f.tag}
            if isinstance(f, ConfigSection)
            else f
            for f in folders
        ]

    @property
    def gmail_domain_tags(self) -> dict:
        """Gmail domain → tag mapping dict."""
        domain_tags = getattr(self.gmail, "domain_tags", None)
        if isinstance(domain_tags, ConfigSection):
            return vars(domain_tags)
        return domain_tags or {}

    @property
    def sheet_tags(self) -> dict:
        """Google Sheets sheet → tag mapping dict."""
        sheet_tags = getattr(self.system_params, "sheet_tags", None)
        if isinstance(sheet_tags, ConfigSection):
            return vars(sheet_tags)
        return sheet_tags or {}


# Globális singleton
cfg = Config()


if __name__ == "__main__":
    print("=== Config betöltve ===")
    print(f"API URL:        {cfg.api.url}")
    print(f"Qdrant:         {cfg.qdrant.host}:{cfg.qdrant.port}/{cfg.qdrant.collection}")
    print(f"Claude model:   {cfg.ai.claude_model}")
    print(f"Gmail recipient:{cfg.gmail.recipient}")
    print(f"NAS mappák:     {len(cfg.nas_folders)} db")
    print(f"Domain tagek:   {cfg.gmail_domain_tags}")
    print(f"Sheet tagek:    {cfg.sheet_tags}")
