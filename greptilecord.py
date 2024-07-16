import os
from typing import Optional, List, Dict, Any
import discord
from discord.ext import commands, tasks
import aiohttp
from datetime import datetime
from collections import defaultdict
import asyncio
import urllib.parse
import json

TOKEN = '' # Discord bot token
GREPTILE_API_KEY = '' #Greptile key
GITHUB_TOKEN = '' # Github PAT token
WHITELIST_FILE = 'whitelist.json' # Whitelisted Discord IDs
BOT_OWNER_ID = '890302656025882654' # Bypasses query limits
MAX_QUERIES_PER_DAY = 5 # Normal mode
MAX_SMART_QUERIES_PER_DAY = 1 # Genius mode

# Repository configuration
REPO_REMOTE = "github"
REPO_OWNER = "followingthefasciaplane"
REPO_NAME = "greptilecord"
REPO_BRANCH = "main"

# Discord bot permissions, admin for convenience but limit this
BOT_PERMISSIONS = discord.Permissions(8)

# Initialize bot with all intents, limit this too
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='~', intents=intents)

# Track user queries
user_queries: Dict[int, List[datetime]] = defaultdict(list)
user_smart_queries: Dict[int, List[datetime]] = defaultdict(list)

# Load whitelist from file
def load_whitelist():
    if os.path.exists(WHITELIST_FILE):
        with open(WHITELIST_FILE, 'r') as f:
            return json.load(f)
    return []

# Save whitelist to file
def save_whitelist(whitelist):
    with open(WHITELIST_FILE, 'w') as f:
        json.dump(whitelist, f)

WHITELIST = load_whitelist()

def is_whitelisted() -> commands.check:
    async def predicate(ctx: commands.Context) -> bool:
        return str(ctx.author.id) in WHITELIST or str(ctx.author.id) == BOT_OWNER_ID
    return commands.check(predicate)

def is_bot_owner() -> commands.check:
    async def predicate(ctx: commands.Context) -> bool:
        return str(ctx.author.id) == BOT_OWNER_ID
    return commands.check(predicate)

def can_make_query(user_id: int) -> bool:
    if str(user_id) == BOT_OWNER_ID:
        return True
    today = datetime.now().date()
    user_queries[user_id] = [date for date in user_queries[user_id] if date.date() == today]
    return len(user_queries[user_id]) < MAX_QUERIES_PER_DAY

def can_make_smart_query(user_id: int) -> bool:
    if str(user_id) == BOT_OWNER_ID:
        return True
    today = datetime.now().date()
    user_smart_queries[user_id] = [date for date in user_smart_queries[user_id] if date.date() == today]
    return len(user_smart_queries[user_id]) < MAX_SMART_QUERIES_PER_DAY

async def index_repository() -> None:
    current_status = await get_repository_status()
    
    if current_status == 'completed':
        print("Repository is already indexed. Skipping indexing process.")
        return
    elif current_status == 'processing':
        print("Repository is currently being processed. Waiting for completion...")
    else:
        url = 'https://api.greptile.com/v2/repositories'
        headers = {
            'Authorization': f'Bearer {GREPTILE_API_KEY}',
            'X-GitHub-Token': GITHUB_TOKEN,
            'Content-Type': 'application/json'
        }
        payload = {
            "remote": REPO_REMOTE,
            "repository": f"{REPO_OWNER}/{REPO_NAME}",
            "branch": REPO_BRANCH,
            "reload": False,
            "notify": False
        }

        async with aiohttp.ClientSession() as session:
            try:
                async with session.post(url, json=payload, headers=headers) as response:
                    response.raise_for_status()
                    result = await response.json()
                    print(f"Repository indexing response: {result['response']}")
            except aiohttp.ClientError as e:
                print(f"An error occurred while indexing the repository: {str(e)}")
                print(f"URL attempted: {url}")
                print(f"Payload: {payload}")
                return

    while True:
        status = await get_repository_status()
        if status == 'completed':
            print("Repository indexing completed.")
            break
        elif status == 'failed':
            print("Repository indexing failed.")
            break
        elif status is None:
            print("Unable to retrieve repository status. Stopping indexing check.")
            break
        print(f"Indexing status: {status}")
        await asyncio.sleep(60)  # Check every minute

async def get_repository_status() -> Optional[str]:
    repo_id = f"{REPO_REMOTE}:{REPO_BRANCH}:{REPO_OWNER}/{REPO_NAME}"
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
                print(f"Repository info retrieved successfully: {repo_info}")
                return repo_info['status']
        except aiohttp.ClientError as e:
            print(f"An error occurred while checking repository status: {str(e)}")
            print(f"URL attempted: {url}")
            return None

@bot.event
async def on_ready() -> None:
    print(f'{bot.user} has connected to Discord!')
    await index_repository()

