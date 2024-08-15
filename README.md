# Greptile Discord Bot

This Discord bot provides information and answers questions about repositories using the [Greptile](https://greptile.com) API. It offers advanced features for repository management, user access control, and intelligent code querying. See [documentation](https://docs.greptile.com/prompt-guide) for more information about Greptile.

## Features

- Repository indexing and management
- Intelligent code search and querying
- User access control with whitelist system
- Configurable settings
- Error logging and reporting
- Periodic repository status checks
- Automatic reindexing of repositories
- Pagination for long responses
- SQLite for persistent storage

## Unsupported 

- Chat history and session management
  
I may implement this in the future, as Greptile's API supports it, however, for now this bot only supports 0 shot queries.

## Installation

1. Set up a virtual environment and install dependencies:
   - On Linux/macOS:
     ```
     ./setup_venv.sh
     ```
   - On Windows:
     ```
     setup_venv.bat
     ```

2. Update your "secrets.yaml" file:
   ```yaml
   DISCORD_BOT_TOKEN: 'your_discord_bot_token' # You will add this in Step 3
   GREPTILE_API_KEY: 'your_greptile_api_key' # Your Greptile API Key
   GITHUB_TOKEN: 'your_github_token' # Your GitHub PAT
   BOT_OWNER_ID: 'your_discord_user_id' # This is not your username
   ```
   - To find your Discord ID, you can read [this article](https://support.discord.com/hc/en-us/articles/206346498-Where-can-I-find-my-User-Server-Message-ID).

3. Create a Discord application and bot:
   - Go to the [Discord Developer Portal](https://discord.com/developers/applications)
   - Click "New Application" and configure your application
   - Go to the "Bot" tab and click "Add Bot"
   - Under the bot's username, click "Copy" to copy the bot token
   - Paste the bot token in your `secrets.yaml` file
   - Under "Privileged Gateway Intents", enable all intents
   - Go to the "Installation" tab and enable "Guild Install"
   - Select the "bot" and "applications.commands" scopes 
   - For bot permissions, select "Administrator"
   - Save all and copy the generated URL and use it to invite the bot to your server

4. Run the bot:
   ```
   python greptilebot.py
   ```

### Optional security
- Consider limiting Discord intents and permissions to what is needed. Full permissions are provided for convenience.
- Consider using environment variables in `secrets.yaml`. Eg: `DISCORD_BOT_TOKEN: '${DISCORD_BOT_TOKEN}'`

## Commands

### General Commands

- `~greptilehelp`: Displays a detailed help message with information about all available commands.
- `~search <search_query>`: Searches for relevant code in the indexed repositories.
- `~query <question>`: Asks a question about the codebase and gets a detailed answer.
- `~smartquery <question>`: Asks a more complex question using the 'genius' feature for more detailed analysis.
- `~listrepos`: Lists all indexed repositories.
- `~repostatus`: Views the current status of the indexed repositories.

### Admin Commands

- `~addrepo <remote> <owner/name> [branch]`: Adds and indexes a new repository.
- `~removerepos`: Removes all indexed repositories.
- `~reindex [repo_id]`: Forces reindexing of a specific repository or all repositories.
- `~setconfig <key> <value>`: Sets a configuration value.
- `~viewconfig`: Views the current bot configuration.
- `~listwhitelist`: Lists all whitelisted users.
- `~addwhitelist <user_id>`: Adds a user to the whitelist.
- `~removewhitelist <user_id>`: Removes a user from the whitelist.
- `~setlogchannel <channel_id>`: Sets the channel for logging bot activities.
- `~seterrorchannel <channel_id>`: Sets the channel for error reporting.
- `~testerror`: Tests the error reporting system.

### Owner Commands

- `~addadmin <user_id>`: Promotes a user to admin.
- `~removeadmin <user_id>`: Demotes an admin to a regular user.
- `~reload`: Reloads the bot.

## Configuration

- Daily limits for regular and smart queries per user.
- Smart queries are 3x the price of regular queries in the Greptile API.
- The bot owner has unlimited usage of all commands.

### Config Keys:

- `MAX_QUERIES_PER_DAY`: Maximum number of regular queries a user can make per day (default: 5)
- `MAX_SMART_QUERIES_PER_DAY`: Maximum number of smart queries a user can make per day (default: 1)
- `API_TIMEOUT`: Timeout for API calls in seconds (default: 60)
- `API_RETRIES`: Maximum retries for failed API calls (default: 3)
- `BOT_PREFIX`: The prefix used for bot commands (default: "~")
- `DEFAULT_BRANCH`: The default branch to use, if it is omitted from an Administrator command (default: main)

These can be adjusted with the `~setconfig <key> <value>` command.   
To view your current keyvalues, use `~viewconfig`.

## Whitelist System

- Three user roles: `UserRole.USER`, `UserRole.ADMIN`, and `UserRole.OWNER`.
- Only whitelisted users can use the general commands.
- Admins can manage the whitelist and bot configuration.
- The Owner (can only be set in `secrets.yaml`) has full access to all commands, and bypasses daily limits.

### Whitelisting users

- Only the Owner can use `~addadmin` and `~removeadmin`.  
These commands will add `UserRole.ADMIN` to a Discord ID, or demote an existing Admin ID to `UserRole.USER`.
  
- Admins can use `~addwhitelist` and `~removewhitelist`.  
These commands will add or remove `UserRole.USER` to or from a Discord ID.  

- To view the current list of users and the roles they have, you can use `~listwhitelist`.

### Changing permissions for commands

Using `~seterrorchannel` as an example, you can change this line in `src/greptilebot.py` to one of three roles:  
```
@bot.command(name='seterrorchannel')
@is_whitelisted(UserRole.ADMIN)
```


```
@bot.command(name='seterrorchannel')  
@is_whitelisted(UserRole.OWNER)
```


```
@bot.command(name='seterrorchannel')  
@is_whitelisted(UserRole.USER)
```

## Database

The bot uses SQLite for persistent storage of:  
- Whitelist information
- Indexed repositories
- Bot configuration
- DB created automatically in `src/bot_data.db`.

## Error Handling and Logging

- Comprehensive error handling for all commands.
- Detailed logging of bot activities and errors.
- Automatic error reporting to a designated channel and to the bot owner directly via DM.
- Debug logfile is automatically generated `src/bot.log`

`~setlogchannel` will stream the debug log to a channel. **Use carefully, this can leak environment information.**  
`~seterrorchannel` will set a channel to log errors in.  
`~testerror` will cause a division by 0 error to test the error reporting system.

## Periodic Tasks

- Automatic repository status checks every 30 minutes.
- Reporting of failed or stuck repository indexing.

## Note

This bot is not affiliated with Greptile in any way. It is a third-party implementation using the Greptile API. While efforts have been made to ensure stability, it may still contain bugs and requires further testing.
