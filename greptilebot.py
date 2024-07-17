import os
import sys
from typing import Optional, List, Dict, Any, Tuple, Union
import discord
from discord.ext import commands, tasks
import aiohttp
from datetime import datetime, timedelta
import asyncio
import urllib.parse
import json
import logging
from enum import Enum
import yaml
import sqlite3
import aiosqlite
from collections import defaultdict
import traceback
from aiohttp import ClientResponseError
from contextlib import asynccontextmanager
import functools

# Enhanced logging setup
logging.basicConfig(
    filename='bot.log',
    level=logging.DEBUG,
    format='%(asctime)s:%(levelname)s:%(message)s'
)
logger = logging.getLogger(__name__)

# Database connection pool
import aiosqlite

class DatabasePool:
    def __init__(self, database_name, max_connections=5):
        self.database_name = database_name
        self.max_connections = max_connections
        self._pool = asyncio.Queue(maxsize=max_connections)

    async def init(self):
        for _ in range(self.max_connections):
            conn = await aiosqlite.connect(self.database_name)
            await self._pool.put(conn)

    @asynccontextmanager
    async def acquire(self):
        conn = await self._pool.get()
        try:
            yield conn
        finally:
            await self._pool.put(conn)

    async def close(self):
        while not self._pool.empty():
            conn = await self._pool.get()
            await conn.close()

db_pool = DatabasePool('bot_data.db')

# Load configuration
def load_config():
    with open('config.yaml', 'r') as config_file:
        return yaml.safe_load(config_file)

config = load_config()

# Load tokens and API keys
with open('secrets.yaml', 'r') as secrets_file:
    secrets = yaml.safe_load(secrets_file)

TOKEN = secrets['DISCORD_BOT_TOKEN']
GREPTILE_API_KEY = secrets['GREPTILE_API_KEY']
GITHUB_TOKEN = secrets['GITHUB_TOKEN']
BOT_OWNER_ID = secrets['BOT_OWNER_ID']

BOT_PERMISSIONS = discord.Permissions(config['BOT_PERMISSIONS'])

# Initialize bot with all intents
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=config.get('BOT_PREFIX', '~'), intents=intents)

bot.remove_command('help')

# Enums
class RepoRemote(Enum):
    GITHUB = "github"
    GITLAB = "gitlab"

class UserRole(Enum):
    USER = "user"
    ADMIN = "admin"
    OWNER = "owner"

# Load configuration from database
async def load_db_config():
    async with db_pool.acquire() as conn:
        async with conn.execute("SELECT key, value FROM config") as cursor:
            return {row[0]: row[1] for row in await cursor.fetchall()}

CONFIG = {}

# Track user queries
user_queries = defaultdict(lambda: defaultdict(list))

# Helper functions
def is_whitelisted(role: UserRole = UserRole.USER):
    async def predicate(ctx: commands.Context):
        if str(ctx.author.id) == BOT_OWNER_ID:
            return True
        async with db_pool.acquire() as conn:
            async with conn.execute("SELECT role FROM whitelist WHERE user_id = ?", (str(ctx.author.id),)) as cursor:
                result = await cursor.fetchone()
        if not result:
            return False
        user_role = UserRole(result[0])
        return user_role.value >= role.value
    return commands.check(predicate)

async def update_config(key: str, value: str):
    async with db_pool.acquire() as conn:
        await conn.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
        await conn.commit()
    CONFIG[key] = value

async def get_repos():
    async with db_pool.acquire() as conn:
        async with conn.execute("SELECT remote, owner, name, branch FROM repos") as cursor:
            return await cursor.fetchall()

async def can_make_query(user_id: int, query_type: str) -> bool:
    if str(user_id) == BOT_OWNER_ID:
        return True
    today = datetime.now().date()
    user_queries[user_id][query_type] = [date for date in user_queries[user_id][query_type] if date.date() == today]
    max_queries = int(CONFIG.get(f'MAX_{query_type.upper()}_QUERIES_PER_DAY', 5))
    return len(user_queries[user_id][query_type]) < max_queries

async def get_repository_status(repo: Tuple[str, str, str, str]) -> Optional[str]:
    remote, owner, name, branch = repo
    repo_id = f"{remote}:{branch}:{owner}/{name}"
    encoded_repo_id = urllib.parse.quote(repo_id, safe='')
    url = f'https://api.greptile.com/v2/repositories/{encoded_repo_id}'
    
    headers = {
        'Authorization': f'Bearer {GREPTILE_API_KEY}',
        'X-GitHub-Token': GITHUB_TOKEN
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(url, headers=headers) as response:
                response.raise_for_status()
                repo_info = await response.json()
                logger.info(f"Repository info retrieved successfully: {repo_info}")
                return repo_info['status']
        except ClientResponseError as e:
            logger.error(f"HTTP error occurred while checking repository status: {e.status} - {e.message}")
            await report_error(f"HTTP error in get_repository_status: {e.status} - {e.message}")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"An error occurred while checking repository status: {str(e)}")
            logger.error(f"URL attempted: {url}")
            await report_error(f"Client error in get_repository_status: {str(e)}")
            return None

