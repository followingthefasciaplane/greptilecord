import discord
from discord.ext import commands
import logging
from typing import Dict, Any
from utils.helpers import is_valid_discord_id, create_error_embed, create_success_embed

logger = logging.getLogger(__name__)

class AdminCommands(commands.Cog):
    def __init__(self, bot, repo_service, query_service, config_service):
        self.bot = bot
        self.repo_service = repo_service
        self.query_service = query_service
        self.config_service = config_service

    async def cog_check(self, ctx):
        return await self.config_service.get_user_role(ctx.author.id) == 'admin'

    @commands.command(name='addrepo')
    async def add_repo(self, ctx, remote: str, owner: str, name: str, branch: str):
        """
        Add and index a new repository.
        Usage: ~addrepo <remote> <owner> <name> <branch>
        Example: ~addrepo github openai gpt-3 main
        """
        try:
            success = await self.repo_service.add_repository(remote, owner, name, branch)
            if success:
                embed = create_success_embed("Repository Added", f"Repository {owner}/{name} has been added and indexing has been initiated.")
            else:
                embed = create_error_embed("Error", "Failed to add repository. Please check the logs for more information.")
        except Exception as e:
            logger.error(f"Error in add_repo command: {str(e)}")
            embed = create_error_embed("Error", f"An unexpected error occurred: {str(e)}")
        
        await ctx.send(embed=embed)

    @commands.command(name='removerepos')
    async def remove_repos(self, ctx):
        """
        Remove all indexed repositories.
        Usage: ~removerepos
        """
        try:
            success = await self.repo_service.remove_all_repositories()
            if success:
                embed = create_success_embed("Repositories Removed", "All repositories have been removed from the index.")
            else:
                embed = create_error_embed("Error", "Failed to remove repositories. Please check the logs for more information.")
        except Exception as e:
            logger.error(f"Error in remove_repos command: {str(e)}")
            embed = create_error_embed("Error", f"An unexpected error occurred: {str(e)}")
        
        await ctx.send(embed=embed)

    @commands.command(name='reindex')
    async def reindex_repo(self, ctx):
        """
        Force reindexing of all current repositories.
        Usage: ~reindex
        """
        try:
            repos = await self.repo_service.get_all_repositories()
            if not repos:
                embed = create_error_embed("Error", "No repositories are currently indexed.")
            else:
                reindex_results = []
                for repo in repos:
                    result = await self.repo_service.index_repository(repo)
                    if result:
                        reindex_results.append(f"Reindexing started for {repo['owner']}/{repo['name']}")
                    else:
                        reindex_results.append(f"Failed to start reindexing for {repo['owner']}/{repo['name']}")
                
                embed = create_success_embed("Reindexing Status", "\n".join(reindex_results))
        except Exception as e:
            logger.error(f"Error in reindex_repo command: {str(e)}")
            embed = create_error_embed("Error", f"An unexpected error occurred: {str(e)}")
        
        await ctx.send(embed=embed)

    @commands.command(name='listwhitelist')
    async def list_whitelist(self, ctx):
        """
        List all whitelisted users.
        Usage: ~listwhitelist
        """
        try:
            whitelist = await self.config_service.get_whitelist()
            if whitelist:
                embed = discord.Embed(title="Whitelisted Users", color=discord.Color.blue())
                for user_id, role in whitelist:
                    embed.add_field(name=f"User ID: {user_id}", value=f"Role: {role}", inline=False)
            else:
                embed = create_error_embed("Error", "No users are currently whitelisted.")
        except Exception as e:
            logger.error(f"Error in list_whitelist command: {str(e)}")
            embed = create_error_embed("Error", f"An unexpected error occurred: {str(e)}")
        
        await ctx.send(embed=embed)

    @commands.command(name='addwhitelist')
    async def add_whitelist(self, ctx, user_id: str):
        """
        Add a user to the whitelist.
        Usage: ~addwhitelist <user_id>
        Example: ~addwhitelist 123456789
        """
        if not is_valid_discord_id(user_id):
            embed = create_error_embed("Error", "Invalid user ID. Please provide a valid Discord user ID.")
        else:
            try:
                success = await self.config_service.add_to_whitelist(user_id, 'user')
                if success:
                    embed = create_success_embed("Whitelist Updated", f"User {user_id} has been added to the whitelist.")
                else:
                    embed = create_error_embed("Error", "Failed to add user to whitelist. Please check the logs for more information.")
            except Exception as e:
                logger.error(f"Error in add_whitelist command: {str(e)}")
                embed = create_error_embed("Error", f"An unexpected error occurred: {str(e)}")
        
        await ctx.send(embed=embed)

    @commands.command(name='removewhitelist')
    async def remove_whitelist(self, ctx, user_id: str):
        """
        Remove a user from the whitelist.
        Usage: ~removewhitelist <user_id>
        Example: ~removewhitelist 123456789
        """
        if not is_valid_discord_id(user_id):
            embed = create_error_embed("Error", "Invalid user ID. Please provide a valid Discord user ID.")
        else:
            try:
                success = await self.config_service.remove_from_whitelist(user_id)
                if success:
                    embed = create_success_embed("Whitelist Updated", f"User {user_id} has been removed from the whitelist.")
                else:
                    embed = create_error_embed("Error", "Failed to remove user from whitelist. Please check the logs for more information.")
            except Exception as e:
                logger.error(f"Error in remove_whitelist command: {str(e)}")
                embed = create_error_embed("Error", f"An unexpected error occurred: {str(e)}")
        
        await ctx.send(embed=embed)

    @commands.command(name='setlogchannel')
    async def set_log_channel(self, ctx, channel_id: str):
        """
        Set the channel for logging bot activities.
        Usage: ~setlogchannel <channel_id>
        Example: ~setlogchannel 123456789
        """
        if not channel_id.isdigit():
            embed = create_error_embed("Error", "Invalid channel ID. Please provide a valid Discord channel ID.")
        else:
            channel = self.bot.get_channel(int(channel_id))
            if channel is None:
                embed = create_error_embed("Error", "Channel not found. Make sure the bot has access to the specified channel.")
            else:
                try:
                    success = await self.config_service.set_config('LOG_CHANNEL_ID', channel_id)
                    if success:
                        embed = create_success_embed("Log Channel Set", f"Log channel has been set to {channel.name} (ID: {channel_id})")
                    else:
                        embed = create_error_embed("Error", "Failed to set log channel. Please check the logs for more information.")
                except Exception as e:
                    logger.error(f"Error in set_log_channel command: {str(e)}")
                    embed = create_error_embed("Error", f"An unexpected error occurred: {str(e)}")
        
        await ctx.send(embed=embed)

    @commands.command(name='seterrorchannel')
    async def set_error_channel(self, ctx, channel_id: str):
        """
        Set the channel for error reporting.
        Usage: ~seterrorchannel <channel_id>
        Example: ~seterrorchannel 123456789
        """
        if not channel_id.isdigit():
            embed = create_error_embed("Error", "Invalid channel ID. Please provide a valid Discord channel ID.")
        else:
            channel = self.bot.get_channel(int(channel_id))
            if channel is None:
                embed = create_error_embed("Error", "Channel not found. Make sure the bot has access to the specified channel.")
            else:
                try:
                    success = await self.config_service.set_config('ERROR_CHANNEL_ID', channel_id)
                    if success:
                        embed = create_success_embed("Error Channel Set", f"Error channel has been set to {channel.name} (ID: {channel_id})")
                    else:
                        embed = create_error_embed("Error", "Failed to set error channel. Please check the logs for more information.")
                except Exception as e:
                    logger.error(f"Error in set_error_channel command: {str(e)}")
                    embed = create_error_embed("Error", f"An unexpected error occurred: {str(e)}")
        
        await ctx.send(embed=embed)

async def setup(bot):
    await bot.add_cog(AdminCommands(bot, bot.repo_service, bot.query_service, bot.config_service))