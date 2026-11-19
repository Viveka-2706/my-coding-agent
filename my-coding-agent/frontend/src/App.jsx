import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import hljs from "highlight.js/lib/common";
import "./App.css";

const API = "http://localhost:8000";
const WS_URL = "ws://localhost:8000/ws";

const EXAMPLES = [
  { title: "Create and run a script", prompt: "Create primes.py that prints the first 10 prime numbers, then run it" },
  { title: "Build a module with tests", prompt: "Build a to-do list module with add, remove and list functions, a test file, and run the tests" },
  { title: "Search the code", prompt: "Find where the add function is defined" },
];

const COMMANDS = [
  { name: "/new", hint: "Start a new chat" },
  { name: "/undo", hint: "Undo the file changes of the last task" },
  { name: "/download", hint: "Download the workspace as a zip" },
];

// Short, readable name for each tool call
const LABEL = {
  read_file: (a) => `Read ${a.path}`,
  list_dir: (a) => `Listed ${a.path || "."}`,
  write_file: (a) => `Wrote ${a.path}`,
  edit_file: (a) => `Edited ${a.path}`,
  grep: (a) => `Searched for "${a.pattern}"`,
  run_bash: (a) => `Ran ${String(a.command).slice(0, 80)}`,
  fetch_url: (a) => `Fetched ${a.url}`,
};
const labelOf = (name, args) => (LABEL[name] ? LABEL[name](args) : name);
const prefix = (text, sign) =>
  String(text ?? "").split("\n").map((l) => `${sign} ${l}`).join("\n");

// ---------- how backend events change the chat ----------
// One pure function, used both for live events and for replaying a saved chat.
function applyEvent(items, m) {
  const last = items[items.length - 1];
  const streaming = last && last.kind === "answer" && last.streaming;
  switch (m.type) {
    case "user":
      return [...items, { kind: "user", text: m.text }];
    case "token": // a piece of the answer is arriving
      return streaming
        ? [...items.slice(0, -1), { ...last, text: last.text + m.text }]
        : [...items, { kind: "answer", text: m.text, streaming: true }];
    case "answer": // the full answer, replaces the streamed pieces
      return streaming
        ? [...items.slice(0, -1), { kind: "answer", text: m.text }]
        : [...items, { kind: "answer", text: m.text }];
    case "tool":
      return [...items, { kind: "tool", name: m.name, args: m.args }];
    case "result": {
      // attach the output to the most recent tool call that has none yet
      const copy = [...items];
      for (let i = copy.length - 1; i >= 0; i--) {
        if (copy[i].kind === "tool" && copy[i].output === undefined) {
          copy[i] = { ...copy[i], output: m.output };
          break;
        }
      }
      return copy;
    }
    case "note":
      return [...items, { kind: "note", text: m.text }];
    case "error":
      return [...items, { kind: "error", text: m.text }];
    case "stopped":
      return [
        ...items.map((it) => (it.streaming ? { ...it, streaming: false } : it)),
        { kind: "note", text: "Stopped." },
      ];
    default:
      return items;
  }
}

// ---------- small building blocks ----------
const ICONS = {
  sun: "M12 8a4 4 0 100 8 4 4 0 000-8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  moon: "M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z",
  send: "M5 12h14M13 6l6 6-6 6",
  stop: "M7 7h10v10H7z",
  plus: "M12 5v14M5 12h14",
  file: "M7 3h7l4 4v14H7zM14 3v4h4",
  chevron: "M6 9l6 6 6-6",
  paperclip: "M21.44 11.05l-9.19 9.19a6 6 0 01-8.49-8.49l9.19-9.19a4 4 0 015.66 5.66l-9.2 9.19a2 2 0 01-2.83-2.83l8.49-8.48",
  download: "M12 3v12M7 10l5 5 5-5M5 21h14",
  undo: "M1 4v6h6M3.51 15a9 9 0 102.13-9.36L1 10",
  close: "M6 6l12 12M18 6L6 18",
  panel: "M3 5h18v14H3zM15 5v14",
};

