"""One-time migration: chat-context.json → SQLite + Chroma.

Run once: python migrate.py
Idempotent: skips if memory.db already has rows.
"""

import json
import time
from pathlib import Path

from db import init_db, has_messages, insert_message, get_all_message_ids_and_content
from embeddings import upsert

CONTEXT_FILE = Path(__file__).with_name("chat-context.json")


def main():
    init_db()

    if has_messages():
        print("memory.db already has rows — skipping migration.")
        return

    if not CONTEXT_FILE.exists():
        print(f"{CONTEXT_FILE.name} not found — nothing to migrate.")
        return

    with CONTEXT_FILE.open("r", encoding="utf-8") as f:
        data = json.load(f)

    messages = data.get("messages", [])
    # Skip the system message (index 0); it's reconstructed at runtime.
    conversation = [m for m in messages if m.get("role") != "system"]

    if not conversation:
        print("No conversation turns found in JSON.")
        return

    # Assign fake timestamps spaced 30s apart so recency ordering is preserved.
    base_time = time.time() - len(conversation) * 30
    for i, msg in enumerate(conversation):
        ts = base_time + i * 30
        insert_message(msg["role"], msg["content"], ts)

    print(f"Inserted {len(conversation)} messages into SQLite.")

    rows = get_all_message_ids_and_content()
    for msg_id, content in rows:
        print(f"  Embedding message {msg_id}...", end="\r")
        upsert(msg_id, content)
    print(f"\nEmbedded {len(rows)} messages into Chroma.")
    print("Migration complete.")


if __name__ == "__main__":
    main()
