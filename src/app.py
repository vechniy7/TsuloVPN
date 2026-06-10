import asyncio
import logging
import warnings

import coloredlogs
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from config import config
from config_pool import close_session, start_refresh_loop
from database import Session, User, init_db
from handlers import setup_handlers
from subscription_server import app as subscription_app

warnings.filterwarnings("ignore", category=DeprecationWarning)
coloredlogs.install(level="info")
logger = logging.getLogger(__name__)


async def update_admins_status() -> None:
    with Session() as session:
        session.query(User).update({User.is_admin: False})
        for admin_id in config.ADMINS:
            user = session.query(User).filter_by(telegram_id=admin_id).first()
            if user:
                user.is_admin = True
        session.commit()


async def setup_bot_commands(bot: Bot) -> None:
    commands = [
        BotCommand(command="start", description="Запуск бота"),
        BotCommand(command="key", description="Получить VPN-ключ"),
        BotCommand(command="menu", description="Главное меню"),
        BotCommand(command="help", description="Как подключить"),
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

    await init_db()
    await update_admins_status()

    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()
    setup_handlers(dp)
    await setup_bot_commands(bot)

    # Сбрасываем webhook и конфликтующие сессии (важно при redeploy на Render)
    await bot.delete_webhook(drop_pending_updates=True)

    asyncio.create_task(run_subscription_server())
    asyncio.create_task(start_refresh_loop())

    logger.info("%s started (subscription port %s)", config.BOT_NAME, config.SUBSCRIPTION_PORT)
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
