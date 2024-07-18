import discord
from discord.ext import commands
import logging
import traceback
import sys
import os
import importlib
import psutil
from config import config
from utils.helpers import create_error_embed, create_success_embed
from utils.error_handler import BotError, ConfigError, DatabaseError, APIError

logger = logging.getLogger(__name__)

class OwnerCommands(commands.Cog):
    def __init__(self, bot, repo_service, query_service, config_service):
        self.bot = bot
        self.repo_service = repo_service
        self.query_service = query_service
        self.config_service = config_service

    async def cog_check(self, ctx):
        return str(ctx.author.id) == config.get('bot.owner_id')

    @commands.command(name='reload')
    async def reload_bot(self, ctx):
        """
        Reload the bot (owner only).
        Usage: ~reload
        """
        try:
            await ctx.send(embed=discord.Embed(title="Reloading", description="Reloading the bot...", color=discord.Color.blue()))
            
            for extension in list(self.bot.extensions):
                await self.bot.reload_extension(extension)
            
            importlib.reload(sys.modules[self.bot.__module__])
            
            await ctx.send(embed=create_success_embed("Reload Complete", "Bot has been successfully reloaded."))
        except Exception as e:
            error_message = f"Error in reload_bot: {str(e)}\n\nTraceback:\n{''.join(traceback.format_tb(e.__traceback__))}"
            logger.error(error_message)
            await self.bot.report_error(error_message)
            await ctx.send(embed=create_error_embed("Error", f"An error occurred while reloading the bot: {str(e)}"))

    @commands.command(name='addadmin')
    async def add_admin(self, ctx, user_id: str):
        """
        Promote a user to admin.
        Usage: ~addadmin <user_id>
        Example: ~addadmin 123456789
        """
        try:
            if not user_id.isdigit():
                raise ValueError("Invalid user ID. Please provide a valid Discord user ID.")

            user = await self.bot.fetch_user(int(user_id))
            success = await self.config_service.add_to_whitelist(user_id, 'admin')
            if success:
                await ctx.send(embed=create_success_embed("Admin Added", f"User {user.name} (ID: {user_id}) promoted to admin."))
            else:
                raise BotError("Failed to add user as admin.")
        except discord.NotFound:
            await ctx.send(embed=create_error_embed("Error", "User not found. Please check the ID and try again."))
        except discord.HTTPException:
            await ctx.send(embed=create_error_embed("Error", "An error occurred while fetching user information. Please try again later."))
        except (ValueError, BotError) as e:
            await ctx.send(embed=create_error_embed("Error", str(e)))
        except Exception as e:
            logger.error(f"Unexpected error in add_admin command: {str(e)}", exc_info=True)
            await ctx.send(embed=create_error_embed("Error", "An unexpected error occurred. Please try again later."))

    @commands.command(name='removeadmin')
    async def remove_admin(self, ctx, user_id: str):
        """
        Demote an admin to regular user.
        Usage: ~removeadmin <user_id>
        Example: ~removeadmin 123456789
        """
        try:
            if not user_id.isdigit():
                raise ValueError("Invalid user ID. Please provide a valid Discord user ID.")

            user = await self.bot.fetch_user(int(user_id))
            success = await self.config_service.update_whitelist_role(user_id, 'user')
            if success:
                await ctx.send(embed=create_success_embed("Admin Removed", f"User {user.name} (ID: {user_id}) demoted to regular user."))
            else:
                raise BotError("Failed to demote admin. Please check if the user was an admin.")
        except discord.NotFound:
            await ctx.send(embed=create_error_embed("Error", "User not found. Please check the ID and try again."))
        except discord.HTTPException:
            await ctx.send(embed=create_error_embed("Error", "An error occurred while fetching user information. Please try again later."))
        except (ValueError, BotError) as e:
            await ctx.send(embed=create_error_embed("Error", str(e)))
        except Exception as e:
            logger.error(f"Unexpected error in remove_admin command: {str(e)}", exc_info=True)
            await ctx.send(embed=create_error_embed("Error", "An unexpected error occurred. Please try again later."))

    @commands.command(name='testerror')
    async def test_error(self, ctx):
        """
        Test the error reporting system.
        Usage: ~testerror
        """
        try:
            # Deliberately cause an error
            1 / 0
        except Exception as e:
            error_message = f"Test error: {str(e)}\n\nTraceback:\n{''.join(traceback.format_tb(e.__traceback__))}"
            logger.error(error_message)
            await self.bot.report_error(error_message)
            await ctx.send(embed=create_success_embed("Test Error", "A test error has been generated and reported. Check the error reporting channel."))

    @commands.command(name='shutdown')
    async def shutdown(self, ctx):
        """Shuts down the bot (owner only)."""
        await ctx.send("Shutting down the bot...")
        logger.info(f"Shutdown initiated by {ctx.author} (ID: {ctx.author.id})")
        await self.bot.close()

    @commands.command(name='updateconfig')
    async def update_config(self, ctx):
        """
        Update the bot's configuration from the config file (owner only).
        Usage: ~updateconfig
        """
        try:
            await self.config_service.reload_config()
            await ctx.send(embed=create_success_embed("Configuration Updated", "The bot's configuration has been updated from the config file."))
        except Exception as e:
            error_message = f"Error updating configuration: {str(e)}"
            logger.error(error_message)
            await self.bot.report_error(error_message)
            await ctx.send(embed=create_error_embed("Error", f"An error occurred while updating the configuration: {str(e)}"))

    @commands.command(name='botinfo')
    async def info_bot(self, ctx):
        """
        Display information about the bot (owner only).
        Usage: ~botinfo
        """
        try:
            embed = discord.Embed(title="Bot Information", color=discord.Color.blue())
            embed.add_field(name="Bot Version", value=self.bot.version, inline=False)
            embed.add_field(name="Discord.py Version", value=discord.__version__, inline=False)
            embed.add_field(name="Python Version", value=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}", inline=False)
            embed.add_field(name="Total Servers", value=str(len(self.bot.guilds)), inline=False)
            embed.add_field(name="Total Users", value=str(len(self.bot.users)), inline=False)
            
            # Get uptime
            uptime = discord.utils.utcnow() - self.bot.start_time
            hours, remainder = divmod(int(uptime.total_seconds()), 3600)
            minutes, seconds = divmod(remainder, 60)
            days, hours = divmod(hours, 24)
            embed.add_field(name="Uptime", value=f"{days}d {hours}h {minutes}m {seconds}s", inline=False)

            # Get memory usage
            process = psutil.Process(os.getpid())
            memory_usage = process.memory_info().rss / 1024 ** 2  # in MB
            embed.add_field(name="Memory Usage", value=f"{memory_usage:.2f} MB", inline=False)

            await ctx.send(embed=embed)
        except Exception as e:
            logger.error(f"Error in botinfo command: {str(e)}", exc_info=True)
            await ctx.send(embed=create_error_embed("Error", "An unexpected error occurred while fetching bot information."))

async def setup(bot):
    await bot.add_cog(OwnerCommands(bot, bot.repo_service, bot.query_service, bot.config_service))