# Greptile 

This Discord bot provides information and answers questions about a repo using [Greptile](https://greptile.com) API. See [documentation](https://docs.greptile.com/prompt-guide).  
I am not affiliated with Greptile in any way.

## Commands

### General Commands

#### `~greptilehelp`
Displays a help message with information.

#### `~search <search_query>`
Searches for relevant code in the repository.  
Example: `~search example`

#### `~query <question>`
Asks a question about the codebase and gets a detailed answer.  
Example: `~query How does the example in example?`

#### `~smartquery <question>`
Asks a more complex question using the 'genius' feature for more in-depth analysis.  
Example: `~smartquery Explain the relationship between example and example in the example system.`

### Admin Commands

These commands are only available to the bot owner:

#### `~listwhitelist`
Lists all user IDs currently in the whitelist.

#### `~addwhitelist <user_id>`
Adds a user ID to the whitelist, allowing them to use the bot's commands.  
Example: `~addwhitelist 123456789012345678`

#### `~removewhitelist <user_id>`
Removes a user ID from the whitelist.  
Example: `~removewhitelist 123456789012345678`

#### `~reload`
Reloads the bot without reprocessing the repository. Useful for applying code changes or resetting the bot's state.

## Config

- Regular queries: 5 per day per whitelisted user by default.
- Genius queries: 1 per day per whitelisted user by default. 
- The bot owner has unlimited usage of all commands  

## Whitelist System

- Only whitelisted users can use the search and query commands  
- The whitelist is managed by the bot owner using the admin commands  
- Whitelist is persistent and stored in a JSON file  
