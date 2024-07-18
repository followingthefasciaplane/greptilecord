import os
from dotenv import load_dotenv
import yaml
from typing import Any, Dict, Optional
import logging
from functools import lru_cache
from collections import ChainMap
from utils.error_handler import ConfigError

# Load environment variables from .env file
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class Config:
    def __init__(self, yaml_file='config.yaml'):
        self._config = ChainMap()
        self._yaml_file = yaml_file
        self._cache = {}
        self.load_config()

    def load_config(self):
        logger.info("Loading configuration...")
        try:
            env_config = self._load_from_env()
            yaml_config = self._load_from_yaml()
            self._config = ChainMap(env_config, yaml_config)
            logger.debug(f"Final config: {self._sanitize_config(dict(self._config))}")
            self._validate_config()
        except Exception as e:
            logger.error(f"Error loading configuration: {str(e)}")
            raise ConfigError(f"Failed to load configuration: {str(e)}")

    def _load_from_env(self) -> Dict[str, Any]:
        logger.debug("Loading from environment variables...")
        env_config = {}
        for key, value in os.environ.items():
            if key.startswith(('DISCORD_', 'GREPTILE_', 'BOT_', 'DATABASE_')):
                parts = key.lower().split('_')
                if len(parts) > 1:
                    main_key = parts[0]
                    sub_key = '_'.join(parts[1:])
                    if main_key not in env_config:
                        env_config[main_key] = {}
                    env_config[main_key][sub_key] = value
                else:
                    env_config[key.lower()] = value
        return env_config

    def _load_from_yaml(self) -> Dict[str, Any]:
        logger.debug(f"Loading from YAML file: {self._yaml_file}")
        try:
            with open(self._yaml_file, 'r') as file:
                yaml_config = yaml.safe_load(file) or {}
            logger.debug(f"Loaded from YAML: {self._sanitize_config(yaml_config)}")
            return yaml_config
        except FileNotFoundError:
            logger.warning(f"{self._yaml_file} not found. Using only environment variables.")
            return {}
        except yaml.YAMLError as e:
            logger.error(f"Error parsing {self._yaml_file}: {e}")
            raise ConfigError(f"Failed to parse YAML config: {str(e)}")

    def _validate_config(self):
        logger.debug("Validating configuration...")
        required_keys = ['discord.bot_token', 'greptile.api_key', 'greptile.github_token']
        missing_keys = []
        for key in required_keys:
            value = self.get(key)
            logger.debug(f"Validating {key}: {'Present' if value else 'Missing'}")
            if not value:
                missing_keys.append(key)
        
        if missing_keys:
            raise ConfigError(f"Required configuration(s) missing: {', '.join(missing_keys)}")

    @lru_cache(maxsize=128)
    def get(self, key: str, default: Any = None) -> Any:
        keys = key.split('.')
        value = self._config
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default

    def set(self, key: str, value: Any):
        keys = key.split('.')
        config = self._config
        for k in keys[:-1]:
            config = config.setdefault(k, {})
        config[keys[-1]] = value
        self._cache.clear()
        self._validate_config()

    def reload(self):
        self.load_config()
        self._cache.clear()
        logger.info("Configuration reloaded.")

    def as_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self._config.items() if not self._is_sensitive(k)}

    def _is_sensitive(self, key: str) -> bool:
        sensitive_keys = ['discord.bot_token', 'greptile.api_key', 'greptile.github_token']
        return any(key.startswith(sensitive_key) for sensitive_key in sensitive_keys)

    def print_config(self):
        logger.info("Current Configuration:")
        for key, value in self.as_dict().items():
            logger.info(f"{key}: {self._sanitize_value(key, value)}")

    def _sanitize_value(self, key: str, value: Any) -> str:
        if self._is_sensitive(key):
            return "***REDACTED***"
        return str(value)

    def _sanitize_config(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return {k: self._sanitize_value(k, v) for k, v in config.items()}

# Create a global instance of Config
config = Config()