from pathlib import Path
from io import BytesIO

from fastapi import Depends, FastAPI, HTTPException, Response
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import httpx

from app.auth import authenticate, current_user, login_response, logout_response, update_credentials
from app.db import add_log, db, init_db, json_dumps, json_loads, row_to_dict, utc_now
from app.schemas import BotCommand, ChangeCredentialsRequest, LoginRequest, Pan115QrRequest, Pan115SaveRequest, ProxyTestRequest, SearchRequest, SettingPayload, SubscriptionBulkDeleteRequest, SubscriptionCreate, SubscriptionUpdate, TelegramCodeLoginRequest, TelegramCodeRequest
from app.services.integrations import EmbyAdapter, Pan115Adapter, TelegramClientAdapter, TmdbAdapter
import qrcode
from app.services.monitor import monitor_service
from app.services.subscription import create_subscription, delete_subscription, delete_subscriptions, deliver_resource, get_subscription, list_subscriptions, result_matches_subscription, search_all_active_subscriptions, search_and_attach_resources, sync_subscriptions_with_emby, update_subscription

app = FastAPI(title="ToGo115")
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


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


@app.post("/api/auth/login")
async def login(payload: LoginRequest, response: Response) -> dict:
    if not authenticate(payload.username, payload.password):
        raise HTTPException(status_code=401, detail="账号或密码错误")
    login_response(response, payload.username)
    add_log("info", "auth", "用户登录成功", {"username": payload.username})
    return {"ok": True}


@app.post("/api/auth/logout")
async def logout(response: Response, user: dict = Depends(current_user)) -> dict:
    logout_response(response)
    add_log("info", "auth", "用户已退出", {"username": user["username"]})
    return {"ok": True}


@app.get("/api/auth/me")
async def me(user: dict = Depends(current_user)) -> dict:
    return user


@app.put("/api/auth/credentials")
async def credentials(payload: ChangeCredentialsRequest, response: Response, user: dict = Depends(current_user)) -> dict:
    update_credentials(payload.username, payload.password)
    login_response(response, payload.username)
    add_log("warning", "auth", "账号密码已修改", {"old_username": user["username"], "new_username": payload.username})
    return {"ok": True}


@app.get("/api/settings")
async def get_settings(user: dict = Depends(current_user)) -> dict:
    with db() as conn:
        rows = conn.execute("SELECT key, value, updated_at FROM settings").fetchall()
    return {row["key"]: {"value": json_loads(row["value"], {}), "updated_at": row["updated_at"]} for row in rows}


