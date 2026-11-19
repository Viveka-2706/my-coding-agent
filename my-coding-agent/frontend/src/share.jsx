// Turns a chat into Markdown or a stand-alone web page, so it can be shared as a file.
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeHighlight from "rehype-highlight";
import { renderToStaticMarkup } from "react-dom/server";

// A code fence that is longer than any run of backticks inside the text
const fence = (text, lang = "") => {
  const longest = Math.max(2, ...(text.match(/`+/g) || []).map((m) => m.length));
  const bar = "`".repeat(longest + 1);
  return `${bar}${lang}\n${text}\n${bar}`;
};
const quote = (text) => text.split("\n").map((l) => `> ${l}`).join("\n");

export function chatToMarkdown(items, title, labelOf) {
  const parts = [`# ${title}`, `*Shared from My Coding Agent on ${new Date().toLocaleDateString()}*`, "---"];
  for (const it of items) {
    if (it.kind === "user") {
      parts.push(`**You:**\n\n${quote(it.text)}`);
    } else if (it.kind === "answer") {
      parts.push(it.text);
    } else if (it.kind === "tool") {
      const a = it.args || {};
      let step = `**Step:** ${labelOf(it.name, a)}${it.approval ? ` *(${it.approval})*` : ""}`;
      if (it.name === "write_file" && a.content) {
        step += "\n\n" + fence(a.content.slice(0, 3000).replace(/\n$/, ""), (a.path || "").split(".").pop());
      } else if (it.name === "run_bash" && it.output) {
        step += "\n\n" + fence(it.output.slice(0, 1500));
      }
      parts.push(step);
    } else if (it.kind === "review" && !it.pending) {
      parts.push(`**Reviewer: ${it.approved ? "approved" : "changes needed"}**\n\n${it.text}`);
    } else if (it.kind === "error") {
      parts.push(`**Error:** ${it.text}`);
    } else if (it.kind === "note") {
      parts.push(`*${it.text}*`);
    }
  }
  return parts.join("\n\n") + "\n";
}

const escapeHtml = (t) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

const PAGE_CSS = `
body{margin:0;background:#f6f8fa;font:16px/1.6 system-ui,"Segoe UI",sans-serif;color:#1f2933}
main{max-width:780px;margin:0 auto;padding:32px 20px;background:#fff;min-height:100vh}
h1{font-size:26px}
blockquote{margin:12px 0;padding:8px 14px;background:#eef1f4;border-radius:10px}
blockquote p{margin:0}
pre{background:#f6f8fa;border:1px solid #e1e6eb;border-radius:8px;padding:12px;overflow:auto;font-size:13px}
code{font-family:ui-monospace,Consolas,monospace;font-size:.9em}
p code,li code{background:#f6f8fa;border:1px solid #e1e6eb;border-radius:4px;padding:1px 5px}
table{border-collapse:collapse}th,td{border:1px solid #e1e6eb;padding:4px 10px}
hr{border:0;border-top:1px solid #e1e6eb;margin:20px 0}
.hljs-keyword,.hljs-literal,.hljs-built_in{color:#7c3aed}.hljs-string,.hljs-attr{color:#b45309}
.hljs-number{color:#0369a1}.hljs-comment{color:#6b7a89;font-style:italic}.hljs-title{color:#1d4ed8}
`;

export function chatToHtml(markdown, title) {
  const body = renderToStaticMarkup(
    <ReactMarkdown remarkPlugins={[remarkGfm]} rehypePlugins={[rehypeHighlight]}>
      {markdown}
    </ReactMarkdown>
  );
  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)}</title><style>${PAGE_CSS}</style></head>
<body><main>${body}</main></body></html>`;
}

export function download(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
