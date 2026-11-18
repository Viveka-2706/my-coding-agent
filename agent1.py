from dotenv import load_dotenv
load_dotenv()
import json
import os

import subprocess
import platform
from groq import Groq

client = Groq()
MODEL = "openai/gpt-oss-120b"  # check Groq's docs for current tool-use models

# The agent can only touch files inside this folder
WORKSPACE = os.path.abspath("workspace")
os.makedirs(WORKSPACE, exist_ok=True)

SYSTEM = (
    "You are a coding agent working inside a project folder. "
    "Use the tools to list, read, create and edit files, and to run commands. "
    "Prefer edit_file for small changes. After making changes, run the code to verify it works. "
    "When the task is done, reply with a short summary. "
    "If the user denies an action, do not try to work around it; briefly say what was not done and ask how they want to proceed. "
    f"You are running on {platform.system()} using the {'cmd.exe' if platform.system() == 'Windows' else 'sh'} shell. "
    "Use commands that work in that shell. Do not use heredocs. "
    "For short Python snippets use: python -c \"...\"; for anything longer, write a .py file and run it."
)

# ---------- helpers ----------
def safe_path(p):
    full = os.path.abspath(os.path.join(WORKSPACE, p))
    if os.path.commonpath([WORKSPACE, full]) != WORKSPACE:
        raise ValueError("Path is outside the workspace")
    return full

def confirm(description):
    ok = input(f"  Allow {description}? [y/N] ").strip().lower() == "y"
    if not ok:
        print("  -> Denied")
    return ok

# ---------- tool functions ----------
def read_file(path):
    with open(safe_path(path), "r", encoding="utf-8") as f:
        return f.read()

def list_dir(path="."):
    items = os.listdir(safe_path(path))
    return "\n".join(items) if items else "(empty folder)"

def write_file(path, content):
    if not confirm(f"writing file '{path}'"):
        return "User denied this action."
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
    if not confirm(f"editing file '{path}'"):
        return "User denied this action."
    with open(full, "w", encoding="utf-8") as f:
        f.write(text.replace(old, new))
    return f"Edited {path}"

def run_bash(command):
    if not confirm(f"running command: {command}"):
        return "User denied this action."
    try:
        r = subprocess.run(command, shell=True, cwd=WORKSPACE,
                           capture_output=True, text=True, timeout=30)
        return (r.stdout + r.stderr).strip() or "(no output)"
    except subprocess.TimeoutExpired:
        return "Error: command timed out after 30 seconds"

# ---------- tool registry ----------
def tool(name, desc, props, required):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object",
                       "properties": {k: {"type": "string", "description": v}
                                      for k, v in props.items()},
                       "required": required}}}

TOOLS = [
    tool("read_file", "Read a text file", {"path": "File path"}, ["path"]),
    tool("list_dir", "List files in a folder", {"path": "Folder path, default '.'"}, []),
    tool("write_file", "Create or overwrite a file",
         {"path": "File path", "content": "Full file content"}, ["path", "content"]),
    tool("edit_file", "Replace one exact piece of text in a file",
         {"path": "File path", "old": "Exact text to replace (must be unique)",
          "new": "Replacement text"}, ["path", "old", "new"]),
    tool("run_bash", "Run a shell command in the workspace",
         {"command": "The command to run"}, ["command"]),
]

FUNCTIONS = {"read_file": read_file, "list_dir": list_dir, "write_file": write_file,
             "edit_file": edit_file, "run_bash": run_bash}

def execute_tool(name, args):
    if name not in FUNCTIONS:
        return f"Unknown tool: {name}"
    return FUNCTIONS[name](**args)

# ---------- the agent loop ----------
def run_agent(messages, max_steps=20):
    for _ in range(max_steps):
        resp = client.chat.completions.create(
            model=MODEL, messages=messages, tools=TOOLS, tool_choice="auto"
        )
        msg = resp.choices[0].message

        assistant = {"role": "assistant", "content": msg.content or ""}
        if msg.tool_calls:
            assistant["tool_calls"] = [
                {"id": c.id, "type": "function",
                 "function": {"name": c.function.name,
                              "arguments": c.function.arguments}}
                for c in msg.tool_calls
            ]
        messages.append(assistant)

        if not msg.tool_calls:
            return msg.content

        for call in msg.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
                print(f"  [tool] {call.function.name}({str(args)[:100]})")
                out = execute_tool(call.function.name, args)
            except Exception as e:
                out = f"Error: {e}"
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": str(out)[:10000]})
    return "Stopped: max steps reached"

if __name__ == "__main__":
    messages = [{"role": "system", "content": SYSTEM}]
    print(f"Agent ready. Working folder: {WORKSPACE}\nType 'exit' to quit.")
    while True:
        task = input("\n> ")
        if task.strip().lower() == "exit":
            break
        messages.append({"role": "user", "content": task})
        print("\n" + run_agent(messages))