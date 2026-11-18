# My Coding Agent

A small AI coding agent with a React chat UI and a Python (FastAPI) backend, powered by Groq.
It works like a mini Claude Code: you describe a task, and the agent plans it, reads and writes
files, runs commands, and asks your permission before it changes anything.

## How to run (Windows)

You need Python 3.10+, Node.js 18+ and a Groq API key.

**1. Backend** (first terminal)

```cmd
cd backend
pip install -r requirements.txt
copy .env.example .env
```

Open `backend\.env` and replace the placeholder with your real Groq key, then start the server:

```cmd
uvicorn main:app --port 8000
```

**2. Frontend** (second terminal)

```cmd
cd frontend
npm install
npm run dev
```

Open http://localhost:5173 in your browser.

If the model name is rejected, run `python -c "from groq import Groq; print([m.id for m in Groq().models.list().data])"`
inside `backend` and set `GROQ_MODEL=` in `.env` to one of the names it prints.

## Things to try

- `create primes.py that prints the first 10 primes, then run it`
- `build a to-do list module with add, remove and list functions, a test file, and run the tests`
- `find where add is defined` (uses the grep tool)

## How it works

```
Browser (React)  <--WebSocket-->  FastAPI (main.py)  -->  agent loop (agent.py)  -->  Groq model
                                                              |
                                                              +-->  tools inside workspace/
```

The agent loop in `backend/agent.py` is the core:

1. Send the conversation and the list of tools to the model.
2. If the model asks for tools, run them and add the results to the conversation.
3. Repeat until the model answers with plain text.

| Building block | Where |
| --- | --- |
| Agent loop | `run_agent` in `backend/agent.py` |
| Tools: read, list, write, edit, grep, run command | functions + `TOOLS` list in `agent.py` |
| Planning (todo list shown in the UI) | `update_todos` tool |
| Safety: workspace sandbox | `safe_path` blocks paths outside `workspace/` |
| Safety: permission before write, edit, run | `NEEDS_PERMISSION` + the Allow / Deny card in the UI |
| Context management | `trim_context` shortens old tool results |
| Project instructions | `workspace/AGENT.md` is added to the system prompt |
| Environment awareness | system prompt tells the model the OS and shell |
| Web server | `backend/main.py` (WebSocket chat + file list) |
| UI | `frontend/src/App.jsx` |

## Folder layout

```
my-coding-agent/
├── backend/      agent.py, main.py, requirements.txt, .env.example
├── frontend/     React app (Vite)
└── workspace/    the only folder the agent can touch (AGENT.md = project instructions)
```

## Push to GitHub

`.gitignore` already keeps `.env`, `node_modules` and agent-generated files out of Git.

```cmd
git init
git add .
git commit -m "AI coding agent with React UI"
git branch -M main
git remote add origin https://github.com/your-username/my-coding-agent.git
git push -u origin main
```
