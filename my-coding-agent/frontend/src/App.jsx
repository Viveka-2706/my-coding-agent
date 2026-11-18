import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import "./App.css";

const API = "http://localhost:8000";
const WS_URL = "ws://localhost:8000/ws";

const EXAMPLES = [
  { title: "Create and run a script", prompt: "Create primes.py that prints the first 10 prime numbers, then run it" },
  { title: "Build a module with tests", prompt: "Build a to-do list module with add, remove and list functions, a test file, and run the tests" },
  { title: "Search the code", prompt: "Find where the add function is defined" },
];

// Short, readable name for each tool call
const LABEL = {
  read_file: (a) => `Read ${a.path}`,
  list_dir: (a) => `Listed ${a.path || "."}`,
  write_file: (a) => `Wrote ${a.path}`,
  edit_file: (a) => `Edited ${a.path}`,
  grep: (a) => `Searched for "${a.pattern}"`,
  run_bash: (a) => `Ran ${String(a.command).slice(0, 80)}`,
};
const labelOf = (name, args) => (LABEL[name] ? LABEL[name](args) : name);
const prefix = (text, sign) =>
  String(text ?? "").split("\n").map((l) => `${sign} ${l}`).join("\n");

// ---------- small building blocks ----------
const ICONS = {
  sun: "M12 8a4 4 0 100 8 4 4 0 000-8zM12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4",
  moon: "M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z",
  send: "M5 12h14M13 6l6 6-6 6",
  plus: "M12 5v14M5 12h14",
  file: "M7 3h7l4 4v14H7zM14 3v4h4",
  chevron: "M6 9l6 6 6-6",
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

function Item({ it }) {
  if (it.kind === "user") return <div className="user">{it.text}</div>;
  if (it.kind === "answer")
    return (
      <div className="agent-row">
        <Mark />
        <div className="agent md">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeHighlight]}
            components={{ pre: CodeBlock }}
          >
            {it.text}
          </ReactMarkdown>
        </div>
      </div>
    );
  if (it.kind === "error") return <div className="error">{it.text}</div>;
  if (it.kind === "note") return <div className="note">{it.text}</div>;
  return <Tool it={it} />;
}

