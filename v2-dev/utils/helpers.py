import discord
from typing import List, Any, Optional
import re
from datetime import timedelta
from utils.error_handler import ConfigError

def chunk_list(lst: List[Any], chunk_size: int) -> List[List[Any]]:
    """Split a list into smaller chunks of a specified size."""
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]

def create_embed(title: str, description: str, color: discord.Color = discord.Color.blue()) -> discord.Embed:
    """Create a Discord embed with the given title, description, and color."""
    return discord.Embed(title=title, description=description, color=color)

def truncate_string(string: str, max_length: int) -> str:
    """Truncate a string to a maximum length, adding an ellipsis if truncated."""
    return (string[:max_length - 3] + '...') if len(string) > max_length else string

def format_code_block(code: str, language: str = '') -> str:
    """Format a string as a Discord code block with optional language highlighting."""
    return f'```{language}\n{code}\n```'

def format_time_delta(seconds: int) -> str:
    """Format a number of seconds into a human-readable time delta string."""
    delta = timedelta(seconds=seconds)
    days = delta.days
    hours, rem = divmod(delta.seconds, 3600)
    minutes, seconds = divmod(rem, 60)
    
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if seconds > 0 or not parts:
        parts.append(f"{seconds}s")
    
    return " ".join(parts)

def sanitize_input(input_string: str) -> str:
    """Remove any potentially harmful characters from user input."""
    return ''.join(char for char in input_string if char.isalnum() or char in (' ', '_', '-', '.'))

def parse_repo_string(repo_string: str) -> tuple:
    """Parse a repository string in the format 'remote:owner/name:branch'."""
    try:
        remote, repo, branch = repo_string.split(':')
        owner, name = repo.split('/')
        return remote, owner, name, branch
    except ValueError:
        raise ConfigError("Invalid repository format. Expected: remote:owner/name:branch")

def create_progress_bar(progress: float, width: int = 20) -> str:
    """Create a text-based progress bar."""
    filled_width = int(width * progress)
    return f"[{'=' * filled_width}{' ' * (width - filled_width)}] {progress:.0%}"

def format_file_size(size_in_bytes: int) -> str:
    """Format a file size in bytes to a human-readable string."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_in_bytes < 1024.0:
            return f"{size_in_bytes:.2f} {unit}"
        size_in_bytes /= 1024.0
    return f"{size_in_bytes:.2f} PB"

def is_valid_discord_id(id_string: str) -> bool:
    """Check if a string is a valid Discord ID (numeric and 17-19 digits long)."""
    return id_string.isdigit() and 17 <= len(id_string) <= 19

def format_repository_name(owner: str, name: str) -> str:
    """Format repository owner and name into a standard string."""
    return f"{owner}/{name}"

def parse_repository_name(repo_string: str) -> Optional[tuple]:
    """Parse a repository string in the format 'owner/name' and return a tuple of (owner, name)."""
    match = re.match(r'^([^/]+)/([^/]+)$', repo_string)
    if match:
        return match.groups()
    return None

def create_error_embed(title: str, description: str) -> discord.Embed:
    """Create a standardized error embed."""
    return discord.Embed(title=title, description=description, color=discord.Color.red())

def create_success_embed(title: str, description: str) -> discord.Embed:
    """Create a standardized success embed."""
    return discord.Embed(title=title, description=description, color=discord.Color.green())

def format_command_usage(command_name: str, usage: str) -> str:
    """Format command usage string."""
    return f"Usage: `~{command_name} {usage}`"

def split_long_message(message: str, max_length: int = 2000) -> List[str]:
    """Split a long message into multiple messages that fit within Discord's character limit."""
    return [message[i:i+max_length] for i in range(0, len(message), max_length)]

def escape_markdown(text: str) -> str:
    """Escape Discord markdown characters in a string."""
    markdown_chars = ['*', '_', '~', '`', '|']
    for char in markdown_chars:
        text = text.replace(char, '\\' + char)
    return text