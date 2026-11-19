# My Coding Agent

An AI coding agent with a React chat UI and a Python (FastAPI) backend, powered by Groq.
You describe a task. The agent makes a plan, reads and writes files, runs commands and fixes errors,
and it asks your permission before it changes anything.

## How to run (Windows)

You need Python 3.10+, Node.js 18+, Git and a Groq API key.

**1. Backend** (first terminal)

```cmd
cd backend
pip install -r requirements.txt
copy .env.example .env
```

Open `backend\.env`, paste your Groq key, then start the server:

```cmd
uvicorn main:app --port 8000
```

**2. Frontend** (second terminal)

```cmd
cd frontend
npm install
npm run dev
```

Open http://localhost:5173.

If the model name is rejected, list the models your key can use
(`python -c "from groq import Groq; print([m.id for m in Groq().models.list().data])"` inside `backend`)
and set `GROQ_MODEL=` in `.env`.

## Features

| Feature | How it works |
| --- | --- |
| Agent loop | `run_agent` in `backend/agent.py`: ask the model, run the tools it requests, repeat until it answers |
| Tools | read, list, write, edit, grep, run command, fetch web page, todo plan |
| Streaming | The answer appears word by word (the model call uses `stream=True`) |
| Stop button | Cancels the running task; the chat history is repaired so you can keep going |
| Permissions | Writes, edits, commands and web fetches show an Allow / Deny card; file changes can be allowed for the session |
| Diffs | Edits and overwrites show red and green lines before you approve |
| Sandbox | File tools can only reach the `workspace/` folder (`safe_path`) |
| Planning | The `update_todos` tool fills the Plan panel with a progress bar |
| Chat history | Every chat is saved in `chats/` and can be reopened or deleted |
| Undo | `workspace/` is a small Git repo; a commit is made around each task, and Undo goes back one (`checkpoints.py`) |
| File viewer | Click a file in the right panel to read it with syntax colours |
| File upload | The paperclip copies a text file into the workspace and mentions it as `@file` |
| Slash commands, @mentions | `/new`, `/undo`, `/download`, and `@file` suggestions (Tab to complete) |
| Download | Gets the whole workspace as a zip |
| Rate-limit retry | If Groq says "too many requests", the agent waits and tries again |
| Context size | Old tool results are shortened (`trim_context`); the top bar shows a rough token count |
| Project instructions | `workspace/AGENT.md` is added to the system prompt |
| Light / dark mode | The button at the bottom of the left sidebar |

## How it works

```
Browser (React)  <--WebSocket-->  main.py  -->  agent.py (loop)  -->  Groq model
                                    |                |
                                    |                +--> tools, only inside workspace/
                                    +--> chats.py (saved chats)    checkpoints.py (undo)
```

## Folder layout

```
my-coding-agent/
├── backend/      agent.py, main.py, chats.py, checkpoints.py
├── frontend/     React app (Vite)
├── workspace/    the only folder the agent can touch (AGENT.md = project instructions)
└── chats/        saved chats (created automatically)
```

## Push to GitHub

`.gitignore` already keeps `.env`, `node_modules`, `chats/` and agent-made files out of Git.

```cmd
git init
git add .
git commit -m "AI coding agent with React UI"
git branch -M main
git remote add origin https://github.com/your-username/my-coding-agent.git
git push -u origin main
```