@app.put("/api/settings/{key}")
async def put_setting(key: str, payload: SettingPayload, user: dict = Depends(current_user)) -> dict:
    with db() as conn:
        conn.execute(
            """
            INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (key, json_dumps(payload.value), utc_now()),
        )
    add_log("info", "settings", "配置已保存", {"key": key})
    return {"ok": True}


@app.get("/api/subscriptions")
async def subscriptions(user: dict = Depends(current_user)) -> list[dict]:
    return list_subscriptions()


@app.post("/api/subscriptions/sync-emby")
async def sync_subscription_emby_status(user: dict = Depends(current_user)) -> dict:
    return await sync_subscriptions_with_emby()


@app.post("/api/subscriptions/search-all")
async def search_all_subscriptions(user: dict = Depends(current_user)) -> dict:
    return await search_all_active_subscriptions()


@app.post("/api/subscriptions/bulk-delete")
async def bulk_delete_subscriptions(payload: SubscriptionBulkDeleteRequest, user: dict = Depends(current_user)) -> dict:
    return {"ok": True, "deleted": delete_subscriptions(payload.ids)}


@app.post("/api/subscriptions")
async def post_subscription(payload: SubscriptionCreate, user: dict = Depends(current_user)) -> dict:
    return await create_subscription(payload)


@app.put("/api/subscriptions/{subscription_id}")
async def put_subscription(subscription_id: int, payload: SubscriptionUpdate, user: dict = Depends(current_user)) -> dict:
    try:
        return update_subscription(subscription_id, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.delete("/api/subscriptions/{subscription_id}")
async def remove_subscription(subscription_id: int, user: dict = Depends(current_user)) -> dict:
    delete_subscription(subscription_id)
    return {"ok": True}


@app.post("/api/subscriptions/{subscription_id}/search")
async def search_subscription(subscription_id: int, user: dict = Depends(current_user)) -> dict:
    if not get_subscription(subscription_id):
        raise HTTPException(status_code=404, detail="订阅不存在")
    results = await search_and_attach_resources(subscription_id)
    return {"ok": True, "count": len(results)}


@app.get("/api/resources")
async def resources(user: dict = Depends(current_user)) -> list[dict]:
    with db() as conn:
        rows = conn.execute(
            """
            SELECT r.*, s.title AS subscription_title
            FROM resources r
            JOIN subscriptions s ON s.id = r.subscription_id
            ORDER BY r.id DESC
            LIMIT 200
            """
        ).fetchall()
    return [row_to_dict(row) for row in rows]


@app.post("/api/resources/{resource_id}/deliver")
async def post_deliver_resource(resource_id: int, user: dict = Depends(current_user)) -> dict:
    return {"ok": await deliver_resource(resource_id)}


@app.post("/api/search")
async def manual_search(payload: SearchRequest, user: dict = Depends(current_user)) -> dict:
    add_log("info", "search", "手动搜索已提交", payload.model_dump())
    subscription_like = {
        "title": payload.title,
        "keywords": payload.keywords,
    }
    results = await TelegramClientAdapter().search_history(payload.title, payload.keywords)
    matched = [result for result in results if result_matches_subscription(subscription_like, result)]
    return {"results": [result.__dict__ for result in matched], "count": len(matched)}


@app.get("/api/tmdb/trending")
async def tmdb_trending(user: dict = Depends(current_user)) -> dict:
    return await TmdbAdapter().trending()


@app.get("/api/tmdb/search")
async def tmdb_search(q: str, media_type: str = "multi", user: dict = Depends(current_user)) -> dict:
    return {"results": await TmdbAdapter().search(q, media_type)}


@app.get("/api/tmdb/{media_type}/{tmdb_id}")
async def tmdb_detail(media_type: str, tmdb_id: int, user: dict = Depends(current_user)) -> dict:
    if media_type not in ("tv", "movie"):
        raise HTTPException(status_code=400, detail="不支持的媒体类型")
    return await TmdbAdapter().detail(media_type, tmdb_id)


@app.get("/api/emby/dashboard")
async def emby_dashboard(user: dict = Depends(current_user)) -> dict:
    return await EmbyAdapter().dashboard()


@app.get("/api/emby/image/{item_id}")
async def emby_image(item_id: str, user: dict = Depends(current_user)) -> StreamingResponse:
    content, media_type = await EmbyAdapter().image_response(item_id)
    return StreamingResponse(BytesIO(content), media_type=media_type)


@app.get("/api/emby/user-image/{user_id}")
async def emby_user_image(user_id: str, user: dict = Depends(current_user)) -> StreamingResponse:
    content, media_type = await EmbyAdapter().user_image_response(user_id)
    return StreamingResponse(BytesIO(content), media_type=media_type)


@app.post("/api/proxy/test")
async def proxy_test(payload: ProxyTestRequest, user: dict = Depends(current_user)) -> dict:
    import time

    targets = {"github": "https://github.com", "google": "https://www.google.com/generate_204"}
    results = {}
    proxy = payload.url if payload.url else None
    async with httpx.AsyncClient(proxy=proxy, timeout=10, follow_redirects=True) as client:
        for name, url in targets.items():
            started = time.perf_counter()
            try:
                res = await client.get(url)
                results[name] = {"ok": True, "status": res.status_code, "latency_ms": round((time.perf_counter() - started) * 1000)}
            except Exception as exc:
                results[name] = {"ok": False, "error": str(exc), "latency_ms": None}
    return {"results": results}


@app.post("/api/telegram/qr-login")
async def telegram_qr_login(user: dict = Depends(current_user)) -> dict:
    try:
        return await TelegramClientAdapter().qr_login_start()
    except Exception as exc:
        add_log("error", "telegram", "Telegram 扫码登录创建失败", {"error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/telegram/send-code")
async def telegram_send_code(payload: TelegramCodeRequest, user: dict = Depends(current_user)) -> dict:
    try:
        return await TelegramClientAdapter().send_login_code(payload.phone)
    except Exception as exc:
        add_log("error", "telegram", "Telegram 手机验证码发送失败", {"error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/telegram/code-login")
async def telegram_code_login(payload: TelegramCodeLoginRequest, user: dict = Depends(current_user)) -> dict:
    try:
        return await TelegramClientAdapter().sign_in_code(payload.phone, payload.code)
    except Exception as exc:
        add_log("error", "telegram", "Telegram 手机验证码登录失败", {"error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/telegram/status")
async def telegram_status(user: dict = Depends(current_user)) -> dict:
    return await TelegramClientAdapter().login_status()


@app.get("/api/telegram/dialogs")
async def telegram_dialogs(user: dict = Depends(current_user)) -> dict:
    return {"dialogs": await TelegramClientAdapter().dialogs()}


@app.post("/api/115/qr-login")
async def pan115_qr_login(payload: Pan115QrRequest, user: dict = Depends(current_user)) -> dict:
    try:
        return await Pan115Adapter().qr_login_start(payload.channel)
    except Exception as exc:
        add_log("error", "115", "115 扫码登录创建失败", {"error": str(exc)})
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/115/qrcode-image")
async def pan115_qrcode_image(uid: str, channel: str = "web", user: dict = Depends(current_user)) -> StreamingResponse:
    try:
        content, media_type = await Pan115Adapter().qrcode_image(uid, channel)
        return StreamingResponse(BytesIO(content), media_type=media_type)
    except Exception as exc:
        add_log("error", "115", "115 二维码图片生成失败", {"error": str(exc), "uid": uid, "channel": channel})
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/115/status")
async def pan115_status(user: dict = Depends(current_user)) -> dict:
    return await Pan115Adapter().qr_login_status()


@app.get("/api/115/folders")
async def pan115_folders(cid: str = "0", user: dict = Depends(current_user)) -> dict:
    try:
        return await Pan115Adapter().list_folders(cid)
    except Exception as exc:
        add_log("error", "115", "115 目录列表获取失败", {"error": str(exc), "cid": cid})
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/115/save")
async def pan115_save(payload: Pan115SaveRequest, user: dict = Depends(current_user)) -> dict:
    ok = await Pan115Adapter().transfer(payload.link, payload.target_path)
    return {"ok": ok}


@app.get("/api/logs")
async def logs(mode: str = "simple", user: dict = Depends(current_user)) -> list[dict]:
    levels = ("info", "warning", "error") if mode != "debug" else ("debug", "info", "warning", "error")
    placeholders = ",".join("?" for _ in levels)
    with db() as conn:
        rows = conn.execute(f"SELECT * FROM logs WHERE level IN ({placeholders}) ORDER BY id DESC LIMIT 200", levels).fetchall()
    return [row_to_dict(row) for row in rows]


@app.post("/api/bot/command")
async def bot_command(payload: BotCommand) -> dict:
    command = payload.command.strip().lower()
    if command in ("/list", "list"):
        return {"subscriptions": list_subscriptions()}
    if command in ("/subscribe", "subscribe"):
        query = str(payload.args.get("query") or payload.args.get("title") or "").strip()
        if not query:
            raise HTTPException(status_code=400, detail="请传入 query，真实 TG Bot 会先返回候选列表供选择")
        return {"message": "请通过 Telegram Bot 发送“订阅 剧名”并在候选列表中确认订阅", "query": query}
    if command in ("/cancel", "cancel"):
        delete_subscription(int(payload.args["id"]))
        return {"ok": True}
    return {"error": "未知命令"}
