import asyncio
import logging
import warnings

import coloredlogs
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo

from bot_notify import set_bot
from bot_profile import profile_update_loop, update_bot_user_count
from config import config, requires_happ_hwid
from pool_engine_v3 import POOL_ENGINE_VERSION, close_session, start_refresh_loop
from database import init_db, update_admins_status
from handlers import setup_handlers
from ssl_check import log_public_url_ssl
from subscription_server import app as subscription_app

warnings.filterwarnings("ignore", category=DeprecationWarning)
coloredlogs.install(level="info")
logger = logging.getLogger(__name__)


async def setup_bot_commands(bot: Bot) -> None:
    commands = [
        BotCommand(command="start", description="Главная"),
        BotCommand(command="access", description="Мой доступ"),
        BotCommand(command="help", description="Подключение"),
        BotCommand(command="donate", description="Поддержать проект"),
    ]
    await bot.set_my_commands(commands)
    miniapp = config.miniapp_url
    if miniapp.lower().startswith("https://"):
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Кабинет", web_app=WebAppInfo(url=miniapp))
        )


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
    if POOL_ENGINE_VERSION < 4:
        logger.error(
            "Stale pool engine on server (v%s). Redeploy from GitHub main without merge.",
            POOL_ENGINE_VERSION,
        )
        return

    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN is not set in .env")
        return

    if not config.use_upstash:
        logger.error("Configure UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN")
        return

    log_public_url_ssl(config.SUBSCRIPTION_PUBLIC_URL)

    source_url = config.resolved_source_url()
    if requires_happ_hwid(source_url):
        if config.upstream_proxy_configured():
            logger.info(
                "Upstream HWID panel (%s): fetch via proxy %s",
                config.source_label(),
                config.upstream_proxy_label(),
            )
        else:
            logger.warning(
                "Upstream HWID panel (%s) without UPSTREAM_PROXY_URL — "
                "requests go from server IP (high ban risk on eu-fffast)",
                config.source_label(),
            )

    await init_db()
    await update_admins_status()

    bot = Bot(token=config.BOT_TOKEN)
    set_bot(bot)
    dp = Dispatcher()
    setup_handlers(dp)
    await setup_bot_commands(bot)
    await update_bot_user_count(bot)

    await bot.delete_webhook(drop_pending_updates=True)

    asyncio.create_task(start_refresh_loop())
    asyncio.create_task(run_subscription_server())
    asyncio.create_task(profile_update_loop(bot))

    logger.info(
        "%s started (Upstash, %s configs, primary subscription%s%s)",
        config.BOT_NAME,
        config.SUBSCRIPTION_CONFIG_LIMIT,
        ", Cardlink ON" if config.use_cardlink else "",
        f", channel gate {config.required_channel_id}" if config.channel_gate_enabled else "",
    )
    logger.info("Pool engine v%s — private JSON passthrough enabled", POOL_ENGINE_VERSION)
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
