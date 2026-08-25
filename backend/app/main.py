"""财务流水自动入账 · 数据中台 FastAPI 入口。

分层架构落地（《执行方案》第 6 章）：
  采集适配层  app/adapters   （可插拔数据源：Mock / 文件 / API 预留）
  中台核心层  app/services   （入库 / 校验 / 复核 / 推送 / 审计）
  对接层      app/services/kingdee（金蝶 OpenAPI，凭据未就绪时 Mock）
  展现层      前端 Web 复核台（经 /api/* 调用，静态资源可选挂载）
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app import models  # noqa: F401  注册全部 ORM 模型
from app.api import auth, dashboard, push, review, settings as settings_api, trace
from app.ingest.api import router as ingest_router
from app.core.config import settings
from app.core.database import Base, SessionLocal, engine
from app.core.seed import ensure_seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 开发期：建表 + 播种维表/初始管理员（生产由运维用 schema SQL 建库，此处幂等）
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_seed(db)
    finally:
        db.close()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

for router_module in (auth, review, push, dashboard, trace, settings_api):
    app.include_router(router_module.router)
app.include_router(ingest_router)


@app.get("/api/health")
def health():
    return {"status": "ok", "app": settings.app_name, "environment": settings.environment}


# 前后端分离：前端静态目录位于项目根 frontend/（内网零构建，由 FastAPI 托管）
_static_dir = Path(__file__).resolve().parents[2] / "frontend"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="web")