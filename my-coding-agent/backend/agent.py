"""The agent: system prompt, tools and the loop (same idea as agent1.py)."""
import asyncio
import difflib
import json
import os
import platform
import re
import subprocess
import urllib.request

from dotenv import load_dotenv
from groq import AsyncGroq, RateLimitError

load_dotenv()
client = AsyncGroq()  # reads GROQ_API_KEY from backend/.env
# The reviewer can use its own Groq key (its own rate limits). Without one it shares the coder's key.
REVIEW_KEY = os.getenv("REVIEW_GROQ_API_KEY")
review_client = AsyncGroq(api_key=REVIEW_KEY) if REVIEW_KEY else client
MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
REVIEW_MODEL = os.getenv("REVIEW_MODEL", MODEL)  # the reviewer can use a different model

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
    "When searching with grep, use simple patterns without anchors like ^ or $, because code can be indented. "
    "If a search finds little, try a simpler pattern before answering. "
    "A word like @cart.py in the user's message means a file in the workspace: read it first. "
    "Use fetch_url only when the user asks for information from the web. "
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
    items = [i for i in os.listdir(safe_path(path)) if i != ".git"]
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
        dirs[:] = [d for d in dirs if d not in ("__pycache__", ".git")]
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


def fetch_url(url):
    if not url.startswith(("http://", "https://")):
        return "Error: only http and https addresses are allowed"
    request = urllib.request.Request(url, headers={"User-Agent": "my-coding-agent"})
    with urllib.request.urlopen(request, timeout=10) as r:
        html = r.read(300_000).decode("utf-8", errors="replace")
    text = re.sub(r"(?s)<(script|style).*?</\1>", " ", html)  # drop scripts and styles
    text = re.sub(r"<[^>]+>", " ", text)                      # drop the remaining tags
    return re.sub(r"\s+", " ", text).strip()[:6000]


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
    tool("fetch_url", "Download a web page and return its text",
         {"url": "The http or https address"}, ["url"]),
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
             "fetch_url": fetch_url, "update_todos": update_todos}

# These tools change things or reach outside, so the user must approve them first
NEEDS_PERMISSION = {"write_file", "edit_file", "run_bash", "fetch_url"}


def permission_text(name, args):
    """Returns (title, detail, is_diff) for the approval card."""
    if name == "run_bash":
        return "Run command", args.get("command", ""), False
    if name == "fetch_url":
        return "Fetch web page", args.get("url", ""), False
    path = args.get("path", "")
    full = safe_path(path)  # blocks paths outside the workspace before asking
    if name == "write_file":
        content = args.get("content", "")
        if not os.path.exists(full):
            return f"Create file {path}", content, False
        with open(full, encoding="utf-8", errors="replace") as f:
            old = f.read()
        diff = list(difflib.unified_diff(old.splitlines(), content.splitlines(), lineterm="", n=2))
        return f"Overwrite file {path}", "\n".join(diff[2:]) or "(no changes)", True
    removed = "\n".join("- " + line for line in args.get("old", "").splitlines())
    added = "\n".join("+ " + line for line in args.get("new", "").splitlines())
    return f"Edit file {path}", removed + "\n" + added, True


async def execute_tool(name, args, ask):
    if name not in FUNCTIONS:
        return f"Error: unknown tool '{name}'. Available tools: {', '.join(FUNCTIONS)}"
    if name in NEEDS_PERMISSION:
        title, detail, is_diff = permission_text(name, args)
        if not await ask(name, title, detail, is_diff):
            return "User denied this action."
    return await asyncio.to_thread(FUNCTIONS[name], **args)


# ---------- context management ----------
def trim_context(messages, keep_last=6, max_chars=300):
    """Shorten old tool results so long sessions stay within token limits."""
    cutoff = len(messages) - keep_last
    for i, m in enumerate(messages):
        if i < cutoff and m["role"] == "tool" and len(m["content"]) > max_chars:
            m["content"] = m["content"][:max_chars] + " ...[truncated]"


# ---------- talking to the model ----------
async def with_retry(call, send):
    """Run an API call. If Groq says 'too many requests', wait and try again."""
    for attempt in range(4):
        try:
            return await call()
        except RateLimitError:
            if attempt == 3:
                raise
            wait = 5 * 2 ** attempt
            await send({"type": "note", "text": f"Groq rate limit reached. Retrying in {wait} seconds..."})
            await asyncio.sleep(wait)


