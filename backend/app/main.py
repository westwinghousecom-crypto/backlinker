import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core import logfilter, requestlog
from app.core.config import get_settings
from app.features.account.router import router as account_router
from app.features.diagnostics.router import router as diagnostics_router
from app.features.diagnostics.worker import check_worker
from app.features.discovery.pinger import discovery_pinger
from app.features.discovery.router import router as discovery_router
from app.features.google.router import router as google_router
from app.features.google.worker import gsc_worker
from app.features.health.router import router as health_router
from app.features.indexing.worker import background_worker
from app.features.proxy.rotator import FreeProxyRotator
from app.features.retention.service import retention_loop
from app.features.submissions.router import router as submissions_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logfilter.install()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    rotator = FreeProxyRotator() if settings.USE_PROXY else None
    tasks = [
        asyncio.create_task(background_worker(f"worker-{i + 1}", rotator), name=f"worker-{i + 1}")
        for i in range(max(settings.WORKER_COUNT, 0))
    ]
    tasks += [
        asyncio.create_task(check_worker(f"check-worker-{i + 1}"), name=f"check-worker-{i + 1}")
        for i in range(max(settings.CHECK_WORKER_COUNT, 0))
    ]
    if settings.google_configured:
        tasks += [
            asyncio.create_task(gsc_worker(f"gsc-worker-{i + 1}"), name=f"gsc-worker-{i + 1}")
            for i in range(max(settings.GSC_WORKER_COUNT, 0))
        ]
    tasks.append(asyncio.create_task(discovery_pinger(), name="discovery-pinger"))
    tasks.append(asyncio.create_task(retention_loop(), name="retention"))  # once a day; nearly free when idle
    try:
        yield
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="QuickIndex API", version="0.1.0", lifespan=lifespan)

requestlog.install(app)  # added before CORS so CORS stays outermost and error responses still carry its headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID"],
)

app.include_router(health_router)
app.include_router(discovery_router)
app.include_router(diagnostics_router)
app.include_router(account_router)
app.include_router(google_router)
app.include_router(submissions_router)