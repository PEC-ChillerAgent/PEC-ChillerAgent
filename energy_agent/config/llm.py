"""Server-side provider configuration; public views never include the API key."""

import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from energy_agent.contracts.chat import LLMConfigUpdate, LLMSettings
from energy_agent.storage.repository import Repository

ENV_FIELDS = {"ENERGY_AGENT_LLM_BASE_URL": "base_url", "ENERGY_AGENT_LLM_MODEL": "model",
              "ENERGY_AGENT_LLM_API_KEY": "api_key"}


class LLMConfigStore:
    def __init__(self, data_dir: Path):
        self.repository = Repository(data_dir)
        with self.repository._connection() as db:
            db.execute("CREATE TABLE IF NOT EXISTS local_settings (name TEXT PRIMARY KEY, payload TEXT NOT NULL)")

    def local(self) -> LLMSettings:
        with self.repository._connection() as db:
            row = db.execute("SELECT payload FROM local_settings WHERE name = 'llm'").fetchone()
        if row is None:
            return LLMSettings()
        try:
            return LLMSettings.model_validate_json(row[0])
        except ValueError:
            raise ValueError("本地模型配置无法读取，请重新保存配置") from None

    def load(self) -> LLMSettings:
        data = self.local().model_dump()
        previous_base = data["base_url"]
        for name, field in ENV_FIELDS.items():
            if os.environ.get(name):
                data[field] = os.environ[name]
        if data["base_url"] != previous_base and not os.environ.get("ENERGY_AGENT_LLM_API_KEY"):
            data["api_key"] = None
        key = data.get("api_key")
        has_key = bool(key and (key.get_secret_value() if hasattr(key, "get_secret_value") else key).strip())
        if not has_key and urlsplit(data["base_url"]).hostname == "api.openai.com" and os.environ.get("OPENAI_API_KEY"):
            data["api_key"] = os.environ["OPENAI_API_KEY"]
        try:
            return LLMSettings.model_validate(data)
        except ValueError:
            raise ValueError("模型环境配置无效，请检查服务地址与参数") from None

    def public(self) -> dict:
        config = self.load()
        result = config.model_dump(mode="json", exclude={"api_key"})
        local = self.local()
        generic_fallback = (os.environ.get("OPENAI_API_KEY") and not os.environ.get("ENERGY_AGENT_LLM_API_KEY")
                            and urlsplit(config.base_url).hostname == "api.openai.com"
                            and (config.base_url != local.base_url or not local.api_key or not local.api_key.get_secret_value().strip()))
        return {**result, "configured": config.configured,
                "has_api_key": bool(config.api_key and config.api_key.get_secret_value().strip()),
                "environment_overrides": [name for name in ENV_FIELDS if os.environ.get(name)] + (["OPENAI_API_KEY"] if generic_fallback else [])}

    def save(self, update: LLMConfigUpdate) -> dict:
        try:
            previous = self.local()
        except ValueError:
            previous = LLMSettings()
        supplied = update.api_key.get_secret_value().strip() if update.api_key else ""
        if supplied:
            key = supplied
        elif update.clear_api_key or update.base_url != previous.base_url:
            key = None
        else:
            key = previous.api_key.get_secret_value() if previous.api_key else None
        data = update.model_dump(mode="json", exclude={"api_key", "clear_api_key"})
        data["api_key"] = key
        with self.repository._connection() as db:
            db.execute("INSERT INTO local_settings(name, payload) VALUES ('llm', ?) ON CONFLICT(name) DO UPDATE SET payload=excluded.payload",
                       (json.dumps(data, ensure_ascii=False),))
        return self.public()
