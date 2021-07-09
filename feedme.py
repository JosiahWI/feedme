from __future__ import annotations

import asyncio
import configparser
import datetime
import pathlib
import pickle
import sqlite3
from typing import Callable, Optional

import aiohttp
import aiosqlite
import discord
from discord.ext import commands
import feedparser # type: ignore

# Green checkmark
SUCCESS_EMOJI = '\u2705'
DATABASE = f"{pathlib.Path(__file__).parent}/database/database.db"
DATABASE_CREATE_SCRIPT = \
    f"{pathlib.Path(__file__).parent}/database/init_database.sql"
    
class BadResponseError(Exception):
    pass
    
class MissingSessionError(Exception):
    pass

class Feed:
    """
    A Feed represents one feed with a discord channel and a feed url.
    """
    
    def __init__(self, name: str, channel_id: int,
            guild_id: int, url: str) -> None:
        """
        name: The name of the feed.
        channel_id: The ID of the Discord channel to send to.
        guild_id: The ID of the guild the channel is part of.
        url: The URL of the web feed.
        """
        self.name = name
        self.channel_id = channel_id
        self.guild_id = guild_id
        self.url = url
        
    def __str__(self) -> str:
        return f"{self.name} in channel {self.channel_id}"

    async def commit(self) -> None:
        """
        Coroutine to save the feed to the database.
        
        Will raise an error if the channel already has a feed in it.
        """
        async with aiosqlite.connect(DATABASE) as db:
            await db.execute(
                "INSERT INTO feeds(name, channel_id, guild_id, url) " \
                "VALUES (?, ?, ?, ?);",
                (self.name, self.channel_id, self.guild_id, self.url))
            await db.commit()
            
    @staticmethod
    async def load_all() -> list[Feed]:
        """
        Static coroutine to load all feeds in the database.
    
        Returns a list of Feeds.
        """
        feeds = []
        async with aiosqlite.connect(DATABASE) as db:
            async with db.execute("SELECT * FROM feeds;") as cursor:
                async for row in cursor:
                    feeds.append(Feed(*row))
        
        return feeds
    
    @staticmethod
    async def load_from_channel(channel_id: int) -> Optional[Feed]:
        """
        Static coroutine to load a channel's feed from the database.
    
        Returns a Feed, or None if no feed was found for that channel.
    
        channel_id: The ID of the discord channel the feed is set to.
        """
        feeds = []
        async with aiosqlite.connect(DATABASE) as db:
            async with db.execute(
                    "SELECT * FROM feeds WHERE (channel_id = ?)",
                    (channel_id,)) as cursor:
                async for row in cursor:
                    feeds.append(Feed(*row))
                
        assert(len(feeds) <= 1)
        if len(feeds) == 0:
            return None
        
        return feeds[0]
        
    @staticmethod
    async def delete(channel_id: int) -> None:
        """
        Static coroutine to delete a channel's feed.
        
        If the feed does not exist, nothing will happen.
        
        channel_id: The ID of the discord channel the feed is set to.
        """
        async with aiosqlite.connect(DATABASE) as db:
            await db.execute(
                "DELETE FROM feeds WHERE (channel_id = ?)",
                (channel_id,))
            await db.commit()

