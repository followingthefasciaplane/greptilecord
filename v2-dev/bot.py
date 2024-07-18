import discord
from discord.ext import commands, tasks
import logging
import traceback
import sys
import os
from typing import Optional
from config import Config
from services.query_service import QueryService
from services.repository_service import RepositoryService
from services.config_service import ConfigService
from utils.api_client import GreptileAPIClient
from utils.rate_limiter import RateLimiter
from database.connection import create_db_pool, setup_database
from utils.error_handler import BotError, ConfigError, DatabaseError, APIError

logger = logging.getLogger(__name__)

class GreptileBot(commands.Bot):
    def __init__(self, config: Config, **kwargs):
        intents = discord.Intents.all()
        super().__init__(
            command_prefix=commands.when_mentioned_or(config.get('bot.prefix', '~')),
            intents=intents
        )
        
        self.config = config
        self.db_pool = kwargs.get('db_pool')
        self.api_client = kwargs.get('api_client')
        self.repo_service = kwargs.get('repo_service')
        self.query_service = kwargs.get('query_service')
        self.config_service = kwargs.get('config_service')
        self.version = config.get('bot.version', "1.0.0")
        self.error_channel: Optional[discord.TextChannel] = None

    async def setup_hook(self):
        # Load cogs
        for filename in os.listdir('./cogs'):
            if filename.endswith('.py'):
                try:
                    await self.load_extension(f'cogs.{filename[:-3]}')
                    logger.info(f'Loaded extension: {filename[:-3]}')
                except Exception as e:
                    logger.error(f'Failed to load extension {filename[:-3]}: {str(e)}')

        # Start periodic tasks
        self.check_repository_status.start()

    @tasks.loop(minutes=30)
    async def check_repository_status(self):
        logger.info("Checking repository status...")
        if not hasattr(self, 'repo_service') or self.repo_service is None:
            logger.warning("Repository service not initialized. Skipping status check.")
            return
        try:
            status_updates = await self.repo_service.check_and_update_repo_status()
            for update in status_updates:
                if update['status'] == 'failed':
                    await self.report_error(f"Repository indexing failed: {update['owner']}/{update['name']}")
                elif update['status'] == 'processing' and update.get('processing_time', 0) > 7200:  # 2 hours
                    await self.report_error(f"Repository indexing taking too long: {update['owner']}/{update['name']}")
        except Exception as e:
            await self.report_error(f"Error checking repository status: {str(e)}")

    async def on_ready(self):
        logger.info(f'{self.user} has connected to Discord!')
        logger.info(f'Serving {len(self.guilds)} guilds')
        
        # Set up error reporting channel
        error_channel_id = await self.config_service.get_config('ERROR_CHANNEL_ID')
        if error_channel_id:
            self.error_channel = self.get_channel(int(error_channel_id))
            if not self.error_channel:
                logger.warning(f"Could not find error channel with ID {error_channel_id}")

    async def on_error(self, event_method, *args, **kwargs):
        exc_type, exc_value, exc_traceback = sys.exc_info()
        error_message = f"Unhandled exception in {event_method}:\n"
        error_message += ''.join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        
        logger.error(error_message)
        await self.report_error(error_message)

    async def report_error(self, error_message: str):
        if self.error_channel:
            await self.error_channel.send(f"```\n{error_message[:1900]}\n```")
        else:
            logger.error(f"Error channel not set. Error: {error_message}")

    async def close(self):
        try:
            self.check_repository_status.cancel()
            if self.db_pool:
                await self.db_pool.close()
            await super().close()
        except Exception as e:
            logger.error(f"Error during bot shutdown: {str(e)}")
        finally:
            logger.info("Bot has been shut down.")

    async def on_guild_join(self, guild):
        logger.info(f"Bot has joined a new guild: {guild.name} (ID: {guild.id})")
        try:
            owner_id = str(guild.owner_id)
            auto_add_owner = await self.config_service.get_config('WHITELIST.AUTO_ADD_SERVER_OWNER', True)
            if auto_add_owner:
                await self.config_service.add_to_whitelist(owner_id, 'owner')
                logger.info(f"Automatically added server owner (ID: {owner_id}) to whitelist")
        except Exception as e:
            logger.error(f"Error processing guild join for {guild.name} (ID: {guild.id}): {str(e)}")

    async def on_guild_remove(self, guild):
        logger.info(f"Bot has been removed from a guild: {guild.name} (ID: {guild.id})")
        # Might want to add cleanup logic here
        
    async def on_message(self, message):
        if message.author.bot:
            return  # Ignore messages from bots

        # Process commands
        await self.process_commands(message)

        # Add some message stuff here at some point

def create_bot(config: Config, **kwargs) -> GreptileBot:
    return GreptileBot(config, **kwargs)

if __name__ == "__main__":
    # This block is useful for testing the bot directly
    import asyncio
    from config import config

    async def run_bot():
        try:
            bot = create_bot(config)
            # Set up services and other initializations here
            await bot.start(config.get('discord.bot_token'))
        except Exception as e:
            logger.error(f"Error starting the bot: {str(e)}")
        finally:
            if 'bot' in locals():
                await bot.close()

    asyncio.run(run_bot())