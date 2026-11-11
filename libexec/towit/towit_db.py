#!/usr/bin/env python3
"""
towit_db — Database abstraction layer for the To Wit catalog.

This module is imported by other towit scripts; it is not run directly.
"""

import contextlib
import hashlib
import os
import sys
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from towit_config import config

# Archive objects shared by SCHEMA (fresh DBs) and run_migrations (existing DBs).
# External-content FTS5 is kept in sync by triggers so FK cascades from
# conversations also clean the index.
ARCHIVE_DDL = """
CREATE TABLE IF NOT EXISTS messages (
  id              INTEGER PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  seq             INTEGER NOT NULL,
  role            TEXT NOT NULL CHECK (role IN ('user','assistant')),
  ts              TEXT,
  text            TEXT NOT NULL,
  UNIQUE (conversation_id, seq)
);

CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
  text, content='messages', content_rowid='id',
  tokenize="unicode61 tokenchars '_-.'"
);

CREATE TRIGGER IF NOT EXISTS messages_ai AFTER INSERT ON messages BEGIN
  INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS messages_ad AFTER DELETE ON messages BEGIN
  INSERT INTO messages_fts(messages_fts, rowid, text) VALUES ('delete', old.id, old.text);
END;
CREATE TRIGGER IF NOT EXISTS messages_au AFTER UPDATE ON messages BEGIN
  INSERT INTO messages_fts(messages_fts, rowid, text) VALUES ('delete', old.id, old.text);
  INSERT INTO messages_fts(rowid, text) VALUES (new.id, new.text);
END;

CREATE TABLE IF NOT EXISTS forgotten (
  id           TEXT PRIMARY KEY,
  forgotten_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS conversations (
  id            TEXT PRIMARY KEY,
  folder        TEXT NOT NULL,
  cwd           TEXT,
  started_at    TEXT,
  last_active   TEXT,
  title         TEXT,
  summary       TEXT,
  message_count INTEGER,
  indexed_at    TEXT NOT NULL DEFAULT (datetime('now')),
  tail_hash     TEXT,
  source_path   TEXT,
  archived      INTEGER NOT NULL DEFAULT 0,
  archived_message_count INTEGER NOT NULL DEFAULT 0,
  repo_key      TEXT
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

CREATE TABLE IF NOT EXISTS keywords (
  id   INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT UNIQUE NOT NULL COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS conversation_keywords (
  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
  keyword_id      INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
  PRIMARY KEY (conversation_id, keyword_id)
);

CREATE INDEX IF NOT EXISTS idx_conversations_started ON conversations(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_conversations_cwd     ON conversations(cwd);
CREATE INDEX IF NOT EXISTS idx_ct_topic              ON conversation_topics(topic_id);
CREATE INDEX IF NOT EXISTS idx_ct_conv               ON conversation_topics(conversation_id);
CREATE INDEX IF NOT EXISTS idx_ck_keyword            ON conversation_keywords(keyword_id);
CREATE INDEX IF NOT EXISTS idx_ck_conv               ON conversation_keywords(conversation_id);
"""


def message_hash(role: str, text: str) -> str:
    """sha256 hex digest of a message, used to detect whether an archive is a prefix of a transcript."""
    return hashlib.sha256((role + "\0" + text).encode('utf-8')).hexdigest()


