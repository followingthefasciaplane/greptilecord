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

- Regular queries: Configurable daily limit per whitelisted user (default: 5).
- Smart queries (genius mode): Configurable daily limit per whitelisted user (default: 1).
- The bot owner has unlimited usage of all commands.
- Configurable options are stored in a SQLite database for persistence.
- Customizable bot prefix (default: '~')

## Whitelist System

- Three user roles: User, Admin, and Owner.
- Only whitelisted users can use the search and query commands.
- Admins can manage the whitelist and bot configuration.
- The Owner (set in the configuration) has full access to all commands.
- Whitelist data is stored in a SQLite database for persistence.

## Database

The bot uses SQLite for persistent storage of:
- Whitelist information
- Indexed repositories
- Bot configuration

## Error Handling and Logging

- Comprehensive error handling for all commands.
- Configurable error reporting channel.
- Detailed logging of bot activities and errors.
- Automatic error reporting to a designated channel and the bot owner.

## Periodic Tasks

- Automatic repository status checks every 30 minutes.
- Reporting of failed or stuck repository indexing.

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
   DISCORD_BOT_TOKEN: 'your_discord_bot_token'
   GREPTILE_API_KEY: 'your_greptile_api_key'
   GITHUB_TOKEN: 'your_github_token'
   BOT_OWNER_ID: 'your_discord_user_id'
   ```


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

## Note

This bot is not affiliated with Greptile in any way. It is a third-party implementation using the Greptile API. While efforts have been made to ensure stability, it may still contain bugs and requires further testing.
