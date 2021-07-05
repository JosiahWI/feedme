# FeedMe, JosiahVanderzee 2021 (c)

import asyncio
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

    with open(f"{pathlib.Path(__file__).parent}/token.txt", "r") as token_file:
        bot_token = token_file.readline().strip()

    loop = asyncio.get_running_loop()
    async with aiohttp.ClientSession(loop=loop) as session:
        setattr(bot, "session", session)
        await bot.start(bot_token)
    
asyncio.get_event_loop().run_until_complete(start())