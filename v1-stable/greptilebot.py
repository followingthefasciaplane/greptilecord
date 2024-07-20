import os
import sys
from typing import Optional, List, Dict, Any, Tuple, Union
import discord
from discord.ext import commands, tasks
from discord.ui import View, Button
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
import time
from collections import defaultdict
import traceback
from aiohttp import ClientResponseError, ServerDisconnectedError
from contextlib import asynccontextmanager
import functools
from tenacity import retry, stop_after_attempt, wait_exponential

# Enhanced logging setup
logging.basicConfig(
    filename='bot.log',
    level=logging.DEBUG,
    format='%(asctime)s:%(levelname)s:%(message)s'
)
logger = logging.getLogger(__name__)

active_queries = set()
last_query_time = defaultdict(float)
COOLDOWN_TIME = 5  # 5 seconds cooldown

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

MAX_EMBED_DESCRIPTION_LENGTH = 4096
MAX_EMBED_FIELD_VALUE_LENGTH = 1024

def load_secrets():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    secrets_path = os.path.join(script_dir, 'secrets.yaml')
    
    try:
        with open(secrets_path, 'r') as secrets_file:
            secrets = yaml.safe_load(secrets_file)
        
        required_keys = ['DISCORD_BOT_TOKEN', 'GREPTILE_API_KEY', 'GITHUB_TOKEN', 'BOT_OWNER_ID']
        for key in required_keys:
            if key not in secrets:
                raise KeyError(f"Missing required key: {key}")
        
        return secrets
    except FileNotFoundError:
        print(f"Error: secrets.yaml file not found at {secrets_path}")
        print("Please ensure the secrets.yaml file is in the same directory as the script.")
        sys.exit(1)
    except yaml.YAMLError as e:
        print(f"Error parsing secrets.yaml: {e}")
        sys.exit(1)
    except KeyError as e:
        print(f"Error: {e}")
        print("Please ensure all required keys are present in your secrets.yaml file.")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected error when loading secrets.yaml: {e}")
        sys.exit(1)

# Load tokens and API keys
try:
    secrets = load_secrets()
    TOKEN = secrets['DISCORD_BOT_TOKEN']
    GREPTILE_API_KEY = secrets['GREPTILE_API_KEY']
    GITHUB_TOKEN = secrets['GITHUB_TOKEN']
    BOT_OWNER_ID = secrets['BOT_OWNER_ID']
except Exception as e:
    print(f"Error setting up configuration: {e}")
    sys.exit(1)

# Initialize bot with all intents
intents = discord.Intents.all()
bot = commands.Bot(command_prefix=lambda _, __: CONFIG.get('BOT_PREFIX', '~'), intents=intents)

bot.remove_command('help')

# Enums
class RepoRemote(Enum):
    GITHUB = "github"
    GITLAB = "gitlab"

class UserRole(Enum):
    USER = "user"
    ADMIN = "admin"
    OWNER = "owner"

@asynccontextmanager
async def db_transaction():
    async with db_pool.acquire() as conn:
        async with conn.cursor() as cur:
            try:
                await conn.execute("BEGIN")
                yield cur
                await conn.commit()
            except Exception:
                await conn.rollback()
                raise

async def load_db_config():
    try:
        async with db_pool.acquire() as conn:
            async with conn.execute("SELECT key, value FROM config") as cursor:
                return {row[0]: row[1] for row in await cursor.fetchall()}
    except sqlite3.Error as e:
        error_message = f"Database error in load_db_config: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        return {}
    except Exception as e:
        error_message = f"Unexpected error in load_db_config: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        return {}

CONFIG = {}

# Track user queries
user_queries = defaultdict(lambda: defaultdict(list))

# Helper functions
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
async def make_api_call(session, url, payload, headers):
    logger.info(f"Sending request to {url}")
    logger.info(f"Request payload: {json.dumps(payload, indent=2)}")
    logger.info(f"Request headers: {json.dumps(headers, indent=2)}")

    async with session.post(url, json=payload, headers=headers) as response:
        logger.info(f"Response status: {response.status}")
        logger.info(f"Response headers: {json.dumps(dict(response.headers), indent=2)}")
        response_text = await response.text()
        logger.info(f"Response body: {response_text}")
        response.raise_for_status()
        return json.loads(response_text)

