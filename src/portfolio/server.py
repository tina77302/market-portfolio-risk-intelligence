import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.portfolio.analytics import load_snapshot_meta
from src.portfolio.api import router

# 포트폴리오 API를 단독으로 띄우는 앱입니다.
#   uvicorn src.portfolio.server:app --port 8000
# 메인 앱이 생기면 이 파일 대신 app.include_router(router)만 쓰면 됩니다.
DEFAULT_ORIGINS = "http://localhost:3000,http://127.0.0.1:3000"
CORS_ORIGINS = [
    o.strip()
    for o in os.getenv("PORTFOLIO_API_CORS_ORIGINS", DEFAULT_ORIGINS).split(",")
    if o.strip()
]

app = FastAPI(title="Portfolio Risk API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)
app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok", "as_of": load_snapshot_meta()["as_of"]}