async def index_repository(ctx: commands.Context, repo: Tuple[str, str, str, str]) -> str:
    """
    Index a repository using the Greptile API.

    Args:
    ctx (commands.Context): The context of the command.
    repo (Tuple[str, str, str, str]): A tuple containing (remote, owner, name, branch) of the repository.

    Returns:
    str: The final status of the indexing process ('completed', 'failed', or 'processing').
    """
    remote, owner, name, branch = repo
    
    # Check if the repository is already indexed
    current_status = await get_repository_status(repo)
    
    if current_status == 'completed':
        await ctx.send(embed=discord.Embed(title="Repository Status", description="This repository is already indexed.", color=discord.Color.green()))
        return 'completed'
    elif current_status == 'processing':
        await ctx.send(embed=discord.Embed(title="Repository Status", description="This repository is currently being processed. Please wait for it to complete.", color=discord.Color.blue()))
        return 'processing'

    url = 'https://api.greptile.com/v2/repositories'
    headers = {
        'Authorization': f'Bearer {GREPTILE_API_KEY}',
        'X-GitHub-Token': GITHUB_TOKEN,
        'Content-Type': 'application/json'
    }
    payload = {
        "remote": remote,
        "repository": f"{owner}/{name}",
        "branch": branch,
        "reload": False,
        "notify": False
    }

    status_embed = discord.Embed(title="Repository Indexing", description="Starting indexing process...", color=discord.Color.blue())
    status_message = await ctx.send(embed=status_embed)

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload, headers=headers) as response:
                response.raise_for_status()
                result = await response.json()
                logger.info(f"Repository indexing response: {result['response']}")
                
                status_embed.description = f"Indexing started: {result['response']}"
                await status_message.edit(embed=status_embed)

                # Start checking the indexing status
                final_status = await check_indexing_status(ctx, status_message, repo)
                return final_status

        except ClientResponseError as e:
            error_message = f"HTTP error occurred while indexing the repository: {e.status} - {e.message}"
            logger.error(error_message)
            logger.error(f"URL attempted: {url}")
            logger.error(f"Payload: {payload}")
            status_embed.description = f"Failed to start indexing. HTTP Error: {e.status} - {e.message}"
            status_embed.color = discord.Color.red()
            await status_message.edit(embed=status_embed)
            await report_error(error_message)
            return 'failed'

        except aiohttp.ClientError as e:
            error_message = f"Client error occurred while indexing the repository: {str(e)}"
            logger.error(error_message)
            logger.error(f"URL attempted: {url}")
            logger.error(f"Payload: {payload}")
            status_embed.description = f"Failed to start indexing. Client Error: {str(e)}"
            status_embed.color = discord.Color.red()
            await status_message.edit(embed=status_embed)
            await report_error(error_message)
            return 'failed'

        except Exception as e:
            error_message = f"Unexpected error occurred while indexing the repository: {str(e)}"
            logger.error(error_message)
            logger.error(f"URL attempted: {url}")
            logger.error(f"Payload: {payload}")
            status_embed.description = f"Failed to start indexing. Unexpected Error: {str(e)}"
            status_embed.color = discord.Color.red()
            await status_message.edit(embed=status_embed)
            await report_error(error_message)
            return 'failed'

async def check_indexing_status(ctx: commands.Context, status_message: discord.Message, repo: Tuple[str, str, str, str]) -> str:
    progress = 0
    while True:
        status = await get_repository_status(repo)
        status_embed = status_message.embeds[0]
        
        if status == 'completed':
            status_embed.description = "Repository indexing completed."
            status_embed.color = discord.Color.green()
            await status_message.edit(embed=status_embed)
            return 'completed'
        elif status == 'failed':
            status_embed.description = "Repository indexing failed."
            status_embed.color = discord.Color.red()
            await status_message.edit(embed=status_embed)
            return 'failed'
        elif status is None:
            status_embed.description = "Unable to retrieve repository status. Stopping indexing check."
            status_embed.color = discord.Color.orange()
            await status_message.edit(embed=status_embed)
            return 'failed'
        else:
            progress += 10
            progress = min(progress, 90)  # Cap at 90% to avoid false completion
            status_embed.description = f"Indexing status: {status}\nProgress: {progress}%"
            status_embed.set_footer(text="This progress is an estimate and may not reflect actual indexing progress.")
            await status_message.edit(embed=status_embed)
        
        await asyncio.sleep(60)  # Check every minute

