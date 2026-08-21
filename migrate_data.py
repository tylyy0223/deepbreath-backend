"""旧 SQLite 数据 → PostgreSQL 数据迁移脚本"""
import sqlite3
import sys
import os
from datetime import datetime, timezone

# Add psy-chat path for old config
sys.path.insert(0, "/root/psy-chat")

import psycopg2
from psycopg2.extras import execute_values

OLD_DB = "/root/psy-chat/psychat.db"
PG_DSN = "host=127.0.0.1 port=5432 dbname=deepbreath user=deepbreath password=deepbreath_2026"

def migrate():
    sqlite = sqlite3.connect(OLD_DB)
    sqlite.row_factory = sqlite3.Row
    pg = psycopg2.connect(PG_DSN)
    pg.autocommit = False

    try:
        cur = pg.cursor()

        # 1. Migrate users (map by email)
        print("\n=== Migrating users ===")
        old_users = sqlite.execute("SELECT * FROM users").fetchall()
        user_map = {}  # old_id -> new_id
        for u in old_users:
            email = u["email"] or f"user_{u['id']}@legacy.local"
            nickname = email.split("@")[0]
            # Check if exists
            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
            row = cur.fetchone()
            if row:
                new_id = row[0]
                print(f"  Skip existing: {email} (id={new_id})")
            else:
                # Create user
                now = datetime.now(timezone.utc).isoformat()
                cur.execute(
                    "INSERT INTO users (email, password_hash, nickname, avatar_url, role, status, created_at, updated_at) VALUES (%s, %s, %s, '', %s, %s, %s, %s) RETURNING id",
                    (email, u["password_hash"] or "legacy_hash", nickname, "user", "active", u["created_at"] or now, now),
                )
                new_id = cur.fetchone()[0]
                print(f"  Created: {email} -> user_id={new_id}")
            user_map[u["id"]] = new_id

        # 2. Migrate sessions -> chat_sessions
        print("\n=== Migrating sessions ===")
        old_sessions = sqlite.execute("SELECT * FROM sessions").fetchall()
        session_map = {}
        for s in old_sessions:
            old_sid = s["id"]
            # Assign to first user if no email/ip match
            user_id = user_map.get(1, 1)
            mode = s["mode"] or "science"
            cur.execute(
                "INSERT INTO chat_sessions (user_id, mode, title, message_count, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (user_id, mode, f"旧对话 {old_sid[:8]}", s["message_count"] or 0,
                 s["created_at"] or "2025-01-01", s["updated_at"] or "2025-01-01"),
            )
            new_id = cur.fetchone()[0]
            session_map[old_sid] = new_id
        print(f"  Migrated {len(session_map)} sessions")

        # 3. Migrate messages -> chat_messages
        print("\n=== Migrating messages ===")
        old_msgs = sqlite.execute("SELECT * FROM messages ORDER BY id").fetchall()
        migrated_msgs = 0
        for m in old_msgs:
            old_sid = m["session_id"]
            new_sid = session_map.get(old_sid)
            if not new_sid:
                continue
            cur.execute(
                "INSERT INTO chat_messages (session_id, role, content, token_count, created_at) VALUES (%s, %s, %s, 0, %s)",
                (new_sid, m["role"], m["content"], m["created_at"] or "2025-01-01"),
            )
            migrated_msgs += 1
        print(f"  Migrated {migrated_msgs} messages")

        # 4. Migrate scale_results
        print("\n=== Migrating scale_results ===")
        old_scales = sqlite.execute("SELECT * FROM scale_results").fetchall()
        for s in old_scales:
            user_id = user_map.get(1, 1)
            cur.execute(
                "INSERT INTO scale_results (user_id, scale_id, raw_score, standard_score, level, answers_json, result_json, created_at) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (user_id, s["scale_id"], s["raw_score"] or 0, s["standard_score"] or 0,
                 s["level"] or "", s["answers"] or "{}", s["result_json"] or "{}",
                 s["created_at"] or "2025-01-01"),
            )
        print(f"  Migrated {len(old_scales)} scale results")

        # 5. Migrate mood_entries
        print("\n=== Migrating mood_entries ===")
        old_moods = sqlite.execute("SELECT * FROM mood_entries").fetchall()
        for m in old_moods:
            user_id = user_map.get(1, 1)
            cur.execute(
                "INSERT INTO mood_entries (user_id, mood_score, mood_label, body_sensation, note, weather, created_at) VALUES (%s, %s, %s, '', %s, %s, %s)",
                (user_id, m["score"] or 3, "", m["note"] or "", "", m["created_at"] or "2025-01-01"),
            )
        print(f"  Migrated {len(old_moods)} mood entries")

        pg.commit()
        print("\n=== Migration completed! ===")

    except Exception as e:
        pg.rollback()
        print(f"Migration failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        sqlite.close()
        pg.close()


if __name__ == "__main__":
    migrate()
