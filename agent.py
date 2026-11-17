import json
from groq import Groq

client = Groq()  # reads GROQ_API_KEY from your environment
MODEL = "openai/gpt-oss-120b"  # check Groq's docs for current tool-use models

SYSTEM = "You are a coding agent. Use the tools to read files and complete the user's task."

TOOLS = [{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a text file and return its contents",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
    },
}]

def execute_tool(name, args):
    if name == "read_file":
        with open(args["path"], "r", encoding="utf-8") as f:
            return f.read()
    return f"Unknown tool: {name}"

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
                args = json.loads(call.function.arguments)
                print(f"  [tool] {call.function.name}({args})")
                out = execute_tool(call.function.name, args)
            except Exception as e:
                out = f"Error: {e}"
            messages.append({"role": "tool", "tool_call_id": call.id,
                             "content": str(out)[:10000]})
    return "Stopped: max steps reached"

if __name__ == "__main__":
    messages = [{"role": "system", "content": SYSTEM}]
    print("Agent ready. Type 'exit' to quit.")
    while True:
        task = input("\n> ")
        if task.strip().lower() == "exit":
            break
        messages.append({"role": "user", "content": task})
        print("\n" + run_agent(messages))