async def report_error(error_message: str):
    """
    Report an error to the designated error channel and the bot owner.
    Prevents duplicate error reports within a short time frame.

    Args:
    error_message (str): The error message to report.
    """
    current_time = datetime.now()
    
    # Initialize last_error_time and last_error_message if they don't exist
    if not hasattr(report_error, 'last_error_time'):
        report_error.last_error_time = None
    if not hasattr(report_error, 'last_error_message'):
        report_error.last_error_message = None

    # Check if this error was recently reported
    if report_error.last_error_time is not None and report_error.last_error_message is not None:
        time_since_last_error = current_time - report_error.last_error_time
        if time_since_last_error.total_seconds() < 300 and report_error.last_error_message == error_message:  # 5 minutes
            return  # Skip reporting if it's the same error within 5 minutes

    # Update the last error information
    report_error.last_error_time = current_time
    report_error.last_error_message = error_message

    # Prepare the error embed
    error_embed = discord.Embed(
        title="Error Report",
        description=error_message,
        color=discord.Color.red(),
        timestamp=current_time
    )

    # Send to error channel if configured
    error_channel_id = CONFIG.get('error_channel')
    if error_channel_id:
        channel = bot.get_channel(int(error_channel_id))
        if channel:
            try:
                await channel.send(embed=error_embed)
            except discord.errors.Forbidden:
                logger.error(f"Bot doesn't have permission to send messages in the error channel (ID: {error_channel_id})")
            except Exception as e:
                logger.error(f"Failed to send error message to error channel: {str(e)}")
    
    # Send to bot owner
    try:
        owner = await bot.fetch_user(int(BOT_OWNER_ID))
        if owner:
            await owner.send(embed=error_embed)
    except discord.errors.NotFound:
        logger.error(f"Bot owner with ID {BOT_OWNER_ID} not found")
    except discord.errors.Forbidden:
        logger.error("Bot doesn't have permission to send DM to the owner")
    except Exception as e:
        logger.error(f"Failed to send error message to bot owner: {str(e)}")

    # Log the error
    logger.error(f"Error reported: {error_message}")

async def log_to_channel(guild_id: int, embed: discord.Embed):
    """Log an embed to the designated log channel."""
    log_channel_id = CONFIG.get('log_channel')
    if log_channel_id:
        channel = bot.get_channel(int(log_channel_id))
        if channel:
            await channel.send(embed=embed)

@bot.command(name='greptilehelp')
async def greptilehelp(ctx: commands.Context):
    """
    Display detailed help information for Greptile bot commands.
    """
    embed = discord.Embed(
        title="Greptile Bot Help",
        description="This bot answers questions about specific GitHub repositories using the Greptile API. Here are the available commands:",
        color=discord.Color.blue()
    )

    # Sort commands alphabetically
    sorted_commands = sorted(bot.commands, key=lambda x: x.name)

    for command in sorted_commands:
        if command.hidden:
            continue
        
        command_help = command.help or "No description available."

        embed.add_field(
            name=f"{command.name.capitalize()}",
            value=command_help,
            inline=False
        )

    embed.add_field(
        name="Usage Limits",
        value=f"- You can make up to {CONFIG.get('MAX_QUERIES_PER_DAY', 5)} regular queries and {CONFIG.get('MAX_SMART_QUERIES_PER_DAY', 1)} smart queries per day.\n"
            f"- Only whitelisted users can use these commands.",
        inline=False
    )
    embed.set_footer(text="If you have any issues or questions, please contact the bot owner.")

    await ctx.send(embed=embed)