async def handle_api_error(ctx, message, e):
    if isinstance(e, aiohttp.ClientResponseError):
        error_message = f"HTTP error: {e.status} - {e.message}"
        user_message = f"An error occurred while processing your request. Status: {e.status}. Message: {e.message}"
    elif isinstance(e, aiohttp.ServerDisconnectedError):
        error_message = "Server disconnected during operation"
        user_message = "The server disconnected while processing your request. Please try again later."
    elif isinstance(e, aiohttp.ClientError):
        error_message = f"Client error: {str(e)}"
        user_message = f"An error occurred while processing your request: {str(e)}"
    else:
        error_message = f"Unexpected error: {str(e)}"
        user_message = f"An unexpected error occurred: {str(e)}"

    logger.error(error_message)
    await report_error(error_message)
    await message.edit(embed=discord.Embed(title="Error", description=user_message, color=discord.Color.red()))
    
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
    try:
        async with db_transaction() as cur:
            await cur.execute("INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)", (key, value))
        CONFIG[key] = value
    except sqlite3.Error as e:
        error_message = f"Database error in update_config: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        raise
    except Exception as e:
        error_message = f"Unexpected error in update_config: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        raise

async def get_repos() -> List[Tuple[str, str, str, str]]:
    try:
        async with db_pool.acquire() as conn:
            async with conn.execute("SELECT remote, owner, name, branch FROM repos") as cursor:
                return await cursor.fetchall()
    except sqlite3.Error as e:
        error_message = f"Database error in get_repos: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        return []
    except Exception as e:
        error_message = f"Unexpected error in get_repos: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        return []

async def can_make_query(user_id: int, query_type: str) -> bool:
    if str(user_id) == BOT_OWNER_ID:
        return True
    today = datetime.now().date()
    user_queries[user_id][query_type] = [date for date in user_queries[user_id][query_type] if date.date() == today]
    max_queries = int(CONFIG.get(f'MAX_{query_type.upper()}_QUERIES_PER_DAY', 5))
    return len(user_queries[user_id][query_type]) < max_queries

async def get_repository_status(repo: Tuple[str, str, str, str], max_retries: int = 3) -> Optional[str]:
    remote, owner, name, branch = repo
    repo_id = f"{remote}:{branch}:{owner}/{name}"
    encoded_repo_id = urllib.parse.quote(repo_id, safe='')
    url = f'https://api.greptile.com/v2/repositories/{encoded_repo_id}'
    
    headers = {
        'Authorization': f'Bearer {GREPTILE_API_KEY}',
        'X-GitHub-Token': GITHUB_TOKEN
    }

    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    response.raise_for_status()
                    repo_info = await response.json()
                    logger.info(f"Repository info retrieved successfully: {repo_info}")
                    return repo_info.get('status', 'Unknown')
        except ServerDisconnectedError:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # exponential backoff
                logger.warning(f"Server disconnected. Retrying in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
            else:
                logger.error("Server disconnected after max retries")
                await report_error("Server disconnected in get_repository_status after max retries")
                return "Error: Server disconnected"
        except aiohttp.ClientResponseError as e:
            logger.error(f"HTTP error occurred while checking repository status: {e.status} - {e.message}")
            await report_error(f"HTTP error in get_repository_status: {e.status} - {e.message}")
            return f"Error: {e.status}"
        except aiohttp.ClientError as e:
            logger.error(f"An error occurred while checking repository status: {str(e)}")
            logger.error(f"URL attempted: {url}")
            await report_error(f"Client error in get_repository_status: {str(e)}")
            return "Error: Unable to connect"
        except Exception as e:
            logger.error(f"Unexpected error in get_repository_status: {str(e)}")
            await report_error(f"Unexpected error in get_repository_status: {str(e)}")
            return "Error: Unexpected issue"

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
    current_status_info = await get_repository_status(ctx, repo)
    
    if current_status_info is None:
        await ctx.send(embed=discord.Embed(title="Error", description="Failed to retrieve repository status. Please try again later.", color=discord.Color.red()))
        return 'failed'

    current_status = current_status_info['status']
    
    if current_status == 'completed':
        # No need to send another embed, as get_repository_status already sent one
        return 'completed'
    elif current_status == 'processing':
        # No need to send another embed, as get_repository_status already sent one
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
        "reload": True,
        "notify": False
    }

    status_embed = discord.Embed(title="Repository Indexing", description="Starting indexing process...", color=discord.Color.blue())
    status_message = await ctx.send(embed=status_embed)

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=CONFIG['API_TIMEOUT'])) as session:
        for attempt in range(CONFIG['API_RETRIES']):
            try:
                async with session.post(url, json=payload, headers=headers) as response:
                    response.raise_for_status()
                    result = await response.json()
                    logger.info(f"Repository indexing response: {result['response']}")
                    
                    status_embed.description = f"Indexing started: {result['response']}"
                    await status_message.edit(embed=status_embed)

                    # Start checking the indexing status
                    return await check_indexing_status(ctx, status_message, repo)

            except aiohttp.ClientResponseError as e:
                error_context = {
                    "status_code": e.status,
                    "request_info": str(e.request_info),
                    "headers": str(e.headers),
                }
                error_message = f"HTTP error occurred while indexing the repository: {e.status} - {e.message}"
                logger.error(error_message)
                logger.error(f"URL attempted: {url}")
                logger.error(f"Payload: {payload}")
                await report_error(error_message, error_context)
                
                if attempt == CONFIG['API_RETRIES'] - 1:
                    status_embed.description = f"Failed to start indexing. HTTP Error: {e.status} - {e.message}"
                    status_embed.color = discord.Color.red()
                    await status_message.edit(embed=status_embed)
                    return 'failed'
                
                await asyncio.sleep(2 ** attempt)  # Exponential backoff

            except aiohttp.ClientError as e:
                error_message = f"Client error occurred while indexing the repository: {str(e)}"
                logger.error(error_message)
                logger.error(f"URL attempted: {url}")
                logger.error(f"Payload: {payload}")
                await report_error(error_message)
                
                if attempt == CONFIG['API_RETRIES'] - 1:
                    status_embed.description = f"Failed to start indexing. Client Error: {str(e)}"
                    status_embed.color = discord.Color.red()
                    await status_message.edit(embed=status_embed)
                    return 'failed'
                
                await asyncio.sleep(2 ** attempt)  # Exponential backoff

            except Exception as e:
                error_message = f"Unexpected error occurred while indexing the repository: {str(e)}"
                logger.error(error_message)
                logger.error(f"URL attempted: {url}")
                logger.error(f"Payload: {payload}")
                await report_error(error_message)
                
                status_embed.description = f"Failed to start indexing. Unexpected Error: {str(e)}"
                status_embed.color = discord.Color.red()
                await status_message.edit(embed=status_embed)
                return 'failed'

