"""Saves each chat as a JSON file so it can be reopened later."""
import json
import os
import time
import uuid

CHATS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "chats"))
os.makedirs(CHATS_DIR, exist_ok=True)


def path_of(chat_id):
    if not chat_id.isalnum():
        raise ValueError("Bad chat id")
    return os.path.join(CHATS_DIR, f"{chat_id}.json")


def new_chat(system_prompt):
    # messages = what the model sees, events = what the browser shows
    return {"id": uuid.uuid4().hex[:8], "title": "New chat", "updated": time.time(),
            "messages": [{"role": "system", "content": system_prompt}], "events": []}


def save(chat):
    chat["updated"] = time.time()
    with open(path_of(chat["id"]), "w", encoding="utf-8") as f:
        json.dump(chat, f)


def load(chat_id):
    with open(path_of(chat_id), encoding="utf-8") as f:
        return json.load(f)


def delete(chat_id):
    try:
        os.remove(path_of(chat_id))
    except FileNotFoundError:
        pass


def list_chats():
    found = []
    for name in os.listdir(CHATS_DIR):
        if name.endswith(".json"):
            chat = load(name[:-5])
            found.append({"id": chat["id"], "title": chat["title"], "updated": chat["updated"]})
    return sorted(found, key=lambda c: -c["updated"])