@bot.command(name='search')
@is_whitelisted(UserRole.USER)
async def search(ctx: commands.Context, *, search_query: str):
    """
    Search for relevant code in the repository.
    Usage: ~search <query>
    Example: ~search "function to calculate fibonacci sequence"
    """
    if not await can_make_query(ctx.author.id, 'search'):
        await ctx.send(embed=discord.Embed(title="Error", description="You have reached the maximum number of queries for today.", color=discord.Color.red()))
        return

    repos = await get_repos()
    if not repos:
        await ctx.send(embed=discord.Embed(title="Error", description="No repositories indexed. Please add a repository first.", color=discord.Color.red()))
        return

    url = 'https://api.greptile.com/v2/search'
    headers = {
        'Authorization': f'Bearer {GREPTILE_API_KEY}',
        'X-GitHub-Token': GITHUB_TOKEN,
        'Content-Type': 'application/json'
    }
    payload = {
        "query": search_query,
        "repositories": [
            {
                "remote": repo[0],
                "repository": f"{repo[1]}/{repo[2]}",
                "branch": repo[3]
            } for repo in repos
        ],
        "sessionId": f"discord-search-{ctx.author.id}-{ctx.message.id}",
        "stream": False
    }

    async with aiohttp.ClientSession() as session:
        try:
            start_time = datetime.now()
            async with session.post(url, json=payload, headers=headers) as response:
                response.raise_for_status()
                results = await response.json()
            end_time = datetime.now()
            response_time = (end_time - start_time).total_seconds()

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

            embeds[-1].add_field(name="Response Time", value=f"{response_time:.2f} seconds", inline=False)

            for embed in embeds:
                await ctx.send(embed=embed)

            user_queries[ctx.author.id]['search'].append(datetime.now())
            await log_to_channel(ctx.guild.id, embeds[0])

        except aiohttp.ClientResponseError as e:
            error_message = f"HTTP error in search: {e.status} - {e.message}"
            logger.error(error_message)
            await report_error(error_message)
            await ctx.send(embed=discord.Embed(title="Error", description=f"An error occurred while searching. Status: {e.status}. Please try again later.", color=discord.Color.red()))
        except aiohttp.ClientError as e:
            error_message = f"Client error in search: {str(e)}"
            logger.error(error_message)
            await report_error(error_message)
            await ctx.send(embed=discord.Embed(title="Error", description="An error occurred while searching. Please try again later.", color=discord.Color.red()))
        except Exception as e:
            error_message = f"Unexpected error in search: {str(e)}"
            logger.error(error_message)
            await report_error(error_message)
            await ctx.send(embed=discord.Embed(title="Error", description="An unexpected error occurred. Please try again later.", color=discord.Color.red()))

@bot.command(name='query')
@is_whitelisted(UserRole.USER)
async def query(ctx: commands.Context, *, question: str):
    """
    Ask a question about the codebase and get a detailed answer.
    Usage: ~query <question>
    Example: ~query "How does the authentication system work?"
    """
    await process_query(ctx, question, False)

@bot.command(name='smartquery')
@is_whitelisted(UserRole.USER)
async def smartquery(ctx: commands.Context, *, question: str):
    """
    Ask a more complex question using the 'genius' feature for more detailed analysis.
    Usage: ~smartquery <question>
    Example: ~smartquery "Explain the overall architecture of the project and how different components interact."
    """
    await process_query(ctx, question, True)

async def process_query(ctx: commands.Context, question: str, genius: bool):
    """
    Process a query to the Greptile API.
    
    Args:
    ctx (commands.Context): The context of the command.
    question (str): The question to be asked.
    genius (bool): Whether to use the 'genius' feature for more detailed analysis.
    """
    query_type = 'smart_queries' if genius else 'queries'
    if not await can_make_query(ctx.author.id, query_type):
        await ctx.send(embed=discord.Embed(title="Error", description=f"You have reached the maximum number of {'smart ' if genius else ''}queries for today.", color=discord.Color.red()))
        return

    repos = await get_repos()
    if not repos:
        await ctx.send(embed=discord.Embed(title="Error", description="No repositories indexed. Please add a repository first.", color=discord.Color.red()))
        return

    url = 'https://api.greptile.com/v2/query'
    headers = {
        'Authorization': f'Bearer {GREPTILE_API_KEY}',
        'X-GitHub-Token': GITHUB_TOKEN,
        'Content-Type': 'application/json'
    }
    payload = {
        "messages": [
            {
                "id": str(ctx.message.id),
                "content": question,
                "role": "user"
            }
        ],
        "repositories": [
            {
                "remote": repo[0],
                "repository": f"{repo[1]}/{repo[2]}",
                "branch": repo[3]
            } for repo in repos
        ],
        "sessionId": f"discord-query-{ctx.author.id}-{ctx.message.id}",
        "stream": False,
        "genius": genius
    }

    async with aiohttp.ClientSession() as session:
        try:
            start_time = datetime.now()
            async with session.post(url, json=payload, headers=headers) as response:
                response.raise_for_status()
                result = await response.json()
            end_time = datetime.now()
            response_time = (end_time - start_time).total_seconds()

            embed = discord.Embed(title="Query Result", description=result['message'], color=discord.Color.blue())
            
            if 'sources' in result:
                sources = "\n".join([f"- {source['filepath']} (lines {source['linestart']}-{source['lineend']})" for source in result['sources']])
                embed.add_field(name="Sources", value=sources, inline=False)

            embed.add_field(name="Response Time", value=f"{response_time:.2f} seconds", inline=False)

            await ctx.send(embed=embed)
            await log_to_channel(ctx.guild.id, embed)

            user_queries[ctx.author.id][query_type].append(datetime.now())

        except ClientResponseError as e:
            error_message = f"HTTP error in query: {e.status} - {e.message}"
            logger.error(error_message)
            await report_error(error_message)
            await ctx.send(embed=discord.Embed(title="Error", description=f"An error occurred while processing your request. Status: {e.status}. Please try again later.", color=discord.Color.red()))
        except aiohttp.ClientError as e:
            error_message = f"Client error in query: {str(e)}"
            logger.error(error_message)
            await report_error(error_message)
            await ctx.send(embed=discord.Embed(title="Error", description="An error occurred while processing your request. Please try again later.", color=discord.Color.red()))
        except Exception as e:
            error_message = f"Unexpected error in query: {str(e)}"
            logger.error(error_message)
            await report_error(error_message)
            await ctx.send(embed=discord.Embed(title="Error", description="An unexpected error occurred. Please try again later.", color=discord.Color.red()))