async def call_model(messages, send):
    """Start a streaming request to the coder model."""
    return await with_retry(lambda: client.chat.completions.create(
        model=MODEL, messages=messages, tools=TOOLS, tool_choice="auto", stream=True), send)


# ---------- the agent loop ----------
async def run_agent(messages, send, ask, max_steps=20):
    for _ in range(max_steps):
        trim_context(messages)
        stream = await call_model(messages, send)

        content = ""
        calls = {}  # tool calls arrive in small pieces, so collect them by index
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                content += delta.content
                await send({"type": "token", "text": delta.content})
            for piece in delta.tool_calls or []:
                call = calls.setdefault(piece.index, {"id": "", "name": "", "arguments": ""})
                call["id"] = piece.id or call["id"]
                if piece.function:
                    call["name"] = piece.function.name or call["name"]
                    call["arguments"] += piece.function.arguments or ""
        if content:
            await send({"type": "answer", "text": content})

        assistant = {"role": "assistant", "content": content}
        if calls:
            assistant["tool_calls"] = [
                {"id": c["id"], "type": "function",
                 "function": {"name": c["name"], "arguments": c["arguments"]}}
                for c in calls.values()]
        messages.append(assistant)

        if not calls:
            return

        for call in calls.values():
            name = call["name"]
            try:
                args = json.loads(call["arguments"] or "{}")
                if name == "update_todos":
                    await send({"type": "todos", "todos": args.get("todos", [])})
                else:
                    await send({"type": "tool", "name": name, "args": args})
                out = await execute_tool(name, args, ask)
            except Exception as e:
                out = f"Error: {e}"
            if name != "update_todos":
                await send({"type": "result", "output": str(out)[:3000]})
            messages.append({"role": "tool", "tool_call_id": call["id"], "content": str(out)[:10000]})
    await send({"type": "note", "text": "Stopped: reached the step limit for one task."})


# ---------- the reviewer agent ----------
REVIEW_SYSTEM = (
    "You are a strict but fair code reviewer. You get the user's request, the changes the coder made "
    "(a git diff) and the output of the commands the coder ran. Check: does it do what was asked, "
    "are there bugs or missing edge cases, did the tests (if any) pass, is anything unsafe. "
    "Reply in this format: the first line is exactly APPROVED or CHANGES NEEDED. "
    "Then give at most 5 short lines, each starting with '- '. Do not rewrite the code. "
    "If everything is fine, write APPROVED and one line saying why."
)


def command_outputs(messages):
    """Output of the shell commands the coder ran (this shows the reviewer if tests passed)."""
    names, outputs = {}, []
    for m in messages:
        for c in m.get("tool_calls", []):
            names[c["id"]] = c["function"]["name"]
        if m["role"] == "tool" and names.get(m["tool_call_id"]) == "run_bash":
            outputs.append(m["content"][:500])
    return "\n---\n".join(outputs[-3:]) or "(no commands were run)"


async def review(request, diff, outputs, send):
    """A second agent checks the coder's work. Returns (approved, feedback)."""
    prompt = (f"User request:\n{request}\n\nChanges (git diff):\n{diff[:6000]}\n\n"
              f"Command output:\n{outputs}")
    resp = await with_retry(lambda: review_client.chat.completions.create(
        model=REVIEW_MODEL,
        messages=[{"role": "system", "content": REVIEW_SYSTEM}, {"role": "user", "content": prompt}]), send)
    text = (resp.choices[0].message.content or "").strip()
    verdict = text.upper()[:40]
    approved = "APPROVED" in verdict and "CHANGES" not in verdict
    feedback = "\n".join(text.splitlines()[1:]).strip() or text
    return approved, feedback


async def run_with_review(messages, start, request, send, ask, get_diff):
    """The coder works, then the reviewer checks the changes. At most one fix round."""
    await run_agent(messages, send, ask)
    for round_number in range(2):
        diff = get_diff()
        if not diff:
            return  # nothing changed, so there is nothing to review
        await send({"type": "reviewing"})
        try:
            approved, feedback = await review(request, diff, command_outputs(messages[start:]), send)
        except Exception as e:  # a failing reviewer must never break the task
            await send({"type": "error", "text": f"Reviewer unavailable: {e}"})
            return
        await send({"type": "review", "approved": approved, "text": feedback})
        if approved or round_number == 1:
            return
        messages.append({"role": "user", "content":
                         "A reviewer checked your work and found problems:\n" + feedback +
                         "\nFix these issues, then reply with a short summary."})
        await run_agent(messages, send, ask)