async def process_query(ctx: commands.Context, question: str, genius: bool) -> None:
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
                "remote": REPO_REMOTE,
                "repository": f"{REPO_OWNER}/{REPO_NAME}",
                "branch": REPO_BRANCH
            }
        ],
        "sessionId": f"discord-query-{ctx.author.id}-{ctx.message.id}",
        "stream": False,
        "genius": genius
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload, headers=headers) as response:
                response.raise_for_status()
                result = await response.json()

            embed = discord.Embed(title="Query Result", description=result['message'], color=discord.Color.blue())
            
            if 'sources' in result:
                sources = "\n".join([f"- {source['filepath']} (lines {source['linestart']}-{source['lineend']})" for source in result['sources']])
                embed.add_field(name="Sources", value=sources, inline=False)

            await ctx.send(embed=embed)

            if str(ctx.author.id) != BOT_OWNER_ID:
                if genius:
                    user_smart_queries[ctx.author.id].append(datetime.now())
                else:
                    user_queries[ctx.author.id].append(datetime.now())

        except aiohttp.ClientError as e:
            await ctx.send(f"An error occurred while processing your request. Please try again later.")
            print(f"Error in query: {str(e)}")

@bot.command(name='query')
@commands.cooldown(1, 5, commands.BucketType.user)
@is_whitelisted()
async def query(ctx: commands.Context, *, question: str) -> None:
    if not can_make_query(ctx.author.id):
        await ctx.send(f"You have reached the maximum number of queries ({MAX_QUERIES_PER_DAY}) for today.")
        return
    await process_query(ctx, question, False)

@bot.command(name='smartquery')
@commands.cooldown(1, 5, commands.BucketType.user)
@is_whitelisted()
async def smartquery(ctx: commands.Context, *, question: str) -> None:
    if not can_make_smart_query(ctx.author.id):
        await ctx.send(f"You have reached the maximum number of smart queries ({MAX_SMART_QUERIES_PER_DAY}) for today.")
        return
    await process_query(ctx, question, True)

@bot.command(name='search')
@commands.cooldown(1, 5, commands.BucketType.user)
@is_whitelisted()
async def search(ctx: commands.Context, *, search_query: str) -> None:
    if not can_make_query(ctx.author.id):
        await ctx.send(f"You have reached the maximum number of queries ({MAX_QUERIES_PER_DAY}) for today.")
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
                "remote": REPO_REMOTE,
                "repository": f"{REPO_OWNER}/{REPO_NAME}",
                "branch": REPO_BRANCH
            }
        ],
        "sessionId": f"discord-search-{ctx.author.id}-{ctx.message.id}",
        "stream": False
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload, headers=headers) as response:
                response.raise_for_status()
                results = await response.json()

            if not results:
                await ctx.send("No results found.")
                return

            embed = discord.Embed(title="Search Results", color=discord.Color.green())
            for result in results:
                embed.add_field(
                    name=f"{result['filepath']} (lines {result['linestart']}-{result['lineend']})",
                    value=f"Summary: {result['summary'][:100]}...",
                    inline=False
                )

            await ctx.send(embed=embed)

            if str(ctx.author.id) != BOT_OWNER_ID:
                user_queries[ctx.author.id].append(datetime.now())

        except aiohttp.ClientError as e:
            await ctx.send(f"An error occurred while searching the repository. Please try again later.")
            print(f"Error in search: {str(e)}")

@bot.command(name='greptilehelp')
async def greptilehelp(ctx: commands.Context) -> None:
    help_embed = discord.Embed(
        title="Greptile Bot",
        description="This bot answers questions about a repo.",
        color=discord.Color.blue()
    )
    help_embed.add_field(
        name="~search <search_query>",
        value="Search for relevant code in the repository.\nExample: `~search example`",
        inline=False
    )
    help_embed.add_field(
        name="~query <question>",
        value="Ask a question about the codebase and get a detailed answer.\nExample: `~query How does the example work in example?`",
        inline=False
    )
    help_embed.add_field(
        name="~smartquery <question>",
        value="Ask a more complex question using the 'genius' feature.\nExample: `~smartquery Explain the relationship between example and example in the example system.`",
        inline=False
    )
    help_embed.add_field(
        name="Usage Limits",
        value=f"- You can make up to {MAX_QUERIES_PER_DAY} regular queries and {MAX_SMART_QUERIES_PER_DAY} smart queries per day.\n- Only whitelisted users can use these commands.",
        inline=False
    )
    help_embed.set_footer(text="If you have any issues or questions, please contact the bot owner.")

    await ctx.send(embed=help_embed)

@bot.command(name='listwhitelist')
@is_bot_owner()
async def listwhitelist(ctx: commands.Context) -> None:
    whitelist_str = "\n".join(WHITELIST)
    await ctx.send(f"Current whitelist:\n{whitelist_str}")

@bot.command(name='addwhitelist')
@is_bot_owner()
async def addwhitelist(ctx: commands.Context, user_id: str) -> None:
    if user_id not in WHITELIST:
        WHITELIST.append(user_id)
        save_whitelist(WHITELIST)
        await ctx.send(f"User {user_id} added to whitelist.")
    else:
        await ctx.send(f"User {user_id} is already in the whitelist.")

@bot.command(name='removewhitelist')
@is_bot_owner()
async def removewhitelist(ctx: commands.Context, user_id: str) -> None:
    if user_id in WHITELIST:
        WHITELIST.remove(user_id)
        save_whitelist(WHITELIST)
        await ctx.send(f"User {user_id} removed from whitelist.")
    else:
        await ctx.send(f"User {user_id} is not in the whitelist.")

@bot.command(name='reload')
@is_bot_owner()
async def reload_bot(ctx: commands.Context) -> None:
    await ctx.send("Reloading the bot...")
    await bot.close()
    os.execv(sys.executable, ['python'] + sys.argv)

# Run the bot
bot.run(TOKEN)
