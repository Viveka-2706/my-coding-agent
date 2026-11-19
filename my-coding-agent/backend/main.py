"""Web server: a WebSocket for the chat, plus a few simple HTTP endpoints."""
import asyncio
import io
import os
import zipfile

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

import chats
import checkpoints
from agent import WORKSPACE, build_system, run_agent, run_with_review, safe_path

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
checkpoints.setup()


# ---------- simple HTTP endpoints ----------
@app.get("/files")
def files():
    found = []
    for folder, dirs, names in os.walk(WORKSPACE):
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
        for name in names:
            found.append(os.path.relpath(os.path.join(folder, name), WORKSPACE))
    return sorted(found)


@app.get("/file")
def read_file(path: str):
    try:
        with open(safe_path(path), encoding="utf-8") as f:
            return {"path": path, "content": f.read()}
    except (ValueError, OSError, UnicodeDecodeError):
        raise HTTPException(400, "This file cannot be shown")


@app.get("/download")
def download():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as z:
        for name in files():
            z.write(os.path.join(WORKSPACE, name), name)
    return Response(buffer.getvalue(), media_type="application/zip",
                    headers={"Content-Disposition": 'attachment; filename="workspace.zip"'})


@app.get("/chats")
def list_chats():
    return chats.list_chats()


@app.delete("/chats/{chat_id}")
def delete_chat(chat_id: str):
    chats.delete(chat_id)
    return {"ok": True}


# ---------- the chat ----------
@app.websocket("/ws")
async def chat_socket(ws: WebSocket):
    await ws.accept()
    chat = chats.new_chat(build_system())
    allowed = set()  # tools the user allowed for the whole session
    waiting = None   # holds the pending permission question
    task = None      # the agent turn that is running right now

    async def emit(event):
        """Send an event to the browser and keep it, so the chat can be replayed later."""
        if event["type"] != "token":
            chat["events"].append(event)
        await ws.send_json(event)

    async def ask(name, title, detail, is_diff):
        """Ask the browser for permission and wait for the answer."""
        nonlocal waiting
        if name in allowed:
            await emit({"type": "note", "text": f"Auto-allowed: {title}"})
            return True
        waiting = asyncio.get_running_loop().create_future()
        await ws.send_json({"type": "confirm", "title": title, "detail": detail, "diff": is_diff,
                            "can_always": name in ("write_file", "edit_file")})
        try:
            reply = await waiting
        finally:
            waiting = None
        if reply.get("always"):
            allowed.update(["write_file", "edit_file"])
        await emit({"type": "note", "text": f"{'Allowed' if reply.get('ok') else 'Denied'}: {title}"})
        return reply.get("ok") is True

    def rollback(start, text, note):
        """Drop the unfinished turn so the history sent to the model stays valid."""
        del chat["messages"][start:]
        chat["messages"] += [{"role": "user", "content": text}, {"role": "assistant", "content": note}]

    async def run_turn(text, review_on):
        start = len(chat["messages"])
        chat["messages"].append({"role": "user", "content": text})
        chat["events"].append({"type": "user", "text": text})
        if chat["title"] == "New chat":
            chat["title"] = text[:40]
        checkpoints.save("before: " + text)
        try:
            if review_on:
                await run_with_review(chat["messages"], start, text, emit, ask, checkpoints.pending_diff)
            else:
                await run_agent(chat["messages"], emit, ask)
        except asyncio.CancelledError:
            rollback(start, text, "Task stopped by the user.")
            await emit({"type": "stopped"})
        except Exception as e:
            rollback(start, text, f"Task failed: {e}")
            await emit({"type": "error", "text": str(e)})
        checkpoints.save("task: " + text)
        size = sum(len(str(m.get("content") or "")) + len(str(m.get("tool_calls") or ""))
                   for m in chat["messages"])
        await emit({"type": "usage", "tokens": size // 4})  # rough estimate: 4 characters per token
        await emit({"type": "done"})
        chats.save(chat)

    async def show_chat():
        await ws.send_json({"type": "history", "id": chat["id"], "title": chat["title"],
                            "events": chat["events"]})

    await show_chat()
    try:
        while True:
            data = await ws.receive_json()
            kind = data["type"]
            busy = task is not None and not task.done()

            if kind == "task" and not busy:
                review_on = bool(data.get("review")) and checkpoints.READY  # the reviewer needs Git
                task = asyncio.create_task(run_turn(data["text"], review_on))
            elif kind == "stop" and busy:
                task.cancel()
            elif kind == "confirm_reply" and waiting and not waiting.done():
                waiting.set_result(data)
            elif kind == "new" and not busy:
                chat = chats.new_chat(build_system())
                allowed.clear()
                await show_chat()
            elif kind == "open" and not busy:
                chat = chats.load(data["id"])
                chat["messages"][0] = {"role": "system", "content": build_system()}
                allowed.clear()
                await show_chat()
            elif kind == "undo" and not busy:
                worked, message = checkpoints.undo()
                if worked:
                    chat["messages"] += [
                        {"role": "user", "content": "[The user pressed Undo: the workspace files are back to how they were before the last task.]"},
                        {"role": "assistant", "content": "Understood."}]
                await emit({"type": "note", "text": message})
                await emit({"type": "files"})
                if chat["events"]:
                    chats.save(chat)
            elif kind == "upload" and not busy:
                try:
                    with open(safe_path(data["name"]), "w", encoding="utf-8") as f:
                        f.write(data["content"])
                    await emit({"type": "note", "text": f"Uploaded {data['name']} to the workspace"})
                except Exception as e:
                    await emit({"type": "error", "text": f"Upload failed: {e}"})
                await emit({"type": "files"})
    except WebSocketDisconnect:
        if task:
            task.cancel()