@bot.command(name='listrepos')
@is_whitelisted(UserRole.USER)
async def list_repos(ctx: commands.Context):
    """
    List all indexed repositories.
    Usage: ~listrepos
    """
    repos = await get_repos()
    if not repos:
        await ctx.send(embed=discord.Embed(title="Repositories", description="No repositories are currently indexed.", color=discord.Color.blue()))
        return

    embed = discord.Embed(title="Indexed Repositories", color=discord.Color.blue())
    for repo in repos:
        remote, owner, name, branch = repo
        embed.add_field(name=f"{owner}/{name}", value=f"Remote: {remote}\nBranch: {branch}", inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='addrepo')
@is_whitelisted(UserRole.ADMIN)
async def add_repo(ctx: commands.Context, remote: str, owner: str, name: str, branch: str):
    """
    Add and index a new repository.
    Usage: ~addrepo <remote> <owner> <name> <branch>
    Example: ~addrepo github openai gpt-3 main
    """
    existing_repos = await get_repos()
    if existing_repos:
        await ctx.send(embed=discord.Embed(title="Error", description="Cannot add a new repo when others exist. Please remove all repos first using ~removerepos.", color=discord.Color.red()))
        return

    # Check if the repository already exists in the database
    async with db_pool.acquire() as conn:
        async with conn.execute("SELECT * FROM repos WHERE remote=? AND owner=? AND name=? AND branch=?", (remote, owner, name, branch)) as cursor:
            if await cursor.fetchone():
                # Check the indexing status
                status = await get_repository_status((remote, owner, name, branch))
                if status == 'completed':
                    await ctx.send(embed=discord.Embed(title="Repository Status", description="This repository is already indexed.", color=discord.Color.green()))
                    return
                elif status == 'processing':
                    await ctx.send(embed=discord.Embed(title="Repository Status", description="This repository is currently being processed. Please wait for it to complete.", color=discord.Color.blue()))
                    return
                # If status is 'failed' or None, we'll re-index the repository

        # Add the repository to the database
        await conn.execute("INSERT INTO repos (remote, owner, name, branch) VALUES (?, ?, ?, ?)",
                (remote, owner, name, branch))
        await conn.commit()

    await ctx.send(embed=discord.Embed(title="Repository Added", description="Repository has been added to the database. Starting indexing process...", color=discord.Color.green()))
    
    # Start indexing process
    status = await index_repository(ctx, (remote, owner, name, branch))

    # Check the indexing result
    if status != 'completed':
        # If indexing failed, remove the repository from the database
        async with db_pool.acquire() as conn:
            await conn.execute("DELETE FROM repos WHERE remote=? AND owner=? AND name=? AND branch=?", (remote, owner, name, branch))
            await conn.commit()
        await ctx.send(embed=discord.Embed(title="Repository Removed", description="Repository indexing failed and has been removed from the database.", color=discord.Color.red()))
    else:
        await ctx.send(embed=discord.Embed(title="Repository Indexed", description="Repository has been successfully indexed and is ready for use.", color=discord.Color.green()))

@bot.command(name='removerepos')
@is_whitelisted(UserRole.ADMIN)
async def remove_repos(ctx: commands.Context):
    """
    Remove all indexed repositories.
    Usage: ~removerepos
    """
    async with db_pool.acquire() as conn:
        await conn.execute("DELETE FROM repos")
        await conn.commit()
    await ctx.send(embed=discord.Embed(title="Repositories Removed", description="All repositories have been removed from the index.", color=discord.Color.green()))

