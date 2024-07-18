import asyncio
import logging
from config import Config
from discord.ext import commands
import discord
from bot import create_bot
from database.connection import create_db_pool, setup_database
from services.query_service import QueryService
from services.repository_service import RepositoryService
from services.config_service import ConfigService
from utils.api_client import GreptileAPIClient
from utils.rate_limiter import RateLimiter
from utils.error_handler import setup_logging, BotError, ConfigError, DatabaseError

logger = logging.getLogger(__name__)

async def main():
    config = Config()
    
    try:
        # Set up logging
        log_file = config.get('logging.file', 'bot.log')
        log_level = config.get('logging.level', 'INFO')
        setup_logging(log_file=log_file, log_level=getattr(logging, log_level))

        # Set up database
        db_url = config.get('database.url')
        db_pool = await create_db_pool(db_url)
        migrations_path = config.get('database.migrations_path', './migrations')
        await setup_database(db_pool, migrations_path)
        
        # Set up API client with rate limiting
        rate_limit = config.get('rate_limiting.default_rate', 5)
        rate_limit_per = config.get('rate_limiting.default_per', 1)
        rate_limiter = RateLimiter(rate=rate_limit, per=rate_limit_per)
        
        api_key = config.get('greptile.api_key')
        github_token = config.get('greptile.github_token')
        api_base_url = config.get('greptile.api_base_url', 'https://api.greptile.com/v2')
        
        api_client = GreptileAPIClient(
            api_key=api_key,
            github_token=github_token,
            base_url=api_base_url,
        )
        
        # Set up services
        config_service = ConfigService(db_pool)
        repo_service = RepositoryService(db_pool, api_client, config_service)
        query_service = QueryService(db_pool, api_client, config_service)
        
        # Create bot
        bot = create_bot(
            config=config,
            db_pool=db_pool,
            api_client=api_client,
            config_service=config_service,
            repo_service=repo_service,
            query_service=query_service
        )
        
        # Start bot
        bot_token = config.get('discord.bot_token')
        if not bot_token:
            raise ConfigError("Bot token not found in configuration")

        logger.info("Starting Greptile Bot...")
        await bot.start(bot_token)

    except ConfigError as e:
        logger.error(f"Configuration error: {str(e)}")
    except DatabaseError as e:
        logger.error(f"Database error: {str(e)}")
    except BotError as e:
        logger.error(f"Bot error: {str(e)}")
    except Exception as e:
        logger.error(f"An unexpected error occurred: {str(e)}", exc_info=True)
    finally:
        if 'bot' in locals() and not bot.is_closed():
            await bot.close()
        if 'db_pool' in locals():
            await db_pool.close()
        logger.info("Bot has been shut down.")

if __name__ == "__main__":
    asyncio.run(main())