import os
from typing import Optional, List, Dict, Any
import discord
from discord.ext import commands, tasks
import aiohttp
from datetime import datetime
from collections import defaultdict
import asyncio
import urllib.parse

TOKEN = os.getenv('DISCORD_BOT_TOKEN')
GREPTILE_API_KEY = os.getenv('GREPTILE_API_KEY')
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
WHITELIST = os.getenv('WHITELIST', '').split(',') # Whitelisted users can query
BOT_OWNER_ID = os.getenv('BOT_OWNER_ID') # Unlimited queries
MAX_QUERIES_PER_DAY = int(os.getenv('MAX_QUERIES_PER_DAY', 5)) # Max for whitelisted users

# Repository configuration
REPO_REMOTE = "github"
REPO_OWNER = "followingthefasciaplane"
REPO_NAME = "greptilecord"
REPO_BRANCH = "main"

# Discord bot permissions
BOT_PERMISSIONS = discord.Permissions(8)  # Admin but should be limited

# Initialize bot with all intents but should be limited
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='~', intents=intents)

# Track user queries
user_queries: Dict[int, List[datetime]] = defaultdict(list)

def is_whitelisted() -> commands.check:
    async def predicate(ctx: commands.Context) -> bool:
        return str(ctx.author.id) in WHITELIST or str(ctx.author.id) == BOT_OWNER_ID
    return commands.check(predicate)

def can_make_query(user_id: int) -> bool:
    if str(user_id) == BOT_OWNER_ID:
        return True
    today = datetime.now().date()
    user_queries[user_id] = [date for date in user_queries[user_id] if date.date() == today]
    return len(user_queries[user_id]) < MAX_QUERIES_PER_DAY

async def index_repository() -> None:
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
        "reload": True,
        "notify": False
    }

    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(url, json=payload, headers=headers) as response:
                response.raise_for_status()
                result = await response.json()
                print(f"Repository indexing started: {result['response']}")

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

        except aiohttp.ClientError as e:
            print(f"An error occurred while indexing the repository: {str(e)}")
            print(f"URL attempted: {url}")
            print(f"Payload: {payload}")

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

@bot.command(name='query')
@commands.cooldown(1, 5, commands.BucketType.user)
@is_whitelisted()
async def query(ctx: commands.Context, *, question: str) -> None:
    if not can_make_query(ctx.author.id):
        await ctx.send(f"You have reached the maximum number of queries ({MAX_QUERIES_PER_DAY}) for today.")
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
                "remote": REPO_REMOTE,
                "repository": f"{REPO_OWNER}/{REPO_NAME}",
                "branch": REPO_BRANCH
            }
        ],
        "sessionId": f"discord-query-{ctx.author.id}-{ctx.message.id}",
        "stream": False,
        "genius": True
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
                user_queries[ctx.author.id].append(datetime.now())

        except aiohttp.ClientError as e:
            await ctx.send(f"An error occurred while processing your request. Please try again later.")
            print(f"Error in query: {str(e)}")

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
        title="Greptile Bot Help",
        description="This bot helps you search and query the Source Engine 2018 HL2 repository.",
        color=discord.Color.blue()
    )
    help_embed.add_field(
        name="~search <search_query>",
        value="Search for relevant code in the repository.\nExample: `~search physics engine implementation`",
        inline=False
    )
    help_embed.add_field(
        name="~query <question>",
        value="Ask a question about the codebase and get a detailed answer.\nExample: `~query How does the physics engine work in this Source Engine implementation?`",
        inline=False
    )
    help_embed.add_field(
        name="Usage Limits",
        value=f"- You can make up to {MAX_QUERIES_PER_DAY} queries per day.\n- Only whitelisted users can use these commands.",
        inline=False
    )
    help_embed.set_footer(text="If you have any issues or questions, please contact the bot owner.")

    await ctx.send(embed=help_embed)

# Run the bot
bot.run(TOKEN)
