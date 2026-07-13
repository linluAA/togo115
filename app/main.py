from pathlib import Path
from io import BytesIO

from fastapi import Depends, FastAPI
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import qrcode

from app.auth import current_user
from app.db import init_db
from app.routers import auth, integrations, media, settings, subscriptions, system
from app.services.monitor import monitor_service

class AppStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        if path.endswith(".js"):
            response.headers["Content-Type"] = "text/javascript; charset=utf-8"
        elif path.endswith(".css"):
            response.headers["Content-Type"] = "text/css; charset=utf-8"
        return response


app = FastAPI(title="ToGo115")
static_dir = Path(__file__).parent / "static"
app.mount("/static", AppStaticFiles(directory=static_dir), name="static")
app.include_router(auth.router)
app.include_router(settings.router)
app.include_router(subscriptions.router)
app.include_router(media.router)
app.include_router(integrations.router)
app.include_router(system.router)


@app.on_event("startup")
async def startup() -> None:
    init_db()
    monitor_service.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await monitor_service.stop()


@app.get("/")
async def index() -> HTMLResponse:
    html = (static_dir / "index.html").read_text(encoding="utf-8")
    app_version = max(
        int((static_dir / "app.js").stat().st_mtime),
        int((static_dir / "styles.css").stat().st_mtime),
    )
    html = html.replace("/static/styles.css", f"/static/styles.css?v={app_version}")
    html = html.replace("/static/app.js", f"/static/app.js?v={app_version}")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True}


@app.get("/api/qr")
async def qr_image(data: str, user: dict = Depends(current_user)) -> StreamingResponse:
    image = qrcode.make(data)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    buffer.seek(0)
    return StreamingResponse(buffer, media_type="image/png")