class Database:
    def __init__(self, db_path=None):
        self.db_path = db_path if db_path is not None else config.db_path

    def validate(self):
        """Check that the DB file exists and is readable/writable."""
        if not os.path.isfile(self.db_path):
            print(
                f"Error: database not found at {self.db_path}.\n"
                "Run 'towit setup' to initialize it.",
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
        self.run_migrations()

    def run_migrations(self):
        """Apply incremental schema changes for existing databases."""
        with self.connect() as conn:
            try:
                conn.execute("ALTER TABLE conversations ADD COLUMN message_count INTEGER")
            except sqlite3.OperationalError:
                pass  # Column already exists
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS keywords (
                  id   INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT UNIQUE NOT NULL COLLATE NOCASE
                );
                CREATE TABLE IF NOT EXISTS conversation_keywords (
                  conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                  keyword_id      INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
                  PRIMARY KEY (conversation_id, keyword_id)
                );
                CREATE INDEX IF NOT EXISTS idx_ck_keyword ON conversation_keywords(keyword_id);
                CREATE INDEX IF NOT EXISTS idx_ck_conv    ON conversation_keywords(conversation_id);
            """)
            for column in (
                "tail_hash TEXT",
                "source_path TEXT",
                "archived INTEGER NOT NULL DEFAULT 0",
                "archived_message_count INTEGER NOT NULL DEFAULT 0",
                "repo_key TEXT",
            ):
                try:
                    conn.execute(f"ALTER TABLE conversations ADD COLUMN {column}")
                except sqlite3.OperationalError:
                    pass  # Column already exists
            conn.executescript(
                "CREATE INDEX IF NOT EXISTS idx_conversations_repo_key ON conversations(repo_key);"
                + ARCHIVE_DDL
            )

    def upsert_conversation(self, data: dict):
        """
        Insert or update a conversation record and its topic/keyword associations.

        Returns False (writing nothing) if the id is in the forgotten table,
        checked under the write lock so a concurrent `towit forget` wins; else True.

        Expected keys in data:
            id, folder, cwd, started_at, last_active, title, summary,
            topics (list of str)
        """
        topics = data.get('topics', [])
        keywords = data.get('keywords', [])

        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM forgotten WHERE id = ?", (data['id'],)).fetchone():
                conn.rollback()
                return False
            conn.execute(
                """
                INSERT INTO conversations
                    (id, folder, cwd, started_at, last_active, title, summary,
                     message_count, indexed_at)
                VALUES
                    (:id, :folder, :cwd, :started_at, :last_active, :title, :summary,
                     :message_count, datetime('now'))
                ON CONFLICT(id) DO UPDATE SET
                    folder        = excluded.folder,
                    cwd           = excluded.cwd,
                    started_at    = excluded.started_at,
                    last_active   = excluded.last_active,
                    title         = excluded.title,
                    summary       = excluded.summary,
                    message_count = excluded.message_count,
                    indexed_at    = excluded.indexed_at
                """,
                {
                    'id':            data.get('id'),
                    'folder':        data.get('folder'),
                    'cwd':           data.get('cwd'),
                    'started_at':    data.get('started_at'),
                    'last_active':   data.get('last_active'),
                    'title':         data.get('title'),
                    'summary':       data.get('summary'),
                    'message_count': data.get('message_count'),
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

            # Remove old keyword links so we start fresh on re-index
            conn.execute(
                "DELETE FROM conversation_keywords WHERE conversation_id = ?",
                (data['id'],)
            )

            for keyword_name in keywords:
                if not keyword_name:
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO keywords (name) VALUES (?)",
                    (keyword_name,)
                )
                row = conn.execute(
                    "SELECT id FROM keywords WHERE name = ? COLLATE NOCASE",
                    (keyword_name,)
                ).fetchone()
                if row:
                    conn.execute(
                        "INSERT OR IGNORE INTO conversation_keywords "
                        "(conversation_id, keyword_id) VALUES (?, ?)",
                        (data['id'], row['id'])
                    )
        return True

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
                GROUP_CONCAT(DISTINCT t.name) AS topics,
                GROUP_CONCAT(DISTINCT k.name) AS keywords
            FROM conversations c
            LEFT JOIN conversation_topics ct ON ct.conversation_id = c.id
            LEFT JOIN topics t ON t.id = ct.topic_id
            LEFT JOIN conversation_keywords ck ON ck.conversation_id = c.id
            LEFT JOIN keywords k ON k.id = ck.keyword_id
        """

    def _row_to_dict(self, row) -> dict:
        return {
            'id':         row['id'],
            'title':      row['title'],
            'summary':    row['summary'],
            'cwd':        row['cwd'],
            'started_at': row['started_at'],
            'topics':     row['topics'] or '',
            'keywords':   row['keywords'] or '',
        }

    def search(self, terms: list, mode: str = 'and', folder: str = None,
               include_keywords: bool = True, include_topics: bool = False,
               include_summary: bool = False, include_title: bool = False) -> list:
        """
        Search over keywords (default) and optionally topics, summaries, and/or titles.

        mode='and'  — all terms must match (intersection)
        mode='or'   — any term must match (union)
        """
        self.validate()

        with self.connect() as conn:
            # For each term, build the set of matching conversation IDs
            term_id_sets = []
            for term in terms:
                like = f'%{term}%'
                # Use a stemmed pattern (drop last char) for name fields so that
                # e.g. "sprint" matches "sprint-planning" via "%sprin%"
                stem_like = f'%{term[:-1]}%' if len(term) >= 5 else like
                # Security: conditions must contain ONLY hardcoded parameterized SQL
                # clauses. All user-supplied values must be bound through the params
                # list using '?' placeholders. Never append user-controlled strings to
                # conditions directly — that would introduce SQL injection.
                conditions = []
                params = []
                if include_keywords:
                    conditions.append('k.name LIKE ?')
                    params.append(stem_like)
                if include_topics:
                    conditions.append('t.name LIKE ?')
                    params.append(stem_like)
                if include_summary:
                    conditions.append('c.summary LIKE ?')
                    params.append(like)
                if include_title:
                    conditions.append('c.title LIKE ?')
                    params.append(like)
                if not conditions:
                    return []
                assert all(isinstance(c, str) and '?' in c for c in conditions), \
                    "conditions must be hardcoded parameterized clauses only"
                where = ' OR '.join(conditions)
                rows = conn.execute(
                    f"""
                    SELECT DISTINCT c.id
                    FROM conversations c
                    LEFT JOIN conversation_topics ct ON ct.conversation_id = c.id
                    LEFT JOIN topics t ON t.id = ct.topic_id
                    LEFT JOIN conversation_keywords ck ON ck.conversation_id = c.id
                    LEFT JOIN keywords k ON k.id = ck.keyword_id
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

    def list_conversations(self, folder: str = None, topic: str = None, keyword: str = None) -> list:
        """Return all conversations, optionally filtered by folder, topic, and/or keyword."""
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

        if keyword:
            conditions.append(
                "c.id IN ("
                "  SELECT ck2.conversation_id FROM conversation_keywords ck2"
                "  JOIN keywords k2 ON k2.id = ck2.keyword_id"
                "  WHERE k2.name LIKE ? COLLATE NOCASE"
                ")"
            )
            params.append(f'%{keyword}%')

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

    def get_for_reindex(self, conv_id: str):
        """
        Return indexing metadata for an existing conversation, or None if not found.

        Returns a dict with:
            message_count (int or None), title (str), topics (list of str)
        """
        self.validate()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT c.message_count, c.title,
                       GROUP_CONCAT(DISTINCT t.name) AS topics,
                       GROUP_CONCAT(DISTINCT k.name) AS keywords
                FROM conversations c
                LEFT JOIN conversation_topics ct ON ct.conversation_id = c.id
                LEFT JOIN topics t ON t.id = ct.topic_id
                LEFT JOIN conversation_keywords ck ON ck.conversation_id = c.id
                LEFT JOIN keywords k ON k.id = ck.keyword_id
                WHERE c.id = ?
                GROUP BY c.id
                """,
                (conv_id,)
            ).fetchone()
            if row is None:
                return None
            raw_topics = row['topics'] or ''
            raw_keywords = row['keywords'] or ''
            return {
                'message_count': row['message_count'],
                'title':         row['title'] or '',
                'topics':        [t.strip() for t in raw_topics.split(',') if t.strip()],
                'keywords':      [k.strip() for k in raw_keywords.split(',') if k.strip()],
            }

    def touch_last_active(self, conv_id: str, last_active: str):
        """Update last_active and indexed_at without changing any other fields."""
        self.validate()
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE conversations
                SET last_active = ?, indexed_at = datetime('now')
                WHERE id = ?
                """,
                (last_active, conv_id)
            )

    def is_indexed(self, conv_id: str) -> bool:
        """Return True if the session has LLM metadata (a title); archive-only rows do not count."""
        self.validate()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM conversations WHERE id = ? AND title IS NOT NULL", (conv_id,)
            ).fetchone()
            return row is not None

    def is_forgotten(self, conv_id: str) -> bool:
        """Return True if the session ID is in the forgotten tombstone table."""
        self.validate()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM forgotten WHERE id = ?", (conv_id,)
            ).fetchone()
            return row is not None

    def archive_session(self, conv: dict, messages: list) -> str:
        """
        Atomically sync a session's messages into the archive.

        conv keys: id, folder, cwd, started_at, last_active, repo_key, source_path.
        Each message: role, ts, text (stored verbatim).

        Returns 'ingested' (not previously archived), 'appended' (stored messages
        are a prefix of messages), 'rewritten' (stored messages diverged),
        'unchanged', or 'forgotten' (id is tombstoned; nothing written). LLM
        metadata (title, summary, message_count, topics, keywords) is never touched. One BEGIN IMMEDIATE transaction; any
        exception rolls everything back.
        """
        conv_id = conv['id']
        tail_hash = message_hash(messages[-1]['role'], messages[-1]['text']) if messages else None
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                # Re-check under the write lock so a concurrent `towit forget` always wins.
                if conn.execute("SELECT 1 FROM forgotten WHERE id = ?", (conv_id,)).fetchone():
                    conn.rollback()
                    return 'forgotten'
                row = conn.execute(
                    "SELECT archived, archived_message_count, tail_hash FROM conversations WHERE id = ?",
                    (conv_id,)
                ).fetchone()
                stored = row['archived_message_count'] if row else 0
                if row is None or not row['archived']:
                    outcome, start = 'ingested', 0
                elif (0 < stored <= len(messages) and row['tail_hash'] == message_hash(
                        messages[stored - 1]['role'], messages[stored - 1]['text'])):
                    outcome = 'unchanged' if stored == len(messages) else 'appended'
                    start = stored
                else:
                    outcome, start = 'rewritten', 0

                params = {
                    'id': conv_id, 'folder': conv.get('folder'), 'cwd': conv.get('cwd'),
                    'started_at': conv.get('started_at'), 'last_active': conv.get('last_active'),
                    'repo_key': conv.get('repo_key'), 'source_path': conv.get('source_path'),
                    'tail_hash': tail_hash, 'count': len(messages),
                }
                conn.execute(
                    """
                    INSERT INTO conversations
                        (id, folder, cwd, started_at, last_active, repo_key, source_path,
                         tail_hash, archived, archived_message_count)
                    VALUES
                        (:id, :folder, :cwd, :started_at, :last_active, :repo_key, :source_path,
                         :tail_hash, 1, :count)
                    ON CONFLICT(id) DO UPDATE SET
                        last_active            = excluded.last_active,
                        cwd                    = excluded.cwd,
                        repo_key               = excluded.repo_key,
                        source_path            = excluded.source_path,
                        tail_hash              = excluded.tail_hash,
                        archived               = 1,
                        archived_message_count = excluded.archived_message_count
                    """,
                    params
                )

                if start == 0:
                    conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
                conn.executemany(
                    "INSERT INTO messages (conversation_id, seq, role, ts, text) VALUES (?, ?, ?, ?, ?)",
                    [(conv_id, seq, m['role'], m.get('ts'), m['text'])
                     for seq, m in enumerate(messages) if seq >= start]
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return outcome
