from __future__ import annotations

import asyncio
import configparser
import datetime
import pathlib
import pickle
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
            await ctx.message.add_reaction(SUCCESS_EMOJI)
        else:
            await ctx.send("Already running!")
            
    @commands.is_owner()
    @commands.command(help="stop polling")
    async def stop(self, ctx: commands.Context) -> None:
        if self.poller is not None:
            self.poller.cancel()
            await ctx.message.add_reaction(SUCCESS_EMOJI)
        else:
            await ctx.send("Already stopped!")

    @commands.is_owner()
    @commands.command(help="<url> <channel> add a new feed")
    async def new(self, ctx: commands.Context, url: str,
            channel: discord.TextChannel) -> None:
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

        await self.update_feed(feed.feed.title, url, channel.id, feed)
        await ctx.message.add_reaction(SUCCESS_EMOJI)
        
    @commands.is_owner()
    @commands.command(help="<name> remove a feed")
    async def remove(self, ctx: commands.Context, feed_url: str) -> None:
        await self.remove_feed(feed_url)

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
        updates = await self.get_entries(feed.feed.title)
        for entry in reversed(feed.entries):
            for old_entry in updates:
                if old_entry[0] == entry.id and \
                        old_entry[2] == entry.updated:
                    break
            else:
                print(f"Found updated entry {entry.title}!")
                await self.post_update(entry, channel_id)
                # If something goes wrong here entry could get posted twice.
                await self.update_entry(
                    entry.id, feed.feed.title, entry.updated)

    async def poll(self) -> None:
        print("Starting to poll.")
        while True:
            feeds = await self.get_feeds()
            for feed_record in feeds:
                print(f"Fetching feed {feed_record[1]}...")
                feed = feedparser.parse(await self.fetch(feed_record[1]))
                await self.check_entries(feed, feed_record[2])

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
                raise e
                self.poller = asyncio.create_task(self.poll())
                
            print("Stopped polling.")
            
        return cleanup
            
    async def update_feed(self, name: str, feed_url: str,
        channel_id: int, feed: feedparser.FeedParseDict) -> None:
        async with aiosqlite.connect(DATABASE) as db:
            await db.execute(
                "REPLACE INTO feeds(name, url, channel) " \
                "VALUES (?, ?, ?);", (name, feed_url, channel_id))
            await db.commit()
            
    async def update_entry(self, entry_id: int, feed_name: str,
        updated: str) -> None:
            async with aiosqlite.connect(DATABASE) as db:
                await db.execute(
                    "REPLACE INTO entries(entry_id, feed_name, updated) " \
                    "VALUES (?, ?, ?);", (entry_id, feed_name, updated))
                await db.commit()
            
    async def get_feeds(self) -> list[aiosqlite.Row]:
        feeds = []
        async with aiosqlite.connect(DATABASE) as db:
            async with db.execute("SELECT * FROM feeds;") as cursor:
                async for row in cursor:
                    feeds.append(row)
        return feeds
        
    async def remove_feed(self, feed_url: str) -> None:
        async with aiosqlite.connect(DATABASE) as db:
            await db.execute("DELETE FROM feeds WHERE (url = ?)", (feed_url,))
            await db.commit()
        
    async def get_entries(self, feed_name: str) -> list[aiosqlite.Row]:
        entries = []
        async with aiosqlite.connect(DATABASE) as db:
            async with db.execute(
                    "SELECT * FROM entries WHERE (feed_name = ?);",
                    (feed_name,)) as cursor: 
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