@bot.command(name='setconfig')
@is_whitelisted(UserRole.ADMIN)
async def set_config(ctx: commands.Context, key: str, value: str):
    """
    Set a configuration value.
    Usage: ~setconfig <key> <value>
    Example: ~setconfig MAX_QUERIES_PER_DAY 10
    """
    await update_config(key, value)
    await ctx.send(embed=discord.Embed(title="Configuration Updated", description=f"{key} has been set to {value}", color=discord.Color.green()))
    await ctx.send(embed=discord.Embed(title="Notice", description="Configuration updated. Some changes may require a bot restart to take effect.", color=discord.Color.blue()))


@bot.command(name='listwhitelist')
@is_whitelisted(UserRole.USER)
async def list_whitelist(ctx: commands.Context):
    """
    List all whitelisted users.
    Usage: ~listwhitelist
    """
    async with db_pool.acquire() as conn:
        async with conn.execute("SELECT user_id, role FROM whitelist") as cursor:
            whitelist = await cursor.fetchall()
    
    embed = discord.Embed(title="Whitelisted Users", color=discord.Color.blue())
    for user_id, role in whitelist:
        embed.add_field(name=user_id, value=role, inline=False)
    
    await ctx.send(embed=embed)

@bot.command(name='addwhitelist')
@is_whitelisted(UserRole.ADMIN)
async def add_whitelist(ctx: commands.Context, user_id: str):
    """
    Add a user to the whitelist.
    Usage: ~addwhitelist <user_id>
    Example: ~addwhitelist 123456789
    """
    if not user_id.isdigit():
        await ctx.send(embed=discord.Embed(title="Error", description="Invalid user ID. Please provide a valid Discord user ID.", color=discord.Color.red()))
        return

    async with db_pool.acquire() as conn:
        try:
            await conn.execute("INSERT OR REPLACE INTO whitelist (user_id, role) VALUES (?, ?)", (user_id, UserRole.USER.value))
            await conn.commit()
            await ctx.send(embed=discord.Embed(title="Whitelist Updated", description=f"User {user_id} added to whitelist.", color=discord.Color.green()))
        except Exception as e:
            error_message = f"Database error in add_whitelist: {str(e)}"
            logger.error(error_message)
            await report_error(error_message)
            await ctx.send(embed=discord.Embed(title="Error", description="An error occurred while updating the whitelist. Please try again later.", color=discord.Color.red()))

@bot.command(name='removewhitelist')
@is_whitelisted(UserRole.ADMIN)
async def remove_whitelist(ctx: commands.Context, user_id: str):
    """
    Remove a user from the whitelist.
    Usage: ~removewhitelist <user_id>
    Example: ~removewhitelist 123456789
    """
    if not user_id.isdigit():
        await ctx.send(embed=discord.Embed(title="Error", description="Invalid user ID. Please provide a valid Discord user ID.", color=discord.Color.red()))
        return

    async with db_pool.acquire() as conn:
        try:
            result = await conn.execute("DELETE FROM whitelist WHERE user_id = ?", (user_id,))
            await conn.commit()
            if result.rowcount == 0:
                await ctx.send(embed=discord.Embed(title="Whitelist Update", description=f"User {user_id} was not in the whitelist.", color=discord.Color.yellow()))
            else:
                await ctx.send(embed=discord.Embed(title="Whitelist Updated", description=f"User {user_id} removed from whitelist.", color=discord.Color.green()))
        except Exception as e:
            error_message = f"Database error in remove_whitelist: {str(e)}"
            logger.error(error_message)
            await report_error(error_message)
            await ctx.send(embed=discord.Embed(title="Error", description="An error occurred while updating the whitelist. Please try again later.", color=discord.Color.red()))

@bot.command(name='addadmin')
@is_whitelisted(UserRole.OWNER)
async def add_admin(ctx: commands.Context, user_id: str):
    """
    Promote a user to admin.
    Usage: ~addadmin <user_id>
    Example: ~addadmin 123456789
    """
    if not user_id.isdigit():
        await ctx.send(embed=discord.Embed(title="Error", description="Invalid user ID. Please provide a valid Discord user ID.", color=discord.Color.red()))
        return

    async with db_pool.acquire() as conn:
        try:
            await conn.execute("INSERT OR REPLACE INTO whitelist (user_id, role) VALUES (?, ?)", (user_id, UserRole.ADMIN.value))
            await conn.commit()
            await ctx.send(embed=discord.Embed(title="Admin Added", description=f"User {user_id} promoted to admin.", color=discord.Color.green()))
        except Exception as e:
            error_message = f"Database error in add_admin: {str(e)}"
            logger.error(error_message)
            await report_error(error_message)
            await ctx.send(embed=discord.Embed(title="Error", description="An error occurred while promoting the user to admin. Please try again later.", color=discord.Color.red()))

@bot.command(name='removeadmin')
@is_whitelisted(UserRole.OWNER)
async def remove_admin(ctx: commands.Context, user_id: str):
    """
    Demote an admin to regular user.
    Usage: ~removeadmin <user_id>
    Example: ~removeadmin 123456789
    """
    if not user_id.isdigit():
        await ctx.send(embed=discord.Embed(title="Error", description="Invalid user ID. Please provide a valid Discord user ID.", color=discord.Color.red()))
        return

    async with db_pool.acquire() as conn:
        try:
            result = await conn.execute("UPDATE whitelist SET role = ? WHERE user_id = ? AND role = ?", (UserRole.USER.value, user_id, UserRole.ADMIN.value))
            await conn.commit()
            if result.rowcount == 0:
                await ctx.send(embed=discord.Embed(title="Admin Removal", description=f"User {user_id} was not an admin or not in the whitelist.", color=discord.Color.yellow()))
            else:
                await ctx.send(embed=discord.Embed(title="Admin Removed", description=f"User {user_id} demoted to regular user.", color=discord.Color.green()))
        except Exception as e:
            error_message = f"Database error in remove_admin: {str(e)}"
            logger.error(error_message)
            await report_error(error_message)
            await ctx.send(embed=discord.Embed(title="Error", description="An error occurred while demoting the admin. Please try again later.", color=discord.Color.red()))

@bot.command(name='setlogchannel')
@is_whitelisted(UserRole.ADMIN)
async def set_log_channel(ctx: commands.Context, channel_id: str):
    """
    Set the channel for logging bot activities.
    Usage: ~setlogchannel <channel_id>
    Example: ~setlogchannel 123456789
    """
    if not channel_id.isdigit():
        await ctx.send(embed=discord.Embed(title="Error", description="Invalid channel ID. Please provide a valid Discord channel ID.", color=discord.Color.red()))
        return

    try:
        channel = bot.get_channel(int(channel_id))
        if channel is None:
            await ctx.send(embed=discord.Embed(title="Error", description="Channel not found. Make sure the bot has access to the specified channel.", color=discord.Color.red()))
            return

        await update_config('log_channel', channel_id)
        await ctx.send(embed=discord.Embed(title="Log Channel Set", description=f"Log channel set to {channel.name} ({channel_id})", color=discord.Color.green()))
    except Exception as e:
        error_message = f"Error in set_log_channel: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="An error occurred while setting the log channel. Please try again later.", color=discord.Color.red()))

@bot.command(name='reload')
@is_whitelisted(UserRole.ADMIN)
async def reload_bot(ctx: commands.Context):
    """
    Reload the bot (owner only).
    Usage: ~reload
    """
    await ctx.send(embed=discord.Embed(title="Reloading", description="Reloading the bot...", color=discord.Color.blue()))
    try:
        await bot.close()
        os.execv(sys.executable, ['python'] + sys.argv)
    except Exception as e:
        error_message = f"Error in reload_bot: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="An error occurred while reloading the bot. Please check the logs and try again.", color=discord.Color.red()))

@bot.command(name='reindex')
@is_whitelisted(UserRole.ADMIN)
async def reindex_repo(ctx: commands.Context):
    """
    Force reindexing of the current repository.
    Usage: ~reindex
    """
    repos = await get_repos()
    if not repos:
        await ctx.send(embed=discord.Embed(title="Error", description="No repository is currently indexed.", color=discord.Color.red()))
        return

    if len(repos) > 1:
        await ctx.send(embed=discord.Embed(title="Error", description="Multiple repositories found. Please remove all but one before reindexing.", color=discord.Color.red()))
        return

    repo = repos[0]
    await ctx.send(embed=discord.Embed(title="Reindexing", description="Starting reindexing process...", color=discord.Color.blue()))
    await index_repository(ctx, repo)

@bot.command(name='repostatus')
@is_whitelisted(UserRole.USER)
async def repo_status(ctx: commands.Context):
    """
    View the current status of the indexed repository.
    Usage: ~repostatus
    """
    try:
        repos = await get_repos()
        if not repos:
            await ctx.send(embed=discord.Embed(title="Repository Status", description="No repository is currently indexed.", color=discord.Color.red()))
            return

        if len(repos) > 1:
            await ctx.send(embed=discord.Embed(title="Error", description="Multiple repositories found. Please contact an admin to resolve this issue.", color=discord.Color.red()))
            return

        repo = repos[0]
        status = await get_repository_status(repo)
        
        remote, owner, name, branch = repo
        embed = discord.Embed(title="Repository Status", color=discord.Color.blue())
        embed.add_field(name="Repository", value=f"{owner}/{name}", inline=False)
        embed.add_field(name="Remote", value=remote, inline=True)
        embed.add_field(name="Branch", value=branch, inline=True)
        embed.add_field(name="Status", value=status or "Unknown", inline=False)
        
        await ctx.send(embed=embed)
    except Exception as e:
        error_message = f"Unexpected error in repo_status: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="An unexpected error occurred while fetching repository status. Please try again later.", color=discord.Color.red()))