async def check_indexing_status(ctx: commands.Context, status_message: discord.Message, repo: Tuple[str, str, str, str]) -> str:
    remote, owner, name, branch = repo
    repo_id = f"{remote}:{branch}:{owner}/{name}"

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=CONFIG['API_TIMEOUT'])) as session:
        start_time = datetime.now()
        while True:
            try:
                status_info = await get_repository_status(ctx, repo)
                
                if status_info is None:
                    status_embed = discord.Embed(title="Error", description="Failed to retrieve repository status. Please check manually.", color=discord.Color.red())
                    await status_message.edit(embed=status_embed)
                    return 'failed'

                status = status_info['status']
                status_embed = status_message.embeds[0]
                
                if status == 'completed':
                    status_embed.description = "Repository indexing completed successfully."
                    status_embed.color = discord.Color.green()
                    await status_message.edit(embed=status_embed)
                    return 'completed'
                elif status == 'failed':
                    status_embed.description = "Repository indexing failed."
                    status_embed.color = discord.Color.red()
                    await status_message.edit(embed=status_embed)
                    return 'failed'
                elif status in ['submitted', 'cloning', 'processing']:
                    elapsed_time = (datetime.now() - start_time).total_seconds() / 60  # in minutes
                    progress = status_info['filesProcessed'] / max(status_info['numFiles'], 1) * 100
                    
                    status_descriptions = {
                        'submitted': "Repository has been submitted for indexing.",
                        'cloning': "Repository is being cloned.",
                        'processing': "Repository is being processed and indexed."
                    }
                    
                    status_embed.description = (
                        f"{status_descriptions[status]}\n"
                        f"Status: {status.capitalize()}\n"
                        f"Progress: {progress:.2f}%\n"
                        f"Elapsed time: {elapsed_time:.2f} minutes"
                    )
                    status_embed.color = discord.Color.blue()
                    status_embed.set_footer(text="This progress is based on the number of files processed.")
                    await status_message.edit(embed=status_embed)
                else:
                    logger.warning(f"Unknown repository status: {status}")
                    status_embed.description = f"Unexpected status: {status}. Please check manually."
                    status_embed.color = discord.Color.orange()
                    await status_message.edit(embed=status_embed)
                
                await asyncio.sleep(60)  # Check every minute

            except Exception as e:
                error_message = f"Unexpected error occurred while checking repository status: {str(e)}"
                logger.error(error_message)
                await report_error(error_message)
                return 'failed'

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
    query_id = f"{ctx.author.id}-{ctx.channel.id}"

    if query_id in active_queries:
        await ctx.send(embed=discord.Embed(title="Error", description="You already have a pending search. Please wait for it to complete.", color=discord.Color.red()))
        return

    current_time = time.time()
    if current_time - last_query_time[ctx.author.id] < COOLDOWN_TIME:
        cooldown_left = COOLDOWN_TIME - (current_time - last_query_time[ctx.author.id])
        await ctx.send(embed=discord.Embed(title="Cooldown", description=f"Please wait {cooldown_left:.1f} seconds before making another search.", color=discord.Color.orange()))
        return

    if not await can_make_query(ctx.author.id, 'search'):
        await ctx.send(embed=discord.Embed(title="Error", description="You have reached the maximum number of searches for today.", color=discord.Color.red()))
        return

    active_queries.add(query_id)
    last_query_time[ctx.author.id] = current_time

    # Send initial response
    initial_embed = discord.Embed(title="Processing Search", description="Your search query is being processed. Please wait...", color=discord.Color.blue())
    message = await ctx.send(embed=initial_embed)

    try:
        repos = await get_repos()
        if not repos:
            await message.edit(embed=discord.Embed(title="Error", description="No repositories indexed. Please add a repository first.", color=discord.Color.red()))
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
            start_time = datetime.now()
            results = await make_api_call(session, url, payload, headers)
            end_time = datetime.now()
            response_time = (end_time - start_time).total_seconds()

            if not results:
                await message.edit(embed=discord.Embed(title="Search Results", description="No results found for your query.", color=discord.Color.blue()))
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

            await message.edit(embed=embeds[0])
            for embed in embeds[1:]:
                await ctx.send(embed=embed)

            user_queries[ctx.author.id]['search'].append(datetime.now())
            await log_to_channel(ctx.guild.id, embeds[0])

    except Exception as e:
        await handle_api_error(ctx, message, e)
    finally:
        active_queries.remove(query_id)

