# Greptile Discord Bot

This Discord bot provides information and answers questions about repositories using the [Greptile](https://greptile.com) API. It offers advanced features for repository management, user access control, and intelligent code querying. See [documentation](https://docs.greptile.com/prompt-guide) for more information about Greptile.

## Features

- Repository indexing and management
- Intelligent code search and querying
- User access control with whitelist system
- Configurable settings
- Error logging and reporting
- Periodic repository status checks

## Commands

### General Commands

- `~greptilehelp`: Displays a detailed help message with information about all available commands.
- `~search <search_query>`: Searches for relevant code in the indexed repositories.
- `~query <question>`: Asks a question about the codebase and gets a detailed answer.
- `~smartquery <question>`: Asks a more complex question using the 'genius' feature for more detailed analysis.
- `~listrepos`: Lists all indexed repositories.
- `~repostatus`: Views the current status of the indexed repository.

### Admin Commands

- `~addrepo <remote> <owner> <name> <branch>`: Adds and indexes a new repository.
- `~removerepos`: Removes all indexed repositories.
- `~reindex`: Forces reindexing of the current repository.
- `~setconfig <key> <value>`: Sets a configuration value.
- `~viewconfig`: Views the current bot configuration.
- `~listwhitelist`: Lists all whitelisted users.
- `~addwhitelist <user_id>`: Adds a user to the whitelist.
- `~removewhitelist <user_id>`: Removes a user from the whitelist.
- `~setlogchannel <channel_id>`: Sets the channel for logging bot activities.
- `~seterrorchannel <channel_id>`: Sets the channel for error reporting.
- `~testerror`: Tests the error reporting system.
- `~reload`: Reloads the bot.

### Owner Commands

- `~addadmin <user_id>`: Promotes a user to admin.
- `~removeadmin <user_id>`: Demotes an admin to a regular user.

## Configuration

- Regular queries: Configurable daily limit per whitelisted user (default: 5).
- Smart queries (genius mode): Configurable daily limit per whitelisted user (default: 1).
- The bot owner has unlimited usage of all commands.
- Configurable options are stored in a SQLite database for persistence.

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

## Note

This bot is not affiliated with Greptile in any way. It is a third-party implementation using the Greptile API. It may be buggy, it needs more testing.
