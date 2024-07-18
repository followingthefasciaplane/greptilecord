import discord
from discord.ext import commands
import logging
from typing import List, Dict, Any
from utils.api_client import GreptileAPIError
from utils.helpers import create_error_embed, create_success_embed
from utils.error_handler import BotError, ConfigError, DatabaseError, APIError, PermissionError

logger = logging.getLogger(__name__)

class UserCommands(commands.Cog):
    def __init__(self, bot, repo_service, query_service, config_service):
        self.bot = bot
        self.repo_service = repo_service
        self.query_service = query_service
        self.config_service = config_service

    async def cog_check(self, ctx):
        return await self.config_service.is_whitelisted(ctx.author.id)

    @commands.command(name='greptilehelp')
    async def greptile_help(self, ctx):
        try:
            embed = discord.Embed(title="Greptile Discord Bot Commands", color=discord.Color.blue())

            # General Commands
            general_commands = """
            `~greptilehelp`: Displays this help message
            `~search <search_query>`: Searches for relevant code
            `~query <question>`: Asks a question about the codebase
            `~smartquery <question>`: Asks a complex question using 'genius' feature
            `~listrepos`: Lists all indexed repositories
            `~repostatus`: Views the current status of the indexed repository
            `~usage`: View your current usage statistics
            `~viewconfig`: View the current bot configuration
            """
            embed.add_field(name="General Commands", value=general_commands, inline=False)

            # Admin Commands
            admin_commands = """
            `~addrepo <remote> <owner> <name> <branch>`: Adds and indexes a new repository
            `~removerepos`: Removes all indexed repositories
            `~reindex`: Forces reindexing of the current repository
            `~listwhitelist`: Lists all whitelisted users
            `~addwhitelist <user_id>`: Adds a user to the whitelist
            `~removewhitelist <user_id>`: Removes a user from the whitelist
            `~setlogchannel <channel_id>`: Sets the channel for logging bot activities
            `~seterrorchannel <channel_id>`: Sets the channel for error reporting
            """
            embed.add_field(name="Admin Commands", value=admin_commands, inline=False)

            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in greptile_help command: {str(e)}", exc_info=True)
            await ctx.send(embed=create_error_embed("Error", "An unexpected error occurred while displaying help."))

    @commands.command(name='search')
    async def search(self, ctx, *, search_query: str):
        try:
            if not await self.query_service.can_make_query(ctx.author.id, 'search'):
                raise PermissionError("You have reached the maximum number of searches for today.")

            repos = await self.repo_service.get_all_repositories()
            if not repos:
                await ctx.send(embed=discord.Embed(title="Error", description="No repositories are currently indexed. Please contact an admin to add a repository.", color=discord.Color.red()))
                return

            await ctx.send(embed=discord.Embed(title="Searching", description="Searching repositories. This may take a moment...", color=discord.Color.blue()))

            results = await self.query_service.search(search_query, repos)

            if not results:
                await ctx.send(embed=discord.Embed(title="Search Results", description="No results found for your query.", color=discord.Color.blue()))
                return

            embeds = []
            current_embed = discord.Embed(title="Search Results", color=discord.Color.green())
            for i, result in enumerate(results, 1):
                current_embed.add_field(
                    name=f"{result['filepath']} (lines {result['linestart']}-{result['lineend']})",
                    value=f"Summary: {result['summary'][:100]}...",
                    inline=False
                )
                if len(current_embed.fields) >= 25:  # Discord's limit is 25 fields per embed
                    embeds.append(current_embed)
                    current_embed = discord.Embed(title=f"Search Results (cont.)", color=discord.Color.green())

            if current_embed.fields:
                embeds.append(current_embed)

            for embed in embeds:
                await ctx.send(embed=embed)

            await self.query_service.log_query(ctx.author.id, 'search')

        except PermissionError as e:
            await ctx.send(embed=create_error_embed("Permission Error", str(e)))
        except ConfigError as e:
            await ctx.send(embed=create_error_embed("Configuration Error", str(e)))
        except GreptileAPIError as e:
            error_embed = discord.Embed(title="Search Error", color=discord.Color.red())
            error_embed.add_field(name="Status", value=e.status_code, inline=False)
            error_embed.add_field(name="Message", value=e.message, inline=False)
            if e.details:
                error_embed.add_field(name="Details", value=str(e.details)[:1024], inline=False)
            await ctx.send(embed=error_embed)
            logger.error(f"GreptileAPIError in search command: {str(e)}", exc_info=True)
        except Exception as e:
            logger.error(f"Unexpected error in search command: {str(e)}", exc_info=True)
            await ctx.send(embed=create_error_embed("Error", "An unexpected error occurred. Please try again later."))

    @commands.command(name='query')
    async def query(self, ctx, *, question: str):
        await self.process_query(ctx, question, False)

    @commands.command(name='smartquery')
    async def smartquery(self, ctx, *, question: str):
        await self.process_query(ctx, question, True)

    async def process_query(self, ctx, question: str, genius: bool):
        query_type = 'smart_queries' if genius else 'queries'
        try:
            if not await self.query_service.can_make_query(ctx.author.id, query_type):
                raise PermissionError(f"You have reached the maximum number of {'smart ' if genius else ''}queries for today.")

            repos = await self.repo_service.get_all_repositories()
            if not repos:
                await ctx.send(embed=discord.Embed(title="Error", description="No repositories are currently indexed. Please contact an admin to add a repository.", color=discord.Color.red()))
                return

            await ctx.send(embed=discord.Embed(title="Processing Query", description="Processing your query. This may take a moment...", color=discord.Color.blue()))

            results = await self.query_service.query(question, repos, genius)

            for result in results:
                embed = discord.Embed(title="Query Result", description=result['message'][:4096], color=discord.Color.blue())
                
                if 'sources' in result:
                    sources = "\n".join([f"- {source['filepath']} (lines {source['linestart']}-{source['lineend']})" for source in result['sources'][:5]])
                    embed.add_field(name="Sources", value=sources[:1024], inline=False)

                await ctx.send(embed=embed)

            await self.query_service.log_query(ctx.author.id, query_type)

        except PermissionError as e:
            await ctx.send(embed=create_error_embed("Permission Error", str(e)))
        except ConfigError as e:
            await ctx.send(embed=create_error_embed("Configuration Error", str(e)))
        except GreptileAPIError as e:
            error_embed = discord.Embed(title="Query Error", color=discord.Color.red())
            error_embed.add_field(name="Status", value=e.status_code, inline=False)
            error_embed.add_field(name="Message", value=e.message, inline=False)
            if e.details:
                error_embed.add_field(name="Details", value=str(e.details)[:1024], inline=False)
            await ctx.send(embed=error_embed)
            logger.error(f"GreptileAPIError in {'smart ' if genius else ''}query command: {str(e)}", exc_info=True)
        except Exception as e:
            logger.error(f"Unexpected error in {'smart ' if genius else ''}query command: {str(e)}", exc_info=True)
            await ctx.send(embed=create_error_embed("Error", "An unexpected error occurred. Please try again later."))

    @commands.command(name='listrepos')
    async def list_repos(self, ctx):
        """
        List all indexed repositories.
        Usage: ~listrepos
        """
        try:
            repos = await self.repo_service.get_all_repositories()
            if not repos:
                await ctx.send(embed=discord.Embed(title="Repositories", description="No repositories are currently indexed.", color=discord.Color.blue()))
                return

            embed = discord.Embed(title="Indexed Repositories", color=discord.Color.blue())
            for repo in repos:
                embed.add_field(
                    name=f"{repo['owner']}/{repo['name']}",
                    value=f"Remote: {repo['remote']}\nBranch: {repo['branch']}\nLast Indexed: {repo['last_indexed_at'] or 'Never'}",
                    inline=False
                )
            
            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in list_repos command: {str(e)}", exc_info=True)
            await ctx.send(embed=create_error_embed("Error", "An unexpected error occurred while listing repositories."))

    @commands.command(name='repostatus')
    async def repo_status(self, ctx):
        """
        View the current status of the indexed repositories.
        Usage: ~repostatus
        """
        try:
            repos = await self.repo_service.get_all_repositories()
            if not repos:
                await ctx.send(embed=discord.Embed(title="Repository Status", description="No repositories are currently indexed.", color=discord.Color.red()))
                return

            status_updates = await self.repo_service.check_and_update_repo_status()
            
            embed = discord.Embed(title="Repository Status", color=discord.Color.blue())
            for update in status_updates:
                embed.add_field(
                    name=f"{update['owner']}/{update['name']}",
                    value=f"Remote: {update['remote']}\n"
                        f"Branch: {update['branch']}\n"
                        f"Status: {update['status']}\n"
                        f"Last Indexed: {update['last_indexed_at'] or 'Never'}",
                    inline=False
                )

            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in repo_status command: {str(e)}", exc_info=True)
            await ctx.send(embed=create_error_embed("Error", "An unexpected error occurred while fetching repository status."))

    @commands.command(name='usage')
    async def usage(self, ctx):
        """
        View your current usage statistics.
        Usage: ~usage
        """
        try:
            queries = await self.query_service.get_query_count(ctx.author.id, 'queries')
            smart_queries = await self.query_service.get_query_count(ctx.author.id, 'smart_queries')
            searches = await self.query_service.get_query_count(ctx.author.id, 'search')

            max_queries = await self.config_service.get_config('MAX_QUERIES_PER_DAY', 5)
            max_smart_queries = await self.config_service.get_config('MAX_SMART_QUERIES_PER_DAY', 1)
            max_searches = await self.config_service.get_config('MAX_SEARCHES_PER_DAY', 10)

            embed = discord.Embed(title="Your Usage Statistics", color=discord.Color.blue())
            embed.add_field(name="Regular Queries", value=f"{queries}/{max_queries}", inline=False)
            embed.add_field(name="Smart Queries", value=f"{smart_queries}/{max_smart_queries}", inline=False)
            embed.add_field(name="Searches", value=f"{searches}/{max_searches}", inline=False)
            embed.set_footer(text="Usage resets daily at midnight UTC.")

            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in usage command: {str(e)}", exc_info=True)
            await ctx.send(embed=create_error_embed("Error", "An unexpected error occurred while fetching usage statistics."))

    @commands.command(name='viewconfig')
    async def view_config(self, ctx):
        """
        View the current bot configuration (non-sensitive parts).
        Usage: ~viewconfig
        """
        try:
            config = await self.config_service.get_all_config()
            if config:
                # Filter out sensitive information
                safe_config = {k: v for k, v in config.items() if not k.lower().startswith(('token', 'api_key', 'secret'))}
                config_str = "\n".join([f"{k}: {v}" for k, v in safe_config.items()])
                await ctx.send(embed=discord.Embed(title="Current Configuration", description=config_str, color=discord.Color.blue()))
            else:
                await ctx.send(embed=create_error_embed("Error", "Failed to retrieve configuration."))
        except Exception as e:
            logger.error(f"Error in view_config command: {str(e)}", exc_info=True)
            await ctx.send(embed=create_error_embed("Error", "An unexpected error occurred while fetching configuration."))

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            await ctx.send(embed=create_error_embed("Error", "Command not found. Use ~greptilehelp to see available commands."))
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(embed=create_error_embed("Error", f"Missing required argument: {error.param.name}. Please check the command usage."))
        elif isinstance(error, commands.BadArgument):
            await ctx.send(embed=create_error_embed("Error", "Invalid argument provided. Please check the command usage."))
        elif isinstance(error, commands.CheckFailure):
            await ctx.send(embed=create_error_embed("Error", "You don't have permission to use this command."))
        elif isinstance(error, BotError):
            await ctx.send(embed=create_error_embed("Bot Error", str(error)))
        else:
            logger.error(f"Unexpected error in command {ctx.command}: {error}", exc_info=True)
            await ctx.send(embed=create_error_embed("Error", "An unexpected error occurred. Please try again later."))

        # Log the error to the error channel if it's set
        error_channel_id = await self.config_service.get_config('ERROR_CHANNEL_ID')
        if error_channel_id:
            error_channel = self.bot.get_channel(int(error_channel_id))
            if error_channel:
                error_message = f"Error in command {ctx.command}:\n```\n{type(error).__name__}: {str(error)}\n\n{traceback.format_exc()}\n```"
                await error_channel.send(error_message[:2000])  # Discord has a 2000 character limit

async def setup(bot):
    config_service = bot.config_service
    query_service = bot.query_service
    repo_service = bot.repo_service
    
    # Fetch configuration values
    max_queries_per_day = await config_service.get_config('MAX_QUERIES_PER_DAY', 5)
    max_smart_queries_per_day = await config_service.get_config('MAX_SMART_QUERIES_PER_DAY', 1)
    max_searches_per_day = await config_service.get_config('MAX_SEARCHES_PER_DAY', 10)
    
    # Update services with new configuration
    await query_service.set_query_limits(max_queries_per_day, max_smart_queries_per_day, max_searches_per_day)
    
    # Add the cog to the bot
    await bot.add_cog(UserCommands(bot, repo_service, query_service, config_service))