function Icon({ name, size = 18 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={ICONS[name]} />
    </svg>
  );
}

const Mark = ({ size = "sm" }) => <span className={`mark ${size}`}>{"</>"}</span>;

// Get the plain text out of a React node (used for the Copy button)
const textOf = (n) =>
  typeof n === "string" ? n
  : Array.isArray(n) ? n.map(textOf).join("")
  : n?.props ? textOf(n.props.children) : "";

function CodeBlock({ children }) {
  const [copied, setCopied] = useState(false);
  const lang = /language-([\w-]+)/.exec(children?.props?.className || "")?.[1];
  const copy = () => {
    navigator.clipboard.writeText(textOf(children).replace(/\n$/, ""));
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="code">
      <div className="code-head">
        <span>{lang || "code"}</span>
        <button onClick={copy}>{copied ? "Copied" : "Copy"}</button>
      </div>
      <pre>{children}</pre>
    </div>
  );
}

function Diff({ text }) {
  return (
    <pre className="diff">
      {text.split("\n").map((line, i) => (
        <div key={i} className={line.startsWith("+") ? "add" : line.startsWith("-") ? "del" : ""}>
          {line}
        </div>
      ))}
    </pre>
  );
}

function Tool({ it }) {
  const a = it.args || {};
  const out = it.output;
  const state = out === undefined ? "running" : /^(User denied|Error)/.test(out) ? "fail" : "ok";
  return (
    <details className="tool">
      <summary>
        <span className={`dot ${state}`} />
        <span className="tool-label">{labelOf(it.name, a)}</span>
        <span className="chev"><Icon name="chevron" size={16} /></span>
      </summary>
      <div className="tool-body">
        {it.name === "write_file" && <pre>{a.content}</pre>}
        {it.name === "edit_file" && <Diff text={`${prefix(a.old, "-")}\n${prefix(a.new, "+")}`} />}
        {out !== undefined && (
          <>
            <div className="small">Output</div>
            <pre>{out}</pre>
          </>
        )}
      </div>
    </details>
  );
}

function Answer({ it }) {
  const [copied, setCopied] = useState(false);
  const copy = () => {
    navigator.clipboard.writeText(it.text);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };
  return (
    <div className="agent-row">
      <Mark />
      <div className="agent-col">
        <div className="agent md">
          <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]} components={{ pre: CodeBlock }}>
            {it.text}
          </ReactMarkdown>
        </div>
        {!it.streaming && (
          <button className="link" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
        )}
      </div>
    </div>
  );
}

function Item({ it }) {
  if (it.kind === "user") return <div className="user">{it.text}</div>;
  if (it.kind === "answer") return <Answer it={it} />;
  if (it.kind === "error") return <div className="error">{it.text}</div>;
  if (it.kind === "note") return <div className="note">{it.text}</div>;
  return <Tool it={it} />;
}

function FileViewer({ file, onClose }) {
  const ext = file.path.split(".").pop().toLowerCase();
  const lang = hljs.getLanguage(ext) ? ext : null;
  return (
    <div className="backdrop" onClick={onClose}>
      <div className="viewer" onClick={(e) => e.stopPropagation()}>
        <div className="viewer-head">
          <strong>{file.path}</strong>
          <button className="ghost icon-btn" onClick={onClose} aria-label="Close"><Icon name="close" size={16} /></button>
        </div>
        {file.error ? (
          <p className="muted pad">{file.error}</p>
        ) : (
          <pre>
            {lang ? (
              <code className="hljs" dangerouslySetInnerHTML={{ __html: hljs.highlight(file.content, { language: lang }).value }} />
            ) : (
              file.content
            )}
          </pre>
        )}
      </div>
    </div>
  );
}

