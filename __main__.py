# FeedMe, JosiahVanderzee 2021 (c)

import asyncio
import os
import pathlib

import aiohttp
from discord.ext import commands

print("Welcome to FeedMe, the web feed watcher.")

bot = commands.Bot(">")
bot.load_extension("feedme")

@bot.event
async def on_ready() -> None:
    print("Connection (re)established.")
    
async def start() -> None:

    bot_token = os.environ.get("FEEDME_TOKEN")
    if bot_token is None:
        raise RuntimeError("Please set the FEEDME_TOKEN environment variable.")

    loop = asyncio.get_running_loop()
    loop.set_debug(True)
    async with aiohttp.ClientSession(loop=loop) as session:
        setattr(bot, "session", session)
        await bot.start(bot_token)
    
asyncio.run(start())