class PaginationView(View):
    def __init__(self, embeds):
        super().__init__(timeout=300)
        self.embeds = embeds
        self.current_page = 0

    @discord.ui.button(label="Previous", style=discord.ButtonStyle.grey)
    async def previous_button(self, interaction: discord.Interaction, button: Button):
        if self.current_page > 0:
            self.current_page -= 1
            await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.grey)
    async def next_button(self, interaction: discord.Interaction, button: Button):
        if self.current_page < len(self.embeds) - 1:
            self.current_page += 1
            await interaction.response.edit_message(embed=self.embeds[self.current_page], view=self)

def split_text(text, max_length):
    """Split text into chunks of maximum length."""
    return [text[i:i+max_length] for i in range(0, len(text), max_length)]
        
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
    Process a query to the Greptile API with pagination for long responses.
    """
    query_type = 'smart_queries' if genius else 'queries'
    query_id = f"{ctx.author.id}-{ctx.channel.id}"

    # Check for concurrent queries
    if query_id in active_queries:
        await ctx.send(embed=discord.Embed(title="Error", description="You already have a pending query. Please wait for it to complete.", color=discord.Color.red()))
        return

    # Check for cooldown
    current_time = time.time()
    if current_time - last_query_time[ctx.author.id] < COOLDOWN_TIME:
        cooldown_left = COOLDOWN_TIME - (current_time - last_query_time[ctx.author.id])
        await ctx.send(embed=discord.Embed(title="Cooldown", description=f"Please wait {cooldown_left:.1f} seconds before making another query.", color=discord.Color.orange()))
        return

    # Check daily limit
    if not await can_make_query(ctx.author.id, query_type):
        await ctx.send(embed=discord.Embed(title="Error", description=f"You have reached the maximum number of {'smart ' if genius else ''}queries for today.", color=discord.Color.red()))
        return

    active_queries.add(query_id)
    last_query_time[ctx.author.id] = current_time

    # Send initial response
    initial_embed = discord.Embed(title="Processing Query", description="Your query is being processed. Please wait...", color=discord.Color.blue())
    message = await ctx.send(embed=initial_embed)

    try:
        repos = await get_repos()
        if not repos:
            await message.edit(embed=discord.Embed(title="Error", description="No repositories indexed. Please add a repository first.", color=discord.Color.red()))
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
            start_time = datetime.now()
            result = await make_api_call(session, url, payload, headers)
            end_time = datetime.now()
            response_time = (end_time - start_time).total_seconds()

            # Split the response into multiple embeds if necessary
            embeds = []
            chunks = split_text(result['message'], MAX_EMBED_DESCRIPTION_LENGTH)
            
            for i, chunk in enumerate(chunks):
                embed = discord.Embed(title=f"Query Result (Page {i+1}/{len(chunks)})", description=chunk, color=discord.Color.green())
                if i == len(chunks) - 1:  # Add sources and response time to the last embed
                    if 'sources' in result:
                        sources = result['sources']
                        source_chunks = []
                        current_chunk = ""
                        for source in sources:
                            source_text = f"- {source['filepath']} (lines {source['linestart']}-{source['lineend']})\n"
                            if len(current_chunk) + len(source_text) > MAX_EMBED_FIELD_VALUE_LENGTH:
                                source_chunks.append(current_chunk)
                                current_chunk = source_text
                            else:
                                current_chunk += source_text
                        if current_chunk:
                            source_chunks.append(current_chunk)
                        
                        for j, source_chunk in enumerate(source_chunks):
                            embed.add_field(name=f"Sources (Page {j+1}/{len(source_chunks)})", value=source_chunk, inline=False)

                    embed.add_field(name="Response Time", value=f"{response_time:.2f} seconds", inline=False)
                embeds.append(embed)

            # Send the first embed with pagination view
            view = PaginationView(embeds)
            await message.edit(embed=embeds[0], view=view)

            await log_to_channel(ctx.guild.id, embeds[0])

            user_queries[ctx.author.id][query_type].append(datetime.now())

    except Exception as e:
        await handle_api_error(ctx, message, e)
    finally:
        active_queries.remove(query_id)

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
async def add_repo(ctx: commands.Context, remote: str, repository: str, branch: str = None):
    """
    Add and index a new repository.
    Usage: ~addrepo <remote> <owner/name> [branch]
    Example: ~addrepo github openai/gpt-3 main
    """
    try:
        owner, name = repository.split('/')
    except ValueError:
        await ctx.send(embed=discord.Embed(title="Error", description="Invalid repository format. Use 'owner/name'.", color=discord.Color.red()))
        return

    if branch is None:
        branch = CONFIG.get('DEFAULT_BRANCH', 'main')

    try:
        async with db_transaction() as cur:
            # Check if the repository already exists
            await cur.execute("SELECT * FROM repos WHERE remote=? AND owner=? AND name=? AND branch=?", (remote, owner, name, branch))
            if await cur.fetchone():
                await ctx.send(embed=discord.Embed(title="Error", description="This repository is already indexed.", color=discord.Color.red()))
                return

            # Add the repository to the database
            await cur.execute("INSERT INTO repos (remote, owner, name, branch) VALUES (?, ?, ?, ?)",
                            (remote, owner, name, branch))

        await ctx.send(embed=discord.Embed(title="Repository Added", description="Repository has been added to the database. Starting indexing process...", color=discord.Color.green()))
        
        # Start indexing process
        status = await index_repository(ctx, (remote, owner, name, branch))

        # Check the indexing result
        if status != 'completed':
            # If indexing failed, remove the repository from the database
            async with db_transaction() as cur:
                await cur.execute("DELETE FROM repos WHERE remote=? AND owner=? AND name=? AND branch=?", (remote, owner, name, branch))
            await ctx.send(embed=discord.Embed(title="Repository Removed", description="Repository indexing failed and has been removed from the database.", color=discord.Color.red()))
        else:
            await ctx.send(embed=discord.Embed(title="Repository Indexed", description="Repository has been successfully indexed and is ready for use.", color=discord.Color.green()))

    except sqlite3.Error as e:
        error_message = f"Database error in add_repo: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="A database error occurred. Please try again later.", color=discord.Color.red()))
    except Exception as e:
        error_message = f"Unexpected error in add_repo: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="An unexpected error occurred. Please try again later.", color=discord.Color.red()))

@bot.command(name='removerepos')
@is_whitelisted(UserRole.ADMIN)
async def remove_repos(ctx: commands.Context):
    """
    Remove all indexed repositories.
    Usage: ~removerepos
    """
    try:
        async with db_transaction() as cur:
            await cur.execute("DELETE FROM repos")
        await ctx.send(embed=discord.Embed(title="Repositories Removed", description="All repositories have been removed from the index.", color=discord.Color.green()))
    except sqlite3.Error as e:
        error_message = f"Database error in remove_repos: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="A database error occurred while removing repositories. Please try again later.", color=discord.Color.red()))
    except Exception as e:
        error_message = f"Unexpected error in remove_repos: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="An unexpected error occurred while removing repositories. Please try again later.", color=discord.Color.red()))

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
    try:
        async with db_pool.acquire() as conn:
            async with conn.execute("SELECT user_id, role FROM whitelist") as cursor:
                whitelist = await cursor.fetchall()
        
        embed = discord.Embed(title="Whitelisted Users", color=discord.Color.blue())
        for user_id, role in whitelist:
            embed.add_field(name=user_id, value=role, inline=False)
        
        await ctx.send(embed=embed)
    except sqlite3.Error as e:
        error_message = f"Database error in list_whitelist: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="A database error occurred while fetching the whitelist. Please try again later.", color=discord.Color.red()))
    except Exception as e:
        error_message = f"Unexpected error in list_whitelist: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="An unexpected error occurred while fetching the whitelist. Please try again later.", color=discord.Color.red()))

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

    try:
        async with db_transaction() as cur:
            await cur.execute("INSERT OR REPLACE INTO whitelist (user_id, role) VALUES (?, ?)", (user_id, UserRole.USER.value))
        await ctx.send(embed=discord.Embed(title="Whitelist Updated", description=f"User {user_id} added to whitelist.", color=discord.Color.green()))
    except sqlite3.Error as e:
        error_message = f"Database error in add_whitelist: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="A database error occurred while updating the whitelist. Please try again later.", color=discord.Color.red()))
    except Exception as e:
        error_message = f"Unexpected error in add_whitelist: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="An unexpected error occurred while updating the whitelist. Please try again later.", color=discord.Color.red()))

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

    try:
        async with db_transaction() as cur:
            result = await cur.execute("DELETE FROM whitelist WHERE user_id = ?", (user_id,))
            if result.rowcount == 0:
                await ctx.send(embed=discord.Embed(title="Whitelist Update", description=f"User {user_id} was not in the whitelist.", color=discord.Color.yellow()))
            else:
                await ctx.send(embed=discord.Embed(title="Whitelist Updated", description=f"User {user_id} removed from whitelist.", color=discord.Color.green()))
    except sqlite3.Error as e:
        error_message = f"Database error in remove_whitelist: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="A database error occurred while updating the whitelist. Please try again later.", color=discord.Color.red()))
    except Exception as e:
        error_message = f"Unexpected error in remove_whitelist: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="An unexpected error occurred while updating the whitelist. Please try again later.", color=discord.Color.red()))

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

    try:
        async with db_transaction() as cur:
            await cur.execute("INSERT OR REPLACE INTO whitelist (user_id, role) VALUES (?, ?)", (user_id, UserRole.ADMIN.value))
        await ctx.send(embed=discord.Embed(title="Admin Added", description=f"User {user_id} promoted to admin.", color=discord.Color.green()))
    except sqlite3.Error as e:
        error_message = f"Database error in add_admin: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="A database error occurred while promoting the user to admin. Please try again later.", color=discord.Color.red()))
    except Exception as e:
        error_message = f"Unexpected error in add_admin: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="An unexpected error occurred while promoting the user to admin. Please try again later.", color=discord.Color.red()))

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

    try:
        async with db_transaction() as cur:
            result = await cur.execute("UPDATE whitelist SET role = ? WHERE user_id = ? AND role = ?", (UserRole.USER.value, user_id, UserRole.ADMIN.value))
            if result.rowcount == 0:
                await ctx.send(embed=discord.Embed(title="Admin Removal", description=f"User {user_id} was not an admin or not in the whitelist.", color=discord.Color.yellow()))
            else:
                await ctx.send(embed=discord.Embed(title="Admin Removed", description=f"User {user_id} demoted to regular user.", color=discord.Color.green()))
    except sqlite3.Error as e:
        error_message = f"Database error in remove_admin: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="A database error occurred while demoting the admin. Please try again later.", color=discord.Color.red()))
    except Exception as e:
        error_message = f"Unexpected error in remove_admin: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="An unexpected error occured while demoting the admin. Please try again later.", color=discord.Color.red()))

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
    except sqlite3.Error as e:
        error_message = f"Database error in set_log_channel: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="A database error occurred while setting the log channel. Please try again later.", color=discord.Color.red()))
    except Exception as e:
        error_message = f"Unexpected error in set_log_channel: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="An unexpected error occurred while setting the log channel. Please try again later.", color=discord.Color.red()))


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
async def reindex_repo(ctx: commands.Context, repo_id: int = None):
    """
    Force reindexing of a specific repository or all repositories if no ID is provided.
    Usage: ~reindex [repo_id]
    """
    try:
        repos = await get_repos()
        if not repos:
            await ctx.send(embed=discord.Embed(title="Error", description="No repositories are currently indexed.", color=discord.Color.red()))
            return

        if repo_id is not None:
            repo = next((r for r in repos if r[0] == repo_id), None)
            if repo is None:
                await ctx.send(embed=discord.Embed(title="Error", description=f"No repository found with ID {repo_id}.", color=discord.Color.red()))
                return
            repos_to_reindex = [repo]
        else:
            repos_to_reindex = repos

        for repo in repos_to_reindex:
            remote, owner, name, branch = repo
            await ctx.send(embed=discord.Embed(title="Reindexing", description=f"Starting reindexing process for {owner}/{name}...", color=discord.Color.blue()))
            await index_repository(ctx, repo)

    except Exception as e:
        error_message = f"Unexpected error in reindex_repo: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="An unexpected error occurred while reindexing. Please try again later.", color=discord.Color.red()))


async def get_repository_status(ctx: commands.Context, repo: Tuple[str, str, str, str], max_retries: int = 3) -> Optional[Dict[str, Any]]:
    """
    Get the status and additional information of a repository from the Greptile API.

    Args:
    ctx (commands.Context): The context of the command, used for sending notifications.
    repo (Tuple[str, str, str, str]): A tuple containing (remote, owner, name, branch) of the repository.
    max_retries (int): Maximum number of retries for the API call.

    Returns:
    Optional[Dict[str, Any]]: A dictionary containing repository information, or None if an error occurred.
    """
    remote, owner, name, branch = repo
    repo_id = f"{remote}:{branch}:{owner}/{name}"
    encoded_repo_id = urllib.parse.quote(repo_id, safe='')
    url = f'https://api.greptile.com/v2/repositories/{encoded_repo_id}'
    
    headers = {
        'Authorization': f'Bearer {GREPTILE_API_KEY}',
        'X-GitHub-Token': GITHUB_TOKEN
    }

    # Notify the user that we're checking the repository status
    await ctx.send(embed=discord.Embed(title="Checking Repository Status", description=f"Fetching status for {owner}/{name}...", color=discord.Color.blue()))

    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers) as response:
                    response.raise_for_status()
                    repo_info = await response.json()
                    logger.info(f"Repository info retrieved successfully: {repo_info}")

                    # Extract relevant information
                    status = repo_info.get('status', 'Unknown')
                    files_processed = repo_info.get('filesProcessed', 0)
                    num_files = repo_info.get('numFiles', 0)
                    sample_questions = repo_info.get('sampleQuestions', [])
                    sha = repo_info.get('sha', 'N/A')

                    # Create a dictionary with the extracted information
                    result = {
                        'status': status,
                        'filesProcessed': files_processed,
                        'numFiles': num_files,
                        'sampleQuestions': sample_questions,
                        'sha': sha
                    }

                    # Notify the user about the retrieved status
                    status_color = discord.Color.green() if status == 'completed' else discord.Color.orange()
                    status_embed = discord.Embed(title="Repository Status", color=status_color)
                    status_embed.add_field(name="Repository", value=f"{owner}/{name}", inline=False)
                    status_embed.add_field(name="Status", value=status, inline=True)
                    status_embed.add_field(name="Files Processed", value=f"{files_processed}/{num_files}", inline=True)
                    status_embed.add_field(name="SHA", value=sha, inline=True)
                    if sample_questions:
                        status_embed.add_field(name="Sample Questions", value="\n".join(sample_questions[:3]), inline=False)
                    
                    await ctx.send(embed=status_embed)

                    return result

        except aiohttp.ServerDisconnectedError:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt  # exponential backoff
                logger.warning(f"Server disconnected. Retrying in {wait_time} seconds...")
                await asyncio.sleep(wait_time)
            else:
                logger.error("Server disconnected after max retries")
                await report_error("Server disconnected in get_repository_status after max retries")
                await ctx.send(embed=discord.Embed(title="Error", description="Failed to retrieve repository status due to server disconnection.", color=discord.Color.red()))
                return None

        except aiohttp.ClientResponseError as e:
            logger.error(f"HTTP error occurred while checking repository status: {e.status} - {e.message}")
            await report_error(f"HTTP error in get_repository_status: {e.status} - {e.message}")
            await ctx.send(embed=discord.Embed(title="Error", description=f"Failed to retrieve repository status. HTTP Error: {e.status}", color=discord.Color.red()))
            return None

        except aiohttp.ClientError as e:
            logger.error(f"An error occurred while checking repository status: {str(e)}")
            logger.error(f"URL attempted: {url}")
            await report_error(f"Client error in get_repository_status: {str(e)}")
            await ctx.send(embed=discord.Embed(title="Error", description="Failed to retrieve repository status due to a client error.", color=discord.Color.red()))
            return None

        except Exception as e:
            logger.error(f"Unexpected error in get_repository_status: {str(e)}")
            await report_error(f"Unexpected error in get_repository_status: {str(e)}")
            await ctx.send(embed=discord.Embed(title="Error", description="An unexpected error occurred while retrieving repository status.", color=discord.Color.red()))
            return None

@bot.command(name='repostatus')
@is_whitelisted(UserRole.USER)
async def repo_status(ctx: commands.Context):
    """
    View the current status of the indexed repositories.
    Usage: ~repostatus
    """
    try:
        repos = await get_repos()
        if not repos:
            await ctx.send(embed=discord.Embed(title="Repository Status", description="No repositories are currently indexed.", color=discord.Color.red()))
            return

        status_embed = discord.Embed(title="Repository Status", color=discord.Color.blue())

        for repo in repos:
            remote, owner, name, branch = repo
            repo_id = f"{remote}:{branch}:{owner}/{name}"
            
            status_info = await get_repository_status(ctx, repo)
            
            if status_info is None:
                status_embed.add_field(
                    name=f"{owner}/{name}",
                    value="Failed to retrieve status",
                    inline=False
                )
                continue

            status = status_info['status']
            files_processed = status_info['filesProcessed']
            num_files = status_info['numFiles']
            sha = status_info['sha']
            
            status_embed.add_field(
                name=f"{owner}/{name}",
                value=f"Remote: {remote}\n"
                    f"Branch: {branch}\n"
                    f"Status: {status}\n"
                    f"Files Processed: {files_processed}/{num_files}\n"
                    f"SHA: {sha}",
                inline=False
            )
        
        await ctx.send(embed=status_embed)
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
    except sqlite3.Error as e:
        error_message = f"Database error in set_error_channel: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="A database error occurred while setting the error channel. Please try again later.", color=discord.Color.red()))
    except Exception as e:
        error_message = f"Unexpected error in set_error_channel: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="An unexpected error occurred while setting the error channel. Please try again later.", color=discord.Color.red()))

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
        async with db_pool.acquire() as conn:
            async with conn.execute("SELECT key, value FROM config") as cursor:
                config_items = await cursor.fetchall()
        
        config_str = "\n".join([f"{k}: {v}" for k, v in config_items])
        await ctx.send(embed=discord.Embed(title="Current Configuration", description=config_str, color=discord.Color.blue()))
    except sqlite3.Error as e:
        error_message = f"Database error in view_config: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="A database error occurred while retrieving the configuration. Please try again later.", color=discord.Color.red()))
    except Exception as e:
        error_message = f"Unexpected error in view_config: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
        await ctx.send(embed=discord.Embed(title="Error", description="An unexpected error occurred while retrieving the configuration. Please try again later.", color=discord.Color.red()))

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
    logger.info("Starting repository status check cycle")
    try:
        repos = await get_repos()
        if not repos:
            logger.info("No repositories found to check.")
            return

        logger.info(f"Checking status for {len(repos)} repositories")

        class MockContext:
            async def send(self, embed):
                # Log the embed content instead of sending to a Discord channel
                logger.info(f"Repository status update: {embed.to_dict()}")

        mock_ctx = MockContext()

        for repo in repos:
            try:
                remote, owner, name, branch = repo
                repo_id = f"{remote}:{branch}:{owner}/{name}"
                logger.info(f"Checking status for repository: {repo_id}")
                
                status_info = await get_repository_status(mock_ctx, repo)
                
                if status_info is None:
                    logger.error(f"Failed to retrieve status for repository {repo_id}")
                    continue

                status = status_info['status']
                files_processed = status_info['filesProcessed']
                num_files = status_info['numFiles']

                logger.info(f"Repository {repo_id} status: {status}, Files processed: {files_processed}/{num_files}")

                if status == 'failed':
                    error_message = f"Repository {repo_id} indexing has failed."
                    logger.error(error_message)
                    await report_error(error_message)
                elif status == 'processing':
                    logger.warning(f"Repository {repo_id} is still processing. This may need attention.")
                elif status not in ['completed', 'submitted', 'cloning']:
                    logger.info(f"Repository {repo_id} has unexpected status: {status}")

            except Exception as e:
                error_message = f"Unexpected error checking status for repo {repo_id}: {str(e)}"
                logger.error(error_message)
                await report_error(error_message)

    except Exception as e:
        error_message = f"Unexpected error in check_repo_status: {str(e)}"
        logger.error(error_message)
        await report_error(error_message)
    
    logger.info("Completed repository status check cycle")

@check_repo_status.before_loop
async def before_check_repo_status():
    await bot.wait_until_ready()
    logger.info("Repository status check loop is ready to start.")

@check_repo_status.after_loop
async def after_check_repo_status():
    if check_repo_status.is_being_cancelled():
        logger.warning("Repository status check loop was cancelled.")
    else:
        logger.error("Repository status check loop has stopped unexpectedly.")
        await report_error("Repository status check loop has stopped unexpectedly.")
        # Attempt to restart the task
        await asyncio.sleep(60)  # Wait for 1 minute before restarting
        check_repo_status.restart()
        logger.info("Attempting to restart check_repo_status task.")

async def setup_bot():
    """Perform initial bot setup."""
    global CONFIG
    
    await db_pool.init()
    
    try:
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
            
            default_config = {
                'MAX_QUERIES_PER_DAY': '5',
                'MAX_SMART_QUERIES_PER_DAY': '1',
                'BOT_PERMISSIONS': '8',
                'API_TIMEOUT': '60',
                'API_RETRIES': '3',
                'DEFAULT_BRANCH': 'main',
                'BOT_PREFIX': '~'
            }
            
            for key, value in default_config.items():
                await conn.execute("INSERT OR IGNORE INTO config (key, value) VALUES (?, ?)", (key, value))
            
            await conn.commit()
        
        CONFIG = await load_db_config()
    except sqlite3.Error as e:
        error_message = f"Database error in setup_bot: {str(e)}"
        logger.error(error_message)
        raise RuntimeError(f"Failed to set up the bot due to a database error: {str(e)}")
    except Exception as e:
        error_message = f"Unexpected error in setup_bot: {str(e)}"
        logger.error(error_message)
        raise RuntimeError(f"Failed to set up the bot due to an unexpected error: {str(e)}")

# Initialize the static variables
report_error.last_error_time = None
report_error.last_error_message = None

if __name__ == "__main__":
    asyncio.run(setup_bot())
    bot.run(TOKEN)
