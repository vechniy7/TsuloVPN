import asyncio
import logging
import warnings

import coloredlogs
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from config import config
from config_pool import close_session, start_refresh_loop
from database import init_db, update_admins_status
from handlers import setup_handlers
from subscription_server import app as subscription_app

warnings.filterwarnings("ignore", category=DeprecationWarning)
coloredlogs.install(level="info")
logger = logging.getLogger(__name__)


async def setup_bot_commands(bot: Bot) -> None:
    commands = [
        BotCommand(command="start", description="Главная"),
        BotCommand(command="key", description="Мой ключ"),
        BotCommand(command="help", description="Инструкция"),
    ]
    await bot.set_my_commands(commands)


async def run_subscription_server() -> None:
    server_config = uvicorn.Config(
        subscription_app,
        host="0.0.0.0",
        port=config.SUBSCRIPTION_PORT,
        log_level="info",
        access_log=True,
    )
    server = uvicorn.Server(server_config)
    await server.serve()


async def main() -> None:
    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN is not set in .env")
        return

    if not config.use_upstash:
        logger.error("Configure UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN")
        return

    await init_db()
    await update_admins_status()

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()
    setup_handlers(dp)
    await setup_bot_commands(bot)

    await bot.delete_webhook(drop_pending_updates=True)

    asyncio.create_task(start_refresh_loop())
    asyncio.create_task(run_subscription_server())

    logger.info(
        "%s started (Upstash, %s configs per key)",
        config.BOT_NAME,
        config.SUBSCRIPTION_CONFIG_LIMIT,
    )
    try:
        await dp.start_polling(bot, drop_pending_updates=True)
    finally:
        await close_session()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopping...")