// ---------- the page ----------
export default function App() {
  const [items, setItems] = useState([]); // everything shown in the chat
  const [todos, setTodos] = useState([]); // the agent's plan
  const [files, setFiles] = useState([]); // files in the workspace
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState(false);
  const [confirm, setConfirm] = useState(null); // pending permission request
  const [theme, setTheme] = useState(document.documentElement.dataset.theme || "light");
  const wsRef = useRef(null);
  const endRef = useRef(null);
  const inputRef = useRef(null);

  const add = (item) => setItems((prev) => [...prev, item]);

  const loadFiles = () =>
    fetch(`${API}/files`).then((r) => r.json()).then(setFiles).catch(() => {});

  // Handle a message coming from the backend
  const handle = (m) => {
    if (m.type === "tool") add({ kind: "tool", name: m.name, args: m.args });
    else if (m.type === "result")
      // attach the output to the most recent tool call that has none yet
      setItems((prev) => {
        const copy = [...prev];
        for (let i = copy.length - 1; i >= 0; i--) {
          if (copy[i].kind === "tool" && copy[i].output === undefined) {
            copy[i] = { ...copy[i], output: m.output };
            break;
          }
        }
        return copy;
      });
    else if (m.type === "todos") setTodos(m.todos);
    else if (m.type === "confirm") setConfirm(m);
    else if (m.type === "answer") add({ kind: "answer", text: m.text });
    else if (m.type === "error") add({ kind: "error", text: m.text });
    else if (m.type === "done") {
      setBusy(false);
      loadFiles();
    }
  };

  // Connect to the backend (and retry if it is not running yet)
  useEffect(() => {
    let stopped = false;
    let ws;
    let timer;
    const connect = () => {
      ws = new WebSocket(WS_URL);
      wsRef.current = ws;
      ws.onopen = () => setConnected(true);
      ws.onmessage = (e) => handle(JSON.parse(e.data));
      ws.onclose = () => {
        setConnected(false);
        if (!stopped) timer = setTimeout(connect, 2000);
      };
    };
    connect();
    loadFiles();
    return () => {
      stopped = true;
      clearTimeout(timer);
      ws.close();
    };
  }, []);

  // Save and apply the theme
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    try { localStorage.setItem("theme", theme); } catch {}
  }, [theme]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [items, confirm]);

  // Make the text box grow with its content
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 160) + "px";
  }, [text]);

  const sendTask = () => {
    if (!text.trim() || busy || !connected) return;
    add({ kind: "user", text });
    setBusy(true);
    wsRef.current.send(JSON.stringify({ type: "task", text }));
    setText("");
  };

  const answerPermission = (ok) => {
    wsRef.current.send(JSON.stringify({ type: "confirm_reply", ok }));
    add({ kind: "note", text: `${ok ? "Allowed" : "Denied"}: ${confirm.title}` });
    setConfirm(null);
  };

  const newChat = () => {
    wsRef.current.send(JSON.stringify({ type: "reset" }));
    setItems([]);
    setTodos([]);
  };

  const doneCount = todos.filter((t) => t.status === "done").length;

  return (
    <div className="app">
      <aside className="side">
        <div className="brand">
          <Mark />
          <span>My Coding Agent</span>
        </div>

        <h2>Plan</h2>
        {todos.length === 0 ? (
          <p className="muted">The plan appears here for multi-step tasks.</p>
        ) : (
          <>
            <div className="progress">
              <div style={{ width: `${(doneCount / todos.length) * 100}%` }} />
            </div>
            <p className="small">{doneCount} of {todos.length} done</p>
            <ul className="plan">
              {todos.map((t, i) => (
                <li key={i} className={t.status}>
                  <span className="check" />
                  {t.task}
                </li>
              ))}
            </ul>
          </>
        )}

        <h2>Workspace files</h2>
        {files.length === 0 ? (
          <p className="muted">No files yet.</p>
        ) : (
          <ul className="files">
            {files.map((f) => (
              <li key={f}><Icon name="file" size={14} /> {f}</li>
            ))}
          </ul>
        )}
      </aside>

      <main className="main">
        <header className="topbar">
          <span className={connected ? "pill on" : "pill off"}>
            <i /> {connected ? "Backend connected" : "Backend not reachable"}
          </span>
          <div className="actions">
            <button className="ghost with-icon" onClick={newChat} disabled={busy || !connected}>
              <Icon name="plus" size={16} /> New chat
            </button>
            <button
              className="ghost with-icon"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
            >
              <Icon name={theme === "dark" ? "sun" : "moon"} size={16} />
              {theme === "dark" ? "Light" : "Dark"}
            </button>
          </div>
        </header>

        <div className="feed">
          <div className="column">
            {items.length === 0 && (
              <div className="empty">
                <Mark size="lg" />
                <h2>What do you want to build?</h2>
                <p className="muted">
                  I can write files, run commands and fix errors. I ask before I change anything.
                </p>
                <div className="cards">
                  {EXAMPLES.map((ex) => (
                    <button
                      key={ex.title}
                      className="card"
                      onClick={() => {
                        setText(ex.prompt);
                        inputRef.current?.focus();
                      }}
                    >
                      <strong>{ex.title}</strong>
                      <span>{ex.prompt}</span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {items.map((it, i) => (
              <Item key={i} it={it} />
            ))}

            {confirm && (
              <div className="permission">
                <strong>{confirm.title}</strong>
                {confirm.title.startsWith("Edit file") ? (
                  <Diff text={confirm.detail} />
                ) : (
                  <pre>{confirm.detail}</pre>
                )}
                <div className="buttons">
                  <button onClick={() => answerPermission(true)}>Allow</button>
                  <button className="ghost" onClick={() => answerPermission(false)}>Deny</button>
                </div>
              </div>
            )}

            {busy && !confirm && (
              <div className="typing" aria-label="Agent is working">
                <span /> <span /> <span />
              </div>
            )}
            <div ref={endRef} />
          </div>
        </div>

        <div className="input">
          <div className="column">
            <div className="box">
              <textarea
                ref={inputRef}
                rows={1}
                value={text}
                placeholder="Ask the agent to build or fix something"
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    sendTask();
                  }
                }}
              />
              <button
                className="send"
                aria-label="Send"
                onClick={sendTask}
                disabled={busy || !connected || !text.trim()}
              >
                <Icon name="send" />
              </button>
            </div>
            <p className="hint">Enter to send, Shift+Enter for a new line. The agent only works inside the workspace folder.</p>
          </div>
        </div>
      </main>
    </div>
  );
}
