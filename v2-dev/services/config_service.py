import logging
from typing import List, Dict, Any, Optional, Tuple
from database.connection import execute_query, fetch_one, fetch_all
from utils.error_handler import BotError, ConfigError, DatabaseError
import json

logger = logging.getLogger(__name__)

class ConfigService:
    def __init__(self, db_pool):
        self.db_pool = db_pool

    async def get_config(self, key: str, default: Any = None) -> Any:
        try:
            query = "SELECT value FROM config WHERE key = ?"
            result = await fetch_one(self.db_pool, query, (key,))
            if result:
                return self._parse_value(result[0])
            return default
        except Exception as e:
            logger.error(f"Error getting config for key '{key}': {str(e)}")
            raise DatabaseError(f"Failed to get config for key '{key}': {str(e)}")

    async def get_all_config(self) -> Dict[str, Any]:
        try:
            query = "SELECT key, value FROM config"
            rows = await fetch_all(self.db_pool, query)
            return {row[0]: self._parse_value(row[1]) for row in rows}
        except Exception as e:
            logger.error(f"Error fetching all config: {str(e)}")
            raise DatabaseError(f"Failed to fetch all config: {str(e)}")

    async def set_config(self, key: str, value: Any) -> bool:
        try:
            query = """
            INSERT INTO config (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """
            await execute_query(self.db_pool, query, (key, self._serialize_value(value)))
            logger.info(f"Set config value for key '{key}' to '{value}'")
            return True
        except Exception as e:
            logger.error(f"Error setting config value for key '{key}': {str(e)}")
            raise DatabaseError(f"Failed to set config value for key '{key}': {str(e)}")

    async def delete_config(self, key: str) -> bool:
        try:
            query = "DELETE FROM config WHERE key = ?"
            await execute_query(self.db_pool, query, (key,))
            logger.info(f"Deleted config value for key '{key}'")
            return True
        except Exception as e:
            logger.error(f"Error deleting config value for key '{key}': {str(e)}")
            raise DatabaseError(f"Failed to delete config value for key '{key}': {str(e)}")

    async def add_to_whitelist(self, user_id: str, role: str) -> bool:
        try:
            query = """
            INSERT INTO whitelist (user_id, role) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET role = excluded.role
            """
            await execute_query(self.db_pool, query, (user_id, role))
            logger.info(f"Added user '{user_id}' to whitelist with role '{role}'")
            return True
        except Exception as e:
            logger.error(f"Error adding user '{user_id}' to whitelist: {str(e)}")
            raise DatabaseError(f"Failed to add user '{user_id}' to whitelist: {str(e)}")

    async def update_whitelist_role(self, user_id: str, role: str) -> bool:
        try:
            query = "UPDATE whitelist SET role = ? WHERE user_id = ?"
            await execute_query(self.db_pool, query, (role, user_id))
            logger.info(f"Updated role for user '{user_id}' to '{role}'")
            return True
        except Exception as e:
            logger.error(f"Error updating role for user '{user_id}': {str(e)}")
            raise DatabaseError(f"Failed to update role for user '{user_id}': {str(e)}")

    async def is_whitelisted(self, user_id: int) -> bool:
        try:
            query = "SELECT role FROM whitelist WHERE user_id = ?"
            result = await fetch_one(self.db_pool, query, (str(user_id),))
            return result is not None
        except Exception as e:
            logger.error(f"Error checking if user '{user_id}' is whitelisted: {str(e)}")
            raise DatabaseError(f"Failed to check if user '{user_id}' is whitelisted: {str(e)}")

    async def get_user_role(self, user_id: int) -> Optional[str]:
        try:
            query = "SELECT role FROM whitelist WHERE user_id = ?"
            result = await fetch_one(self.db_pool, query, (str(user_id),))
            return result[0] if result else None
        except Exception as e:
            logger.error(f"Error getting role for user '{user_id}': {str(e)}")
            raise DatabaseError(f"Failed to get role for user '{user_id}': {str(e)}")

    async def remove_from_whitelist(self, user_id: str) -> bool:
        try:
            query = "DELETE FROM whitelist WHERE user_id = ?"
            await execute_query(self.db_pool, query, (user_id,))
            logger.info(f"Removed user '{user_id}' from whitelist")
            return True
        except Exception as e:
            logger.error(f"Error removing user '{user_id}' from whitelist: {str(e)}")
            raise DatabaseError(f"Failed to remove user '{user_id}' from whitelist: {str(e)}")

    async def get_whitelist(self) -> List[Tuple[str, str]]:
        try:
            query = "SELECT user_id, role FROM whitelist"
            rows = await fetch_all(self.db_pool, query)
            return [(row[0], row[1]) for row in rows]
        except Exception as e:
            logger.error(f"Error fetching whitelist: {str(e)}")
            raise DatabaseError(f"Failed to fetch whitelist: {str(e)}")

    async def get_whitelisted_users_by_role(self, role: str) -> List[str]:
        try:
            query = "SELECT user_id FROM whitelist WHERE role = ?"
            rows = await fetch_all(self.db_pool, query, (role,))
            return [row[0] for row in rows]
        except Exception as e:
            logger.error(f"Error fetching whitelisted users with role '{role}': {str(e)}")
            raise DatabaseError(f"Failed to fetch whitelisted users with role '{role}': {str(e)}")

    async def reload_config(self):
        try:
            # Reload the configuration from the environment variables
            from config import config
            config.load_config()
            logger.info("Configuration reloaded from environment variables")

            # Update the database with the new configuration
            for key, value in config.as_dict().items():
                await self.set_config(key, value)
            logger.info("Database configuration updated")
        except Exception as e:
            logger.error(f"Error reloading configuration: {str(e)}")
            raise ConfigError(f"Failed to reload configuration: {str(e)}")

    def _serialize_value(self, value: Any) -> str:
        try:
            return json.dumps(value)
        except (TypeError, OverflowError) as e:
            logger.error(f"Error serializing value: {str(e)}")
            raise ConfigError(f"Failed to serialize value: {str(e)}")

    def _parse_value(self, value: str) -> Any:
        try:
            return json.loads(value)
        except json.JSONDecodeError as e:
            logger.error(f"Error parsing value: {str(e)}")
            return value

    async def set_default_config(self, default_config: Dict[str, Any]):
        try:
            for key, value in default_config.items():
                existing_value = await self.get_config(key)
                if existing_value is None:
                    await self.set_config(key, value)
            logger.info("Default configuration values set")
        except Exception as e:
            logger.error(f"Error setting default configuration: {str(e)}")
            raise ConfigError(f"Failed to set default configuration: {str(e)}")

    async def get_config_as_dict(self) -> Dict[str, Any]:
        try:
            all_config = await self.get_all_config()
            return {k: v for k, v in all_config.items() if not self._is_sensitive(k)}
        except Exception as e:
            logger.error(f"Error getting configuration as dictionary: {str(e)}")
            raise ConfigError(f"Failed to get configuration as dictionary: {str(e)}")

    def _is_sensitive(self, key: str) -> bool:
        sensitive_keys = ['discord.bot_token', 'greptile.api_key', 'greptile.github_token']
        return any(key.startswith(sensitive_key) for sensitive_key in sensitive_keys)

    async def validate_config(self, required_keys: List[str]):
        try:
            all_config = await self.get_all_config()
            missing_keys = [key for key in required_keys if key not in all_config]
            if missing_keys:
                raise ConfigError(f"Missing required configuration keys: {', '.join(missing_keys)}")
            logger.info("Configuration validated successfully")
        except Exception as e:
            logger.error(f"Error validating configuration: {str(e)}")
            raise ConfigError(f"Failed to validate configuration: {str(e)}")

    async def get_typed_config(self, key: str, default: Any = None, expected_type: type = None) -> Any:
        try:
            value = await self.get_config(key, default)
            if expected_type and not isinstance(value, expected_type):
                raise ConfigError(f"Configuration value for '{key}' is not of expected type {expected_type.__name__}")
            return value
        except Exception as e:
            logger.error(f"Error getting typed configuration for key '{key}': {str(e)}")
            raise ConfigError(f"Failed to get typed configuration for key '{key}': {str(e)}")

    async def increment_config(self, key: str, increment: int = 1) -> int:
        try:
            current_value = await self.get_config(key, 0)
            if not isinstance(current_value, int):
                raise ConfigError(f"Configuration value for '{key}' is not an integer")
            new_value = current_value + increment
            await self.set_config(key, new_value)
            return new_value
        except Exception as e:
            logger.error(f"Error incrementing configuration for key '{key}': {str(e)}")
            raise ConfigError(f"Failed to increment configuration for key '{key}': {str(e)}")

    async def toggle_config(self, key: str) -> bool:
        try:
            current_value = await self.get_config(key, False)
            if not isinstance(current_value, bool):
                raise ConfigError(f"Configuration value for '{key}' is not a boolean")
            new_value = not current_value
            await self.set_config(key, new_value)
            return new_value
        except Exception as e:
            logger.error(f"Error toggling configuration for key '{key}': {str(e)}")
            raise ConfigError(f"Failed to toggle configuration for key '{key}': {str(e)}")