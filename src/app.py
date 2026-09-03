import asyncio
import logging
import warnings

import coloredlogs
import uvicorn
from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand, MenuButtonWebApp, WebAppInfo

from bot_notify import set_bot
from bot_profile import restore_bot_profile
from config import config
from pool_engine_v3 import POOL_ENGINE_VERSION, close_session, start_refresh_loop
from database import init_db, update_admins_status
from handlers import setup_handlers
from ssl_check import log_public_url_ssl
from subscription_server import app as subscription_app
from telegram_webhook import (
    bind_telegram,
    create_bot,
    maintain_webhook,
    router as telegram_router,
)

warnings.filterwarnings("ignore", category=DeprecationWarning)
coloredlogs.install(level="info")
logger = logging.getLogger(__name__)


async def setup_bot_commands(bot: Bot) -> None:
    commands = [
        BotCommand(command="start", description="Главная"),
        BotCommand(command="access", description="Мой доступ / ключ"),
        BotCommand(command="help", description="Инструкция"),
        BotCommand(command="tariffs", description="Тарифы"),
        BotCommand(command="docs", description="Документы"),
    ]
    await bot.set_my_commands(commands)
    miniapp = config.miniapp_url
    if miniapp.lower().startswith("https://"):
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(text="Кабинет", web_app=WebAppInfo(url=miniapp))
        )


async def _telegram_bootstrap(bot: Bot) -> None:
    # Amvera не достучится до api.telegram.org — любые setMyCommands/setWebhook
    # только жгут таймауты и мешают принимать входящий webhook.
    if config.telegram_webhook_enabled():
        await maintain_webhook(bot)
        return
    try:
        await asyncio.wait_for(setup_bot_commands(bot), timeout=15)
    except Exception as exc:
        logger.warning("Bot commands setup failed: %s", exc)
    await restore_bot_profile(bot)
    try:
        await asyncio.wait_for(bot.delete_webhook(drop_pending_updates=True), timeout=15)
    except Exception as exc:
        logger.warning("delete_webhook failed: %s", exc)


async def run_subscription_server() -> None:
    server_config = uvicorn.Config(
        subscription_app,
        host="0.0.0.0",
        port=config.SUBSCRIPTION_PORT,
        log_level="warning",
        access_log=False,
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

    await init_db()
    asyncio.create_task(update_admins_status())

    bot = create_bot()
    set_bot(bot)
    dp = Dispatcher()
    setup_handlers(dp)
    bind_telegram(dp, bot)
    subscription_app.include_router(telegram_router)

    asyncio.create_task(start_refresh_loop())
    asyncio.create_task(_telegram_bootstrap(bot))

    mode = (
        f"webhook {config.telegram_webhook_url()}"
        if config.telegram_webhook_enabled()
        else "polling"
    )
    logger.info(
        "%s started (Upstash, %s configs, Telegram %s%s%s%s)",
        config.BOT_NAME,
        config.SUBSCRIPTION_CONFIG_LIMIT,
        mode,
        ", Platega ON" if config.use_platega else "",
        ", payments ON" if config.payments_active else "",
        f", channel gate {config.required_channel_id}" if config.channel_gate_enabled else "",
    )
    logger.info("Pool engine v%s — private JSON passthrough enabled", POOL_ENGINE_VERSION)

    if config.telegram_webhook_enabled():
        await run_subscription_server()
        return

    asyncio.create_task(run_subscription_server())
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