class FeedMe(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.config = configparser.ConfigParser()
        self.config.read(f"{pathlib.Path(__file__).parent}/config.ini")
        self.poller: Optional[asyncio.Task] = None
        asyncio.get_event_loop().run_until_complete(self._init_database())

    async def _init_database(self) -> None:
        async with aiosqlite.connect(DATABASE) as db:
            with open(DATABASE_CREATE_SCRIPT) as script:
                await db.executescript(script.read())
            await db.commit()
        
    async def post_update(self, entry: feedparser.FeedParserDict,
            channel_id: int) -> None:
        channel = await self.bot.fetch_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            print(f"ERROR: Channel {channel_id} is not a text channel!")
            return
                
        embed = discord.Embed(
            title=entry.title,
            description=entry.summary,
            timestamp=datetime.datetime(*entry.updated_parsed[0:3])
        )
        await channel.send(embed=embed)

    @commands.is_owner()
    @commands.command(help="start polling")
    async def start(self, ctx: commands.Context) -> None:
        if self.poller is None or self.poller.cancelled():
            self.poller = asyncio.create_task(self.poll())
            self.poller.add_done_callback(self._cleanup_poll())
            print("INFO: Starting poller.")
            await ctx.message.add_reaction(SUCCESS_EMOJI)
        else:
            await ctx.send("Already running!")
            
    @commands.is_owner()
    @commands.command(help="stop polling")
    async def stop(self, ctx: commands.Context) -> None:
        if self.poller is not None:
            self.poller.cancel()
            print("INFO: Stopped polling.")
            await ctx.message.add_reaction(SUCCESS_EMOJI)
        else:
            await ctx.send("Already stopped!")

    @commands.is_owner()
    @commands.guild_only()
    @commands.command(help="<channel> <url> add a new feed")
    async def new(self, ctx: commands.Context, channel: discord.TextChannel,
            url: str) -> None:
        try:
            feed = feedparser.parse(await self.fetch(url))
        except BadResponseError as e:
            await ctx.send(f"Error: {e}!")
            return
        except aiohttp.client_exceptions.InvalidURL:
            await ctx.send("Error: Invalid URL!")
            return
        except asyncio.TimeoutError:
            await ctx.send("Error: Connection timed out!")
            return
        except:
            await ctx.send("There was an error processing your request.")
            raise
        if feed.bozo:
            await ctx.send("Feed is not well-formed.")
            return
            
        # To keep mypy quiet. guild_only() should handle this.
        assert(ctx.guild is not None)
        bot_feed = Feed(feed.feed.title, channel.id, ctx.guild.id, url)

        try:
            await bot_feed.commit()
        except sqlite3.IntegrityError:
            await ctx.send("Channel already has a feed in it.")
            return
        await ctx.message.add_reaction(SUCCESS_EMOJI)
        
    @commands.is_owner()
    @commands.command(help="<name> remove a feed")
    async def remove(self, ctx: commands.Context,
            channel: discord.TextChannel) -> None:
        await Feed.delete(channel.id)

    async def fetch(self, feed_url: str) -> str:
        session = getattr(self.bot, "session", None)
        if session is None:
            print("Missing session!")
            raise MissingSessionError("bot.session undefined")
        async with session.get(feed_url, timeout=60.0) as response:
            if response.status != 200:
                raise BadResponseError(f"Got status code {response.status}")
            return str(await response.text())
        
    async def check_entries(self, feed: feedparser.FeedParseDict,
            channel_id: int) -> None:
        print("Checking for updated entries...")
        updates = await self.get_entries(feed.feed.title, channel_id)
        for entry in reversed(feed.entries):
            for old_entry in updates:
                if old_entry[2] == entry.id and \
                        old_entry[3] == entry.updated:
                    break
            else:
                print(f"Found updated entry {entry.title}!")
                await self.post_update(entry, channel_id)
                # If something goes wrong here entry could get posted twice.
                await self.update_entry(
                    entry.id, feed.feed.title, channel_id, entry.updated)

    async def poll(self) -> None:
        while True:
            feeds = await Feed.load_all()
            for bot_feed in feeds:
                print(f"Fetching feed {bot_feed}...")
                feed = feedparser.parse(await self.fetch(bot_feed.url))
                await self.check_entries(feed, bot_feed.channel_id)

            await asyncio.sleep(self.config["DEFAULT"].getint("Interval"))
            
    def _cleanup_poll(self) -> Callable[[asyncio.Future], None]:
        """
        Returns a callback that performs exception handling for the poll loop.
        """
        def cleanup(future: asyncio.Future) -> None:
            if future.cancelled():
                return
            
            e = future.exception()
            if isinstance(e, Exception):
                print("INFO: Restarting poller.")
                self.poller = asyncio.create_task(self.poll())
                raise e
                            
        return cleanup
            
    async def update_entry(self, entry_id: int, feed_name: str,
        channel_id: int, updated: str) -> None:
            async with aiosqlite.connect(DATABASE) as db:
                await db.execute(
                    "REPLACE INTO " \
                    "entries(feed_name, channel_id, entry_id, updated) " \
                    "VALUES (?, ?, ?, ?);",
                    (feed_name, channel_id, entry_id, updated))
                await db.commit()
        
    async def remove_feed(self, feed_url: str) -> None:
        async with aiosqlite.connect(DATABASE) as db:
            await db.execute("DELETE FROM feeds WHERE (url = ?)", (feed_url,))
            await db.commit()
        
    async def get_entries(self, feed_name: str,
            channel_id: int) -> list[aiosqlite.Row]:
        entries = []
        async with aiosqlite.connect(DATABASE) as db:
            async with db.execute(
                    "SELECT * FROM entries " \
                    "WHERE(feed_name = ? AND channel_id = ?);",
                    (feed_name, channel_id)) as cursor: 
                async for row in cursor:
                    entries.append(row)
        return entries
            
    @commands.Cog.listener()
    async def on_command_error(self, ctx: commands.Context,
            e: commands.CommandError) -> None:
        if isinstance(e, commands.errors.MissingRequiredArgument):
            await ctx.send(str(e))
        else:
            raise e
        
def setup(bot: commands.Bot) -> None:
    bot.add_cog(FeedMe(bot))