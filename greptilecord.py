import os # Use env variables for better security
import discord
from discord.ext import commands
import requests
from datetime import datetime
from collections import defaultdict
import asyncio
import urllib.parse

TOKEN = 'YOUR_BOT_TOKEN'
GREPTILE_API_KEY = 'YOUR_GREPTILE_KEY'
GITHUB_TOKEN = 'YOUR_GITHUB_PAT'
WHITELIST = ['251574105356751746', '325364234672159234']  # Whitelisted user IDs can query and search
BOT_OWNER_ID = 'YOUR_DISCORD_ID' # Bot owner has unlimited queries
MAX_QUERIES_PER_DAY = 5  # Whitelisted user query limit

# Repository configuration
REPO_REMOTE = "github"
REPO_OWNER = "followingthefasciaplane"
REPO_NAME = "greptilecord"
REPO_BRANCH = "master"

# Discord bot permissions
BOT_PERMISSIONS = discord.Permissions(8) # Have this set as admin for convenience but should be limited

# Initialize bot with all intents, should also be limited
intents = discord.Intents.all()
bot = commands.Bot(command_prefix='~', intents=intents)

# Track user queries
user_queries = defaultdict(list)

def is_whitelisted(user_id):
    return str(user_id) in WHITELIST or str(user_id) == BOT_OWNER_ID

def can_make_query(user_id):
    if str(user_id) == BOT_OWNER_ID:
        return True
    today = datetime.now().date()
    user_queries[user_id] = [date for date in user_queries[user_id] if date.date() == today]
    return len(user_queries[user_id]) < MAX_QUERIES_PER_DAY

async def index_repository():
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

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        print(f"Repository indexing started: {response.json()['response']}")

        # Wait for indexing to complete
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

    except requests.exceptions.RequestException as e:
        print(f"An error occurred while indexing the repository: {str(e)}")
        print(f"URL attempted: {url}")
        print(f"Payload: {payload}")
        print(f"Response status code: {e.response.status_code if e.response else 'N/A'}")
        print(f"Response content: {e.response.text if e.response else 'N/A'}")

async def get_repository_status():
    # Correctly format the repository ID
    repo_id = f"{REPO_REMOTE}:{REPO_BRANCH}:{REPO_OWNER}/{REPO_NAME}"
    # URL-encode the entire repository ID string
    encoded_repo_id = urllib.parse.quote(repo_id, safe='')
    url = f'https://api.greptile.com/v2/repositories/{encoded_repo_id}'
    
    headers = {
        'Authorization': f'Bearer {GREPTILE_API_KEY}',
        'X-GitHub-Token': GITHUB_TOKEN
    }

    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        repo_info = response.json()
        print(f"Repository info retrieved successfully: {repo_info}")
        return repo_info['status']
    except requests.exceptions.RequestException as e:
        print(f"An error occurred while checking repository status: {str(e)}")
        print(f"URL attempted: {url}")
        print(f"Response status code: {e.response.status_code if e.response else 'N/A'}")
        print(f"Response content: {e.response.text if e.response else 'N/A'}")
        return None

@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    await index_repository()

@bot.command(name='query')
async def query(ctx, *, question):
    if not is_whitelisted(ctx.author.id):
        await ctx.send("You are not authorized to use this command.")
        return

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

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        result = response.json()

        # Send the response in chunks if it's too long
        chunks = [result['message'][i:i+1900] for i in range(0, len(result['message']), 1900)]
        for chunk in chunks:
            await ctx.send(chunk)

        # Send sources information
        if 'sources' in result:
            sources_message = "**Sources:**\n"
            for source in result['sources']:
                sources_message += f"- {source['filepath']} (lines {source['linestart']}-{source['lineend']})\n"
            await ctx.send(sources_message)

        # Update user query count
        if str(ctx.author.id) != BOT_OWNER_ID:
            user_queries[ctx.author.id].append(datetime.now())

    except requests.exceptions.RequestException as e:
        await ctx.send(f"An error occurred while processing your request: {str(e)}")

@bot.command(name='search')
async def search(ctx, *, search_query):
    if not is_whitelisted(ctx.author.id):
        await ctx.send("You are not authorized to use this command.")
        return

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

    try:
        response = requests.post(url, json=payload, headers=headers)
        response.raise_for_status()
        results = response.json()

        if not results:
            await ctx.send("No results found.")
            return

        message = "**Search Results:**\n"
        for result in results:
            message += f"- {result['filepath']} (lines {result['linestart']}-{result['lineend']})\n"
            message += f"  Summary: {result['summary'][:100]}...\n\n"

        # Send the response in chunks if it's too long
        chunks = [message[i:i+1900] for i in range(0, len(message), 1900)]
        for chunk in chunks:
            await ctx.send(chunk)

        # Update user query count
        if str(ctx.author.id) != BOT_OWNER_ID:
            user_queries[ctx.author.id].append(datetime.now())

    except requests.exceptions.RequestException as e:
        await ctx.send(f"An error occurred while searching the repository: {str(e)}")

# Example help command
@bot.command(name='greptilehelp')
async def greptilehelp(ctx):
    help_message = f"""
**Greptile Bot Help**

This bot helps you search and query the Source Engine 2018 HL2 repository.

**Commands:**

1. **~search <search_query>**
  Search for relevant code in the repository.
  Example: `~search physics engine implementation`

2. **~query <question>**
  Ask a question about the codebase and get a detailed answer.
  Example: `~query How does the physics engine work in this Source Engine implementation?`

3. **~greptilehelp**
  Display this help message.

**Usage Limits:**
- You can make up to {MAX_QUERIES_PER_DAY} queries per day.
- Only whitelisted users can use these commands.

If you have any issues or questions, please contact the bot owner.
    """
    await ctx.send(help_message)

# Run the bot
bot.run(TOKEN)