// ---------- the page ----------
export default function App() {
  const [items, setItems] = useState([]); // everything shown in the chat
  const [todos, setTodos] = useState([]); // the agent's plan
  const [files, setFiles] = useState([]); // files in the workspace
  const [chats, setChats] = useState([]); // saved chats (history)
  const [activeId, setActiveId] = useState(null);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState(false);
  const [confirm, setConfirm] = useState(null); // pending permission request
  const [usage, setUsage] = useState(0); // rough size of the conversation, in tokens
  const [viewer, setViewer] = useState(null); // file shown in the pop-up
  const [panelOpen, setPanelOpen] = useState(true); // right panel shown or hidden
  const [workspaceOpen, setWorkspaceOpen] = useState(false); // file list opened or closed
  const [theme, setTheme] = useState(document.documentElement.dataset.theme || "light");
  const wsRef = useRef(null);
  const endRef = useRef(null);
  const inputRef = useRef(null);
  const fileRef = useRef(null);

  const send = (obj) => wsRef.current?.send(JSON.stringify(obj));
  const addLocal = (event) => setItems((prev) => applyEvent(prev, event));

  const loadFiles = () => fetch(`${API}/files`).then((r) => r.json()).then(setFiles).catch(() => {});
  const loadChats = () => fetch(`${API}/chats`).then((r) => r.json()).then(setChats).catch(() => {});

  // Handle a message coming from the backend
  const handle = (m) => {
    if (m.type === "history") {
      // a chat was opened (or a new one started): rebuild the screen from its saved events
      setItems(m.events.reduce(applyEvent, []));
      setTodos([]); // a plan is only shown while the agent is working
      setUsage(m.events.filter((e) => e.type === "usage").pop()?.tokens || 0);
      setActiveId(m.id);
      setConfirm(null);
      setBusy(false);
      loadFiles();
    } else if (m.type === "todos") setTodos(m.todos);
    else if (m.type === "confirm") setConfirm(m);
    else if (m.type === "usage") setUsage(m.tokens);
    else if (m.type === "files") loadFiles();
    else if (m.type === "done") {
      setBusy(false);
      setTodos([]);
      loadFiles();
      loadChats();
    } else setItems((prev) => applyEvent(prev, m));
  };

  // Connect to the backend (and retry if it is not running yet)
  useEffect(() => {
    let stopped = false;
    let ws;
    let timer;
    const connect = () => {
      ws = new WebSocket(WS_URL);
      wsRef.current = ws;
      ws.onopen = () => {
        setConnected(true);
        loadChats();
      };
      ws.onmessage = (e) => handle(JSON.parse(e.data));
      ws.onclose = () => {
        setConnected(false);
        if (!stopped) timer = setTimeout(connect, 2000);
      };
    };
    connect();
    return () => {
      stopped = true;
      clearTimeout(timer);
      ws.close();
    };
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("theme", theme); } catch {}
  }, [theme]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "auto" });
  }, [items, confirm]);

  // Make the text box grow with its content
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }, [text]);

  // Close the file pop-up with Esc
  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && setViewer(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // ----- actions -----
  const newChat = () => !busy && send({ type: "new" });
  const openChat = (id) => !busy && id !== activeId && send({ type: "open", id });
  const undo = () => !busy && send({ type: "undo" });
  const stop = () => send({ type: "stop" });

  const deleteChat = async (id) => {
    await fetch(`${API}/chats/${id}`, { method: "DELETE" });
    loadChats();
    if (id === activeId) send({ type: "new" });
  };

  const runCommand = (name) => {
    if (name === "/new") newChat();
    else if (name === "/undo") undo();
    else if (name === "/download") window.open(`${API}/download`);
  };

  const sendTask = () => {
    const t = text.trim();
    if (!t || busy || !connected) return;
    setText("");
    if (COMMANDS.some((c) => c.name === t)) return runCommand(t);
    addLocal({ type: "user", text: t });
    setBusy(true);
    send({ type: "task", text: t });
  };

  const answerPermission = (ok, always = false) => {
    send({ type: "confirm_reply", ok, always });
    setConfirm(null);
  };

  const openFile = async (path) => {
    try {
      const r = await fetch(`${API}/file?path=${encodeURIComponent(path)}`);
      if (!r.ok) throw new Error();
      setViewer(await r.json());
    } catch {
      setViewer({ path, error: "This file cannot be shown (it may be a binary file)." });
    }
  };

  // Attach a text file: it is copied into the workspace and mentioned in the message
  const attach = async (e) => {
    const file = e.target.files[0];
    e.target.value = "";
    if (!file) return;
    if (file.size > 300000) return addLocal({ type: "error", text: "That file is too large (limit 300 KB)." });
    send({ type: "upload", name: file.name, content: await file.text() });
    setText((t) => `${t}${t && !t.endsWith(" ") ? " " : ""}@${file.name} `);
    inputRef.current?.focus();
  };

  // ----- suggestions for "/" commands and "@" file mentions -----
  const lastWord = text.split(/\s/).pop();
  let suggestions = [];
  if (text.startsWith("/") && !text.includes(" ")) {
    suggestions = COMMANDS.filter((c) => c.name.startsWith(text)).map((c) => ({ label: c.name, hint: c.hint }));
  } else if (lastWord.startsWith("@")) {
    suggestions = files
      .filter((f) => `@${f}`.toLowerCase().startsWith(lastWord.toLowerCase()))
      .slice(0, 6)
      .map((f) => ({ label: `@${f}`, hint: "" }));
  }
  const applySuggestion = (s) => {
    setText(s.label.startsWith("@") ? text.slice(0, text.length - lastWord.length) + s.label + " " : s.label);
    inputRef.current?.focus();
  };

  const doneCount = todos.filter((t) => t.status === "done").length;
  const title = chats.find((c) => c.id === activeId)?.title || "New chat";
  const streaming = items.length > 0 && items[items.length - 1].streaming;

  return (
    <div className={`app ${panelOpen ? "" : "wide"}`}>
      {/* ----- left: chat history ----- */}
      <aside className="sidebar">
        <div className="brand">
          <Mark />
          <span>My Coding Agent</span>
        </div>
        <button className="new-chat" onClick={newChat} disabled={busy || !connected}>
          <Icon name="plus" size={16} /> New chat
        </button>

        <h2>History</h2>
        <div className="history">
          {chats.length === 0 && <p className="muted pad">Your chats will appear here.</p>}
          {chats.map((c) => (
            <div key={c.id} className={`hist ${c.id === activeId ? "active" : ""}`}>
              <button className="hist-title" onClick={() => openChat(c.id)} title={c.title}>{c.title}</button>
              <button className="hist-del" aria-label="Delete chat" onClick={() => deleteChat(c.id)}>
                <Icon name="close" size={14} />
              </button>
            </div>
          ))}
        </div>

        <div className="side-foot">
          <span className={connected ? "pill on" : "pill off"}>
            <i /> {connected ? "Backend connected" : "Backend not reachable"}
          </span>
          <button className="ghost with-icon" onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}>
            <Icon name={theme === "dark" ? "sun" : "moon"} size={16} />
            {theme === "dark" ? "Light" : "Dark"}
          </button>
        </div>
      </aside>

      {/* ----- middle: the chat ----- */}
      <main className="main">
        <header className="topbar">
          <strong className="chat-title">{title}</strong>
          <div className="top-right">
            {usage > 0 && <span className="muted">about {usage.toLocaleString()} tokens in this chat</span>}
            <button className="ghost icon-btn" onClick={() => setPanelOpen(!panelOpen)}
              aria-label={panelOpen ? "Hide side panel" : "Show side panel"} aria-pressed={panelOpen}>
              <Icon name="panel" />
            </button>
          </div>
        </header>

        <div className="feed">
          <div className="column">
            {items.length === 0 && (
              <div className="empty">
                <Mark size="lg" />
                <h2>What do you want to build?</h2>
                <p className="muted">I can write files, run commands and fix errors. I ask before I change anything.</p>
                <div className="cards">
                  {EXAMPLES.map((ex) => (
                    <button key={ex.title} className="card"
                      onClick={() => { setText(ex.prompt); inputRef.current?.focus(); }}>
                      <strong>{ex.title}</strong>
                      <span>{ex.prompt}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {items.map((it, i) => <Item key={i} it={it} />)}

            {confirm && (
              <div className="permission">
                <strong>{confirm.title}</strong>
                {confirm.diff ? <Diff text={confirm.detail} /> : <pre>{confirm.detail}</pre>}
                <div className="buttons">
                  <button onClick={() => answerPermission(true)}>Allow</button>
                  {confirm.can_always && (
                    <button className="ghost" onClick={() => answerPermission(true, true)}>
                      Allow file changes this session
                    </button>
                  )}
                  <button className="ghost" onClick={() => answerPermission(false)}>Deny</button>
                </div>
              </div>
            )}

            {busy && !confirm && !streaming && (
              <div className="typing" aria-label="Agent is working"><span /> <span /> <span /></div>
            )}
            <div ref={endRef} />
          </div>
        </div>

        <div className="input">
          <div className="column">
            {suggestions.length > 0 && (
              <div className="suggest">
                {suggestions.map((s) => (
                  <button key={s.label} onClick={() => applySuggestion(s)}>
                    <b>{s.label}</b> <span>{s.hint}</span>
                  </button>
                ))}
              </div>
            )}
            <div className="box">
              <button className="icon-btn" aria-label="Attach a text file" onClick={() => fileRef.current.click()} disabled={busy}>
                <Icon name="paperclip" />
              </button>
              <input ref={fileRef} type="file" hidden onChange={attach} />
              <textarea
                ref={inputRef}
                rows={1}
                value={text}
                placeholder="Message the agent, / for commands, @ to mention a file"
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Tab" && suggestions.length > 0) {
                    e.preventDefault();
                    applySuggestion(suggestions[0]);
                  } else if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    sendTask();
                  }
                }}
              />
              {busy ? (
                <button className="send stop" aria-label="Stop" onClick={stop}><Icon name="stop" /></button>
              ) : (
                <button className="send" aria-label="Send" onClick={sendTask} disabled={!connected || !text.trim()}>
                  <Icon name="send" />
                </button>
              )}
            </div>
            <p className="hint">Enter to send, Shift+Enter for a new line. The agent only works inside the workspace folder.</p>
          </div>
        </div>
      </main>

      {/* ----- right: plan and files ----- */}
      {panelOpen && (
      <aside className="panel">
        {busy && todos.length > 0 && (
          <>
            <h2>Plan</h2>
            <div className="progress"><div style={{ width: `${(doneCount / todos.length) * 100}%` }} /></div>
            <p className="small">{doneCount} of {todos.length} done</p>
            <ul className="plan">
              {todos.map((t, i) => (
                <li key={i} className={t.status}><span className="check" />{t.task}</li>
              ))}
            </ul>
          </>
        )}

        <button className="section-toggle" onClick={() => setWorkspaceOpen(!workspaceOpen)} aria-expanded={workspaceOpen}>
          <span>Workspace</span>
          <Icon name="chevron" size={14} />
        </button>
        {workspaceOpen &&
          (files.length === 0 ? (
            <p className="muted">No files yet.</p>
          ) : (
            <>
              <ul className="files">
                {files.slice(0, 10).map((f) => (
                  <li key={f}>
                    <button onClick={() => openFile(f)}><Icon name="file" size={14} /> {f}</button>
                  </li>
                ))}
              </ul>
              <p className="small">
                {files.length > 10 ? `Showing 10 of ${files.length} files. ` : ""}
                For further files, click{" "}
                <a href={`${API}/download`} style={{ color: "var(--accent)" }}>Download workspace</a>.
              </p>
            </>
          ))}

        <div className="panel-actions">
          <button className="ghost with-icon" onClick={undo} disabled={busy || !connected}>
            <Icon name="undo" size={16} /> Undo last task
          </button>
          <a className="ghost with-icon" href={`${API}/download`}>
            <Icon name="download" size={16} /> Download workspace
          </a>
        </div>
      </aside>
      )}

      {viewer && <FileViewer file={viewer} onClose={() => setViewer(null)} />}
    </div>
  );
}
