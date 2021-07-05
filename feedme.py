from __future__ import annotations

import asyncio
import configparser
import datetime
import pathlib
import pickle
from typing import Optional

import discord
from discord.ext import commands
import feedparser # type: ignore

UPDATES_FILE = f"{pathlib.Path(__file__).parent}/updates.pickle"

class MissingSessionError(Exception):
    pass

class FeedMe(commands.Cog):

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.config = configparser.ConfigParser()
        self.config.read(f"{pathlib.Path(__file__).parent}/config.ini")
        self.poller: Optional[asyncio.Task] = None
        
    async def post_update(self, entry: feedparser.FeedParserDict) -> None:
        channel_id = self.config["DEFAULT"].getint("DiscordChannel")
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
        if self.poller is None:
            self.poller = asyncio.create_task(self.poll())
            await ctx.send("Started.")
        else:
            await ctx.send("Already running!")

    @commands.is_owner()
    @commands.command(help="stop polling")
    async def stop(self, ctx: commands.Context) -> None:
        if self.poller is not None:
            self.poller.cancel()
            await ctx.send("Stopped.")
        else:
            await ctx.send("Already stopped!")

    async def fetch(self) -> str:
        feed_url = self.config["DEFAULT"]["FeedURL"]
        session = getattr(self.bot, "session", None)
        if session is None:
            print("Missing session!")
            raise MissingSessionError("bot.session undefined")
        async with session.get(feed_url) as response:
            return str(await response.text())
        
    async def poll(self) -> None:
        while True:
            print("Fetching feed...")
            feed = feedparser.parse(await self.fetch())
            print("Checking for updated feeds...")
            updates: dict[str, str] = pickle.load(open(UPDATES_FILE, "rb"))
            for entry in reversed(feed.entries):
                #if updates.get(entry.id, "") != entry.updated:
                if True:
                    print(f"Found updated feed {entry.title}!")
                    await self.post_update(entry)
            # If the code is interrupted here, the update may duplicate.
            pickle.dump(updates, open(UPDATES_FILE, "wb"))
            await asyncio.sleep(self.config["DEFAULT"].getint("Interval"))
        
def setup(bot: commands.Bot) -> None:
    bot.add_cog(FeedMe(bot))