"""Web server: one WebSocket per chat, plus a file list for the UI."""
import os

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from agent import WORKSPACE, build_system, run_agent

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/files")
def files():
    found = []
    for folder, dirs, names in os.walk(WORKSPACE):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in names:
            found.append(os.path.relpath(os.path.join(folder, name), WORKSPACE))
    return sorted(found)


@app.websocket("/ws")
async def chat(ws: WebSocket):
    await ws.accept()
    messages = [{"role": "system", "content": build_system()}]

    async def ask(title, detail):
        """Ask the browser for permission and wait for the answer."""
        await ws.send_json({"type": "confirm", "title": title, "detail": detail})
        reply = await ws.receive_json()
        return reply.get("ok") is True

    try:
        while True:
            data = await ws.receive_json()
            if data["type"] == "reset":
                messages = [{"role": "system", "content": build_system()}]
                continue
            if data["type"] != "task":
                continue
            messages.append({"role": "user", "content": data["text"]})
            try:
                answer = await run_agent(messages, ws.send_json, ask)
                await ws.send_json({"type": "answer", "text": answer})
            except Exception as e:
                await ws.send_json({"type": "error", "text": str(e)})
            await ws.send_json({"type": "done"})
    except WebSocketDisconnect:
        pass
