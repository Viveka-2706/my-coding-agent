"""The agent: system prompt, tools and the loop (same idea as agent1.py)."""
import asyncio
import json
import os
import platform
import re
import subprocess

from dotenv import load_dotenv
from groq import AsyncGroq

load_dotenv()
client = AsyncGroq()  # reads GROQ_API_KEY from backend/.env
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")

# The agent can only touch files inside this folder
WORKSPACE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "workspace"))
os.makedirs(WORKSPACE, exist_ok=True)

SYSTEM = (
    "You are a coding agent working inside a project folder. "
    "Use the tools to list, read, search, create and edit files, and to run commands. "
    "Prefer edit_file for small changes. After making changes, run the code to verify it works. "
    "When the task is done, reply with a short summary. "
    "If the user denies an action, do not work around it; say what was not done and ask how to proceed. "
    f"You are running on {platform.system()} using the {'cmd.exe' if platform.system() == 'Windows' else 'sh'} shell. "
    "Use commands that work in that shell. Do not use heredocs. "
    "For short Python snippets use: python -c \"...\"; for anything longer, write a .py file and run it. "
    "When searching with grep, use simple patterns without anchors like ^ or $, because code can be indented. If a search finds little, try a simpler pattern before answering. "
    "IMPORTANT: for any task that needs three or more steps, your very first action must be to call "
    "update_todos with the full plan. After finishing each step, call update_todos again with new statuses."
)


def build_system():
    """System prompt + optional project instructions from workspace/AGENT.md."""
    text = SYSTEM
    path = os.path.join(WORKSPACE, "AGENT.md")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            text += "\n\nProject instructions:\n" + f.read()
    return text


# ---------- tools ----------
def safe_path(p):
    full = os.path.abspath(os.path.join(WORKSPACE, p))
    if os.path.commonpath([WORKSPACE, full]) != WORKSPACE:
        raise ValueError("Path is outside the workspace")
    return full


def read_file(path):
    with open(safe_path(path), "r", encoding="utf-8") as f:
        return f.read()


def list_dir(path="."):
    items = os.listdir(safe_path(path))
    return "\n".join(items) if items else "(empty folder)"


def write_file(path, content):
    full = safe_path(path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Wrote {len(content)} characters to {path}"


def edit_file(path, old, new):
    full = safe_path(path)
    with open(full, "r", encoding="utf-8") as f:
        text = f.read()
    if text.count(old) != 1:
        return f"Error: 'old' text must appear exactly once, found {text.count(old)} times."
    with open(full, "w", encoding="utf-8") as f:
        f.write(text.replace(old, new))
    return f"Edited {path}"


def grep(pattern, path="."):
    results = []
    for folder, dirs, files in os.walk(safe_path(path)):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for name in files:
            full = os.path.join(folder, name)
            try:
                with open(full, encoding="utf-8") as f:
                    for n, line in enumerate(f, 1):
                        if re.search(pattern, line):
                            results.append(f"{os.path.relpath(full, WORKSPACE)}:{n}: {line.strip()}")
            except (UnicodeDecodeError, OSError):
                continue
    return "\n".join(results[:50]) or "No matches"


def run_bash(command):
    try:
        r = subprocess.run(command, shell=True, cwd=WORKSPACE, capture_output=True,
                           text=True, errors="replace", timeout=30)
        return (r.stdout + r.stderr).strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 30 seconds"


def update_todos(todos):
    return "Todo list updated."  # the UI shows the plan; nothing else to do


def tool(name, desc, props, required):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object",
                       "properties": {k: {"type": "string", "description": v} for k, v in props.items()},
                       "required": required}}}


TOOLS = [
    tool("read_file", "Read a text file", {"path": "File path"}, ["path"]),
    tool("list_dir", "List files in a folder", {"path": "Folder path, default '.'"}, []),
    tool("write_file", "Create or overwrite a file",
         {"path": "File path", "content": "Full file content"}, ["path", "content"]),
    tool("edit_file", "Replace one exact piece of text in a file",
         {"path": "File path", "old": "Exact text to replace (must be unique)",
          "new": "Replacement text"}, ["path", "old", "new"]),
    tool("grep", "Search all files for a regex pattern",
         {"pattern": "Regex to search for", "path": "Folder, default '.'"}, ["pattern"]),
    tool("run_bash", "Run a shell command in the workspace",
         {"command": "The command to run"}, ["command"]),
    {"type": "function", "function": {
        "name": "update_todos",
        "description": "Write or update a checklist for multi-step tasks.",
        "parameters": {"type": "object", "properties": {
            "todos": {"type": "array", "items": {"type": "object", "properties": {
                "task": {"type": "string"},
                "status": {"type": "string", "enum": ["pending", "in_progress", "done"]}},
                "required": ["task", "status"]}}},
            "required": ["todos"]}}},
]

FUNCTIONS = {"read_file": read_file, "list_dir": list_dir, "write_file": write_file,
             "edit_file": edit_file, "grep": grep, "run_bash": run_bash,
             "update_todos": update_todos}

# These tools change things, so the user must approve them first
NEEDS_PERMISSION = {"write_file", "edit_file", "run_bash"}


def permission_text(name, args):
    if name == "run_bash":
        return "Run command", args.get("command", "")
    if name == "write_file":
        return f"Write file {args.get('path')}", args.get("content", "")
    removed = "\n".join("- " + line for line in args.get("old", "").splitlines())
    added = "\n".join("+ " + line for line in args.get("new", "").splitlines())
    return f"Edit file {args.get('path')}", removed + "\n" + added


async def execute_tool(name, args, ask):
    if name not in FUNCTIONS:
        return f"Error: unknown tool '{name}'. Available tools: {', '.join(FUNCTIONS)}"
    if name in NEEDS_PERMISSION:
        title, detail = permission_text(name, args)
        if not await ask(title, detail):
            return "User denied this action."
    return await asyncio.to_thread(FUNCTIONS[name], **args)


# ---------- context management ----------
def trim_context(messages, keep_last=6, max_chars=300):
    """Shorten old tool results so long sessions stay within token limits."""
    cutoff = len(messages) - keep_last
    for i, m in enumerate(messages):
        if i < cutoff and m["role"] == "tool" and len(m["content"]) > max_chars:
            m["content"] = m["content"][:max_chars] + " ...[truncated]"


# ---------- the agent loop ----------
async def run_agent(messages, send, ask, max_steps=20):
    for _ in range(max_steps):
        trim_context(messages)
        resp = await client.chat.completions.create(
            model=MODEL, messages=messages, tools=TOOLS, tool_choice="auto")
        msg = resp.choices[0].message

        assistant = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant["tool_calls"] = [
                {"id": c.id, "type": "function",
                 "function": {"name": c.function.name, "arguments": c.function.arguments}}
                for c in msg.tool_calls]
        messages.append(assistant)

        if not msg.tool_calls:
            return msg.content or ""

        for call in msg.tool_calls:
            name = call.function.name
            try:
                args = json.loads(call.function.arguments or "{}")
                if name == "update_todos":
                    await send({"type": "todos", "todos": args.get("todos", [])})
                else:
                    await send({"type": "tool", "name": name, "args": args})
                out = await execute_tool(name, args, ask)
            except Exception as e:
                out = f"Error: {e}"
            if name != "update_todos":
                await send({"type": "result", "output": str(out)[:3000]})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": str(out)[:10000]})
    return "Stopped: max steps reached"
