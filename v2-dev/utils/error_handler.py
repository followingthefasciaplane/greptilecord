import logging
import traceback
from discord.ext import commands
import discord

logger = logging.getLogger(__name__)

class BotError(Exception):
    """Base exception class for bot errors"""

class ConfigError(BotError):
    """Raised when there's an issue with configuration"""

class DatabaseError(BotError):
    """Raised when there's an issue with database operations"""

class APIError(BotError):
    """Raised when there's an issue with API calls"""

class PermissionError(BotError):
    """Raised when there's an issue with user permissions"""

# TO DO:
class RateLimitError(BotError):
    """Raised when rates are exceeded"""

async def handle_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(embed=discord.Embed(title="Error", description="Command not found. Use `~greptilehelp` to see available commands.", color=discord.Color.red()))
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=discord.Embed(title="Error", description=f"Missing required argument: {error.param.name}", color=discord.Color.red()))
    elif isinstance(error, commands.BadArgument):
        await ctx.send(embed=discord.Embed(title="Error", description="Invalid argument provided. Please check the command usage.", color=discord.Color.red()))
    elif isinstance(error, commands.CheckFailure):
        await ctx.send(embed=discord.Embed(title="Error", description="You don't have permission to use this command.", color=discord.Color.red()))
    elif isinstance(error, ConfigError):
        logger.error(f"Configuration error: {error}", exc_info=True)
        await ctx.send(embed=discord.Embed(title="Configuration Error", description=str(error), color=discord.Color.red()))
    elif isinstance(error, DatabaseError):
        logger.error(f"Database error: {error}", exc_info=True)
        await ctx.send(embed=discord.Embed(title="Database Error", description="An error occurred while accessing the database. Please try again later.", color=discord.Color.red()))
    elif isinstance(error, APIError):
        logger.error(f"API error: {error}", exc_info=True)
        await ctx.send(embed=discord.Embed(title="API Error", description="An error occurred while communicating with the Greptile API. Please try again later.", color=discord.Color.red()))
    elif isinstance(error, PermissionError):
        await ctx.send(embed=discord.Embed(title="Permission Error", description=str(error), color=discord.Color.red()))
    else:
        logger.error(f"Unhandled error in command {ctx.command}: {error}", exc_info=True)
        await ctx.send(embed=discord.Embed(title="Unexpected Error", description="An unexpected error occurred. Please try again later.", color=discord.Color.red()))

    # If there's an error channel set, send the full error message there
    if hasattr(ctx.bot, 'error_channel') and ctx.bot.error_channel:
        error_message = f"Error in command {ctx.command}:\n```\n{type(error).__name__}: {str(error)}\n\n{traceback.format_exc()}\n```"
        await ctx.bot.error_channel.send(error_message[:2000])  # Discord has a 2000 character limit

def setup_logging(log_file='bot.log', log_level=logging.INFO):
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )