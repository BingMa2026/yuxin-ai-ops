import asyncio
from collections.abc import AsyncGenerator
from contextlib import suppress
from typing import Any

from fastapi import FastAPI
from fastapi.concurrency import asynccontextmanager
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html, get_swagger_ui_oauth2_redirect_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from .config import path_conf
from .config.setting import settings
from .core.exceptions import handle_exception
from .core.logger import logger
from .utils.common_util import import_module
from .utils.console import console_end, console_start


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[Any, Any]:
    from app.api.v1.module_system.dict.service import DictDataService
    from app.api.v1.module_system.params.service import ParamsService
    from app.core.ap_scheduler import SchedulerUtil
    from app.core.database import async_engine, redis_connect
    from app.scripts.initialize import InitializeData

    await InitializeData().init_db()
    logger.info("✅ {}数据库初始化完成", settings.DATABASE_TYPE)
    await redis_connect(app, status=True)
    logger.info("✅ Redis 连接初始化完成")
    await ParamsService.init_cache(redis=app.state.redis)
    logger.info("✅ Redis系统参数初始化完成")
    await DictDataService.init_cache(redis=app.state.redis)
    logger.info("✅ Redis数据字典初始化完成")
    await SchedulerUtil.init_scheduler(redis=app.state.redis)
    logger.info("✅ 定时任务调度器初始化完成")

    console_start(
        host=settings.SERVER_HOST,
        port=settings.SERVER_PORT,
        reload=settings.DEBUG,
        database_type=settings.DATABASE_TYPE,
        database_ready=True,
        redis_ready=True,
        scheduler_ready=SchedulerUtil.is_running(),
    )

    from app.api.v1.module_model_gateway.settlement_worker import settlement_loop

    settlement_task = asyncio.create_task(settlement_loop())
    try:
        yield
    finally:
        settlement_task.cancel()
        with suppress(asyncio.CancelledError):
            await settlement_task

    try:
        from app.api.v1.module_model_gateway.gateway import close_provider_http_client

        SchedulerUtil.shutdown(wait=True)
        logger.info("✅ 定时任务调度器已关闭")
        await close_provider_http_client()
        logger.info("✅ 模型供应商 HTTP 连接池已关闭")
        await redis_connect(app, status=False)
        logger.info("✅ Redis 连接已关闭")
        await async_engine.dispose()
        logger.info("✅ 数据库引擎连接池已释放")
        console_end()
    except Exception as e:
        logger.error("❌ 应用关闭过程中发生错误: {}", e)
        raise SystemExit(1)


def register_middlewares(app: FastAPI) -> None:
    for middleware in settings.MIDDLEWARE_LIST[::-1]:
        if not middleware:
            continue
        middleware = import_module(middleware, desc="中间件")
        app.add_middleware(middleware)


def register_exceptions(app: FastAPI) -> None:
    handle_exception(app)


def register_routers(app: FastAPI) -> None:
    from app.api.v1.module_agreement.controller import agreement_admin_router, agreement_public_router
    from app.api.v1.module_billing import billing_client_router, billing_operations_router
    from app.api.v1.module_client import client_public_router, client_update_public_router, operations_client_router
    from app.api.v1.module_common import common_router
    from app.api.v1.module_finance.controller import finance_client_router, finance_router
    from app.api.v1.module_generator import generator_router
    from app.api.v1.module_growth.controller import growth_admin_router, growth_client_router, growth_public_router
    from app.api.v1.module_model_gateway import model_client_router, model_operations_router
    from app.api.v1.module_monitor import monitor_router
    from app.api.v1.module_operations import operations_router
    from app.api.v1.module_payment import payment_callback_router, payment_client_router, payment_router
    from app.api.v1.module_speech.controller import speech_admin_router, speech_client_router
    from app.api.v1.module_storage import storage_router
    from app.api.v1.module_system import system_router
    from app.api.v1.module_task import task_router
    from app.api.v1.module_telemetry import telemetry_client_router
    from app.api.v1.module_user_operations import user_operations_admin_router, user_operations_client_router

    app.include_router(common_router)
    app.include_router(speech_admin_router)
    app.include_router(speech_client_router)
    app.include_router(agreement_admin_router)
    app.include_router(agreement_public_router)
    app.include_router(finance_router)
    app.include_router(finance_client_router)
    app.include_router(operations_client_router)
    app.include_router(client_public_router)
    app.include_router(client_update_public_router)
    app.include_router(billing_operations_router)
    app.include_router(billing_client_router)
    app.include_router(model_operations_router)
    app.include_router(model_client_router)
    app.include_router(operations_router)
    app.include_router(monitor_router)
    app.include_router(system_router)
    app.include_router(generator_router)
    app.include_router(task_router)
    app.include_router(storage_router)
    app.include_router(payment_router)
    app.include_router(payment_client_router)
    app.include_router(payment_callback_router)
    app.include_router(telemetry_client_router)
    app.include_router(user_operations_admin_router)
    app.include_router(user_operations_client_router)
    app.include_router(growth_admin_router)
    app.include_router(growth_client_router)
    app.include_router(growth_public_router)

    from app.core.discover import dynamic_router

    dynamic_router.init_app(app)


def register_static(app: FastAPI) -> None:
    """注册静态文件路由。"""
    path_conf.STATIC_DIR.mkdir(parents=True, exist_ok=True)
    app.mount(path=settings.STATIC_URL, app=StaticFiles(directory=path_conf.STATIC_DIR), name=path_conf.STATIC_DIR.name)


def register_docs(app: FastAPI) -> None:
    """注册文档路由。"""
    swagger_ui_redirect_url = str(app.swagger_ui_oauth2_redirect_url)
    root_openapi_url = str(app.root_path) + str(app.openapi_url)

    @app.get(swagger_ui_redirect_url, include_in_schema=False)
    async def swagger_ui_redirect():
        return get_swagger_ui_oauth2_redirect_html()

    @app.get(settings.DOCS_URL, include_in_schema=False)
    async def custom_swagger_ui_html() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=root_openapi_url,
            title=app.title + " - Swagger UI",
            oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
            swagger_js_url=settings.SWAGGER_JS_URL,
            swagger_css_url=settings.SWAGGER_CSS_URL,
            swagger_favicon_url=settings.FAVICON_URL,
        )

    @app.get(settings.REDOC_URL, include_in_schema=False)
    async def custom_redoc_html():
        return get_redoc_html(
            openapi_url=root_openapi_url,
            title=app.title + " - ReDoc",
            redoc_js_url=settings.REDOC_JS_URL,
            redoc_favicon_url=settings.FAVICON_URL,
        )


def register_frontend(app: FastAPI) -> None:
    if path_conf.FRONTEND_DIST_DIR.exists():
        app.mount("/web", StaticFiles(directory=str(path_conf.FRONTEND_DIST_DIR), html=True), name="frontend")
