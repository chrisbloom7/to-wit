#!/usr/bin/env python3
"""
claudecat_db — Database abstraction layer for the claudecat catalog.

This module is imported by other claudecat scripts; it is not run directly.
"""

import contextlib
import os
import sys
import sqlite3

DB_PATH = os.environ.get(
    'CLAUDECAT_DB_PATH',
    os.path.expanduser('~/.claude/catalog/catalog.db')
)

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS conversations (
  id           TEXT PRIMARY KEY,
  folder       TEXT NOT NULL,
  cwd          TEXT,
  started_at   TEXT,
  last_active  TEXT,
  title        TEXT,
  summary      TEXT,
  indexed_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS topics (
  id   INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS conversation_topics (
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  topic_id        INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
  PRIMARY KEY (conversation_id, topic_id)
);

CREATE INDEX IF NOT EXISTS idx_conversations_started ON conversations(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversations_cwd     ON conversations(cwd);
CREATE INDEX IF NOT EXISTS idx_ct_topic              ON conversation_topics(topic_id);
CREATE INDEX IF NOT EXISTS idx_ct_conv               ON conversation_topics(conversation_id);
"""


class Database:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path

    def validate(self):
        """Check that the DB file exists and is readable/writable."""
        if not os.path.isfile(self.db_path):
            print(
                f"Error: database not found at {self.db_path}.\n"
                "Run 'claudecat setup' to initialize it.",
                file=sys.stderr
            )
            sys.exit(1)
        if not os.access(self.db_path, os.R_OK | os.W_OK):
            print(
                f"Error: database at {self.db_path} is not readable/writable.",
                file=sys.stderr
            )
            sys.exit(1)

    @contextlib.contextmanager
    def connect(self):
        """Context manager yielding an sqlite3 connection; commits on clean exit, always closes."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def create_schema(self):
        """Execute the full schema DDL (safe to run on a fresh DB)."""
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    def upsert_conversation(self, data: dict):
        """
        Insert or replace a conversation record and its topic associations.

        Expected keys in data:
            id, folder, cwd, started_at, last_active, title, summary,
            topics (list of str)
        """
        topics = data.get('topics', [])

        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO conversations
                    (id, folder, cwd, started_at, last_active, title, summary, indexed_at)
                VALUES
                    (:id, :folder, :cwd, :started_at, :last_active, :title, :summary,
                     datetime('now'))
                ON CONFLICT(id) DO UPDATE SET
                    folder      = excluded.folder,
                    cwd         = excluded.cwd,
                    started_at  = excluded.started_at,
                    last_active = excluded.last_active,
                    title       = excluded.title,
                    summary     = excluded.summary,
                    indexed_at  = excluded.indexed_at
                """,
                {
                    'id':          data.get('id'),
                    'folder':      data.get('folder'),
                    'cwd':         data.get('cwd'),
                    'started_at':  data.get('started_at'),
                    'last_active': data.get('last_active'),
                    'title':       data.get('title'),
                    'summary':     data.get('summary'),
                }
            )

            # Remove old topic links so we start fresh on re-index
            conn.execute(
                "DELETE FROM conversation_topics WHERE conversation_id = ?",
                (data['id'],)
            )

            for topic_name in topics:
                if not topic_name:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO topics (name) VALUES (?)",
                    (topic_name,)
                )
                row = conn.execute(
                    "SELECT id FROM topics WHERE name = ? COLLATE NOCASE",
                    (topic_name,)
                ).fetchone()
                if row:
                    conn.execute(
                        "INSERT OR IGNORE INTO conversation_topics "
                        "(conversation_id, topic_id) VALUES (?, ?)",
                        (data['id'], row['id'])
                    )

    # ------------------------------------------------------------------
    # Private helper — builds the base query and returns (sql, params)
    # ------------------------------------------------------------------
    def _conversation_select(self):
        return """
            SELECT
                c.id,
                c.title,
                c.summary,
                c.cwd,
                c.started_at,
                GROUP_CONCAT(t.name, ', ') AS topics
            FROM conversations c
            LEFT JOIN conversation_topics ct ON ct.conversation_id = c.id
            LEFT JOIN topics t ON t.id = ct.topic_id
        """

    def _row_to_dict(self, row) -> dict:
        return {
            'id':         row['id'],
            'title':      row['title'],
            'summary':    row['summary'],
            'cwd':        row['cwd'],
            'started_at': row['started_at'],
            'topics':     row['topics'] or '',
        }

    def search(self, terms: list, mode: str = 'and', folder: str = None,
               include_summary: bool = False, include_title: bool = False) -> list:
        """
        Search over topic names, and optionally summaries and/or titles.

        mode='and'  — all terms must match (intersection)
        mode='or'   — any term must match (union)
        """
        self.validate()

        with self.connect() as conn:
            # For each term, build the set of matching conversation IDs
            term_id_sets = []
            for term in terms:
                like = f'%{term}%'
                # For topic matching, use a stemmed pattern (drop last char) so that
                # e.g. "estimate" matches "project-estimation" via "%estimat%"
                topic_like = f'%{term[:-1]}%' if len(term) >= 5 else like
                conditions = ['t.name LIKE ?']
                params = [topic_like]
                if include_summary:
                    conditions.append('c.summary LIKE ?')
                    params.append(like)
                if include_title:
                    conditions.append('c.title LIKE ?')
                    params.append(like)
                where = ' OR '.join(conditions)
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT c.id
                    FROM conversations c
                    LEFT JOIN conversation_topics ct ON ct.conversation_id = c.id
                    LEFT JOIN topics t ON t.id = ct.topic_id
                    WHERE {where}
                    """,
                    params
                ).fetchall()
                term_id_sets.append({r['id'] for r in rows})

            if not term_id_sets:
                return []

            if mode == 'and':
                matched_ids = term_id_sets[0]
                for s in term_id_sets[1:]:
                    matched_ids &= s
            else:
                matched_ids = set()
                for s in term_id_sets:
                    matched_ids |= s

            if not matched_ids:
                return []

            placeholders = ','.join('?' for _ in matched_ids)
            params = list(matched_ids)
            extra = ''
            if folder:
                extra = ' AND c.cwd = ?'
                params.append(folder)

            sql = (
                self._conversation_select()
                + f" WHERE c.id IN ({placeholders}){extra}"
                + " GROUP BY c.id ORDER BY c.started_at DESC"
            )
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def list_conversations(self, folder: str = None, topic: str = None) -> list:
        """Return all conversations, optionally filtered by folder and/or topic."""
        self.validate()

        conditions = []
        params = []

        if folder:
            conditions.append("c.cwd = ?")
            params.append(folder)

        if topic:
            conditions.append(
                "c.id IN ("
                "  SELECT ct2.conversation_id FROM conversation_topics ct2"
                "  JOIN topics t2 ON t2.id = ct2.topic_id"
                "  WHERE t2.name LIKE ? COLLATE NOCASE"
                ")"
            )
            params.append(f'%{topic}%')

        where_clause = (" WHERE " + " AND ".join(conditions)) if conditions else ""

        sql = (
            self._conversation_select()
            + where_clause
            + " GROUP BY c.id ORDER BY c.started_at DESC"
        )

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [self._row_to_dict(r) for r in rows]

    def get_conversation(self, conv_id: str):
        """Return a single conversation dict, or None if not found."""
        self.validate()

        sql = (
            self._conversation_select()
            + " WHERE c.id = ?"
            + " GROUP BY c.id"
        )

        with self.connect() as conn:
            row = conn.execute(sql, (conv_id,)).fetchone()
            if row is None:
                return None
            # Also include folder (not in the shared select above)
            result = self._row_to_dict(row)
            folder_row = conn.execute(
                "SELECT folder FROM conversations WHERE id = ?", (conv_id,)
            ).fetchone()
            if folder_row:
                result['folder'] = folder_row['folder']
            return result

    def all_conversation_stubs(self) -> list:
        """Return (id, folder) for every conversation — used by prune."""
        self.validate()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, folder FROM conversations ORDER BY started_at DESC"
            ).fetchall()
            return [{'id': r['id'], 'folder': r['folder']} for r in rows]

    def delete_conversation(self, conv_id: str):
        """Delete a conversation and its topic associations (via CASCADE)."""
        self.validate()
        with self.connect() as conn:
            conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))

    def is_indexed(self, conv_id: str) -> bool:
        """Return True if the session ID already exists in the DB."""
        self.validate()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM conversations WHERE id = ?", (conv_id,)
            ).fetchone()
            return row is not None