@bot.command(name='seterrorchannel')
@is_whitelisted(UserRole.ADMIN)
async def set_error_channel(ctx: commands.Context, channel_id: str):
    """
    Set the channel for error reporting.
    Usage: ~seterrorchannel <channel_id>
    Example: ~seterrorchannel 123456789
    """
    if not channel_id.isdigit():
        await ctx.send(embed=discord.Embed(title="Error", description="Invalid channel ID. Please provide a valid Discord channel ID.", color=discord.Color.red()))
        return

    try:
        channel = bot.get_channel(int(channel_id))
        if channel is None:
            await ctx.send(embed=discord.Embed(title="Error", description="Channel not found. Make sure the bot has access to the specified channel.", color=discord.Color.red()))
            return

        await update_config('error_channel', channel_id)
        await ctx.send(embed=discord.Embed(title="Error Channel Set", description=f"Error channel set to {channel.name} ({channel_id})", color=discord.Color.green()))
    except Exception as e:
        error_message = f"Error in set_error_channel: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="An error occurred while setting the error channel. Please try again later.", color=discord.Color.red()))

@bot.command(name='testerror')
@is_whitelisted(UserRole.ADMIN)
async def test_error(ctx: commands.Context):
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
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Test Error", description="A test error has been generated and reported.", color=discord.Color.orange()))

@bot.command(name='viewconfig')
@is_whitelisted(UserRole.ADMIN)
async def view_config(ctx: commands.Context):
    """
    View the current bot configuration.
    Usage: ~viewconfig
    """
    try:
        config_str = "\n".join([f"{k}: {v}" for k, v in CONFIG.items()])
        await ctx.send(embed=discord.Embed(title="Current Configuration", description=config_str, color=discord.Color.blue()))
    except Exception as e:
        error_message = f"Error in view_config: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="An error occurred while retrieving the configuration. Please try again later.", color=discord.Color.red()))

# Error handling
@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(embed=discord.Embed(title="Error", description="Command not found. Use `~greptilehelp` to see available commands.", color=discord.Color.red()))
    elif isinstance(error, commands.CheckFailure):
        await ctx.send(embed=discord.Embed(title="Error", description="You don't have permission to use this command.", color=discord.Color.red()))
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send(embed=discord.Embed(title="Error", description=f"Missing required argument: {error.param.name}", color=discord.Color.red()))
    else:
        error_message = f"An unexpected error occurred: {str(error)}\n\nTraceback:\n{''.join(traceback.format_tb(error.__traceback__))}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="An unexpected error occurred. The bot owner has been notified.", color=discord.Color.red()))

@bot.event
async def on_ready():
    global CONFIG
    print(f'{bot.user} has connected to Discord!')
    CONFIG = await load_db_config()
    check_repo_status.start()

@tasks.loop(minutes=30)
async def check_repo_status():
    repos = await get_repos()
    if not repos:
        return  # Don't check if there are no repos

    for repo in repos:
        status = await get_repository_status(repo)
        logger.info(f"Repository {repo[1]}/{repo[2]} status: {status}")

async def setup_bot():
    """Perform initial bot setup."""
    global CONFIG
    
    await db_pool.init()
    
    async with db_pool.acquire() as conn:
        # Create tables if they don't exist
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS whitelist (
                user_id TEXT PRIMARY KEY,
                role TEXT
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS repos (
                id INTEGER PRIMARY KEY,
                remote TEXT,
                owner TEXT,
                name TEXT,
                branch TEXT
            )
        ''')
        await conn.execute('''
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        
        # Ensure the bot owner is in the whitelist as an owner
        await conn.execute("INSERT OR REPLACE INTO whitelist (user_id, role) VALUES (?, ?)", (BOT_OWNER_ID, UserRole.OWNER.value))
        
        # Set up default configuration
        default_config = {
            'MAX_QUERIES_PER_DAY': str(config.get('MAX_QUERIES_PER_DAY', 5)),
            'MAX_SMART_QUERIES_PER_DAY': str(config.get('MAX_SMART_QUERIES_PER_DAY', 1)),
            'BOT_PERMISSIONS': str(config.get('BOT_PERMISSIONS', 8))
        }
        
        for key, value in default_config.items():
            await conn.execute("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", (key, value))
        
        await conn.commit()
    
    CONFIG = await load_db_config()

# Initialize the static variables
report_error.last_error_time = None
report_error.last_error_message = None

if __name__ == "__main__":
    asyncio.run(setup_bot())
    bot.run(TOKEN)
