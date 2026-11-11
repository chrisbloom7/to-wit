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

# Bump whenever run_migrations gains steps; stored in PRAGMA user_version.
SCHEMA_VERSION = 1

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


def is_missing_forgotten_table(exc: Exception) -> bool:
    """True if exc is the error from an un-migrated DB lacking the forgotten table.

    Nothing can be forgotten there, so callers treat it as not-forgotten; every
    other OperationalError (locked, I/O) must still fail closed.
    """
    return isinstance(exc, sqlite3.OperationalError) and 'no such table: forgotten' in str(exc)


def message_hash(role: str, text: str) -> str:
    """sha256 hex digest of a message, used to detect whether an archive is a prefix of a transcript."""
    return hashlib.sha256((role + "\0" + text).encode('utf-8')).hexdigest()


# Message prefixes SQLite emits when FTS5 rejects a MATCH query (verified by provoking
# each unquoted: 'a AND', '"abc', 'foo:bar', '*'). Only meaningful for errors raised
# by the MATCH execution itself.
FTS_QUERY_ERROR_PREFIXES = ('fts5: ', 'unterminated string', 'no such column: ',
                            'unknown special query')


def is_fts_query_error(exc: Exception) -> bool:
    """True if exc is an FTS5 query-parse error (as opposed to a lock, I/O or SQL bug)."""
    return isinstance(exc, sqlite3.OperationalError) and str(exc).startswith(FTS_QUERY_ERROR_PREFIXES)


def build_match_expression(terms: list, mode: str = 'and') -> str | None:
    """Build an FTS5 MATCH expression from user terms, or None if nothing is searchable.

    Each term becomes a quoted FTS5 phrase (embedded '"' doubled), so operators,
    column filters and punctuation in user input are always literal. Terms with
    no letter or digit cannot produce a token and are dropped.
    """
    phrases = ['"%s"' % t.replace('"', '""') for t in terms if any(ch.isalnum() for ch in t)]
    if not phrases:
        return None
    return (' OR ' if mode == 'or' else ' AND ').join(phrases)


def _add_column(conn, column_def: str) -> None:
    """ALTER TABLE conversations ADD COLUMN, tolerating only an already-present column."""
    try:
        conn.execute(f"ALTER TABLE conversations ADD COLUMN {column_def}")
    except sqlite3.OperationalError as exc:
        if 'duplicate column name' not in str(exc):
            raise


def _execute_script(conn, script: str) -> None:
    """
    Run a multi-statement script inside the caller's open transaction.

    sqlite3's executescript() COMMITs first, which would drop the migration lock,
    so split on complete statements (trigger bodies contain semicolons) instead.
    Statements are detected line by line with sqlite3.complete_statement, so each
    one must start on its own line; two statements on one line raise
    ProgrammingError (and the migration rolls back).
    """
    statement = ''
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            conn.execute(statement)
            statement = ''
    if statement.strip():
        conn.execute(statement)


class Database:
    cleanup_warning = None  # set by forget_conversations when physical cleanup was incomplete

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
        # Steady state costs one PRAGMA read; a DB from an older towit migrates
        # in place (a newer DB is left alone). Errors propagate to the caller.
        if self.schema_version() < SCHEMA_VERSION:
            self.run_migrations(only_if_stale=True)

    def schema_version(self) -> int:
        """Return the schema version stamped in PRAGMA user_version (0 if never stamped)."""
        with self.connect() as conn:
            return conn.execute("PRAGMA user_version").fetchone()[0]

    @contextlib.contextmanager
    def connect(self):
        """Context manager yielding an sqlite3 connection; commits on clean exit, always closes."""
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        # Zero freed pages so deleted or overwritten text never lingers in the file.
        conn.execute("PRAGMA secure_delete=ON")
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
        self.run_migrations()  # also stamps SCHEMA_VERSION

    def run_migrations(self, only_if_stale: bool = False):
        """
        Apply incremental schema changes for existing databases, then stamp
        SCHEMA_VERSION. Idempotent. Runs as one BEGIN IMMEDIATE transaction, so a
        failure rolls everything back (version unchanged) and concurrent migrators
        serialize; with only_if_stale the version is re-checked under the lock so
        the loser of a race does nothing.
        """
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            if only_if_stale and version >= SCHEMA_VERSION:
                return
            _add_column(conn, "message_count INTEGER")
            _execute_script(conn, """
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
                _add_column(conn, column)
            _execute_script(
                conn,
                "CREATE INDEX IF NOT EXISTS idx_conversations_repo_key ON conversations(repo_key);"
                + ARCHIVE_DDL
            )
            if not conn.in_transaction:
                # SQLite can roll back by itself on SQLITE_FULL/IOERR; never stamp that.
                raise RuntimeError("schema migration transaction was lost; not stamping version")
            if version < SCHEMA_VERSION:  # never downgrade a newer towit's stamp
                conn.execute(f"PRAGMA user_version = {int(SCHEMA_VERSION)}")

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
            try:
                forgotten = conn.execute(
                    "SELECT 1 FROM forgotten WHERE id = ?", (data['id'],)).fetchone()
            except sqlite3.OperationalError as exc:
                if not is_missing_forgotten_table(exc):
                    raise
                forgotten = None  # un-migrated DB: nothing can be forgotten
            if forgotten:
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

    def _repo_filter(self, repo: str, col: str = 'c.repo_key') -> tuple:
        """Return (sql, params) matching rows whose `col` equals repo exactly or whose
        final path component equals repo.

        `col` is a hardcoded column reference supplied by the caller (never user input).
        The basename test compares a suffix with substr(), not LIKE, so '%', '_' and
        '\\' in repo are literal. A trailing slash on repo is ignored.
        """
        stripped = repo.rstrip('/')
        if not stripped:
            return '1 = 0', []
        sql = f"({col} = ? OR {col} = ?"
        params = [repo, stripped]
        if '/' not in stripped:
            sql += f" OR substr({col}, -length(?)) = ?"
            params += ['/' + stripped, '/' + stripped]
        return sql + ')', params

    def _text_match_query(self, folder, repo) -> tuple:
        """SQL + params (after the MATCH expression) for message-text hits, best bm25 first."""
        sql = (
            "SELECT m.conversation_id AS id, m.seq AS seq,"
            " snippet(messages_fts, 0, '[', ']', '…', 12) AS snippet,"
            " bm25(messages_fts) AS score"
            " FROM messages_fts"
            " JOIN messages m ON m.id = messages_fts.rowid"
            " JOIN conversations c ON c.id = m.conversation_id"
            " WHERE messages_fts MATCH ?"
        )
        params = []
        if folder:
            sql += " AND c.cwd = ?"
            params.append(folder)
        if repo:
            frag, rparams = self._repo_filter(repo)
            sql += " AND " + frag
            params += rparams
        return sql + " ORDER BY score", params

    def search_archive(self, terms: list, mode: str = 'and', folder: str = None,
                       repo: str = None, scope: str = 'all', include_topics: bool = False,
                       include_summary: bool = False, include_title: bool = False,
                       limit: int = 50) -> list:
        """
        Search archived message text and/or conversation metadata.

        scope='all'      — metadata (as `search`) plus message text; a conversation with
                           a metadata match ranks above a text-only match, then bm25
                           (lower is better), then recency
        scope='text'     — message text only
        scope='metadata' — exactly `search` (keywords plus the include_* fields)

        One result per conversation: its best-matching message (seq, snippet, score), or
        seq=None, snippet='', score=None for a metadata-only hit. A null title falls back
        to the first user message (80 chars). limit caps text-only rows (metadata
        hits are never dropped); limit=None means unlimited.
        """
        self.validate()
        meta = []
        if scope in ('all', 'metadata'):
            meta = self.search(terms, mode=mode, folder=folder, include_keywords=True,
                               include_topics=include_topics, include_summary=include_summary,
                               include_title=include_title)

        with self.connect() as conn:
            if repo and meta:
                frag, rparams = self._repo_filter(repo)
                keep = {r['id'] for r in conn.execute(
                    f"SELECT c.id FROM conversations c WHERE {frag}", rparams)}
                meta = [r for r in meta if r['id'] in keep]

            if scope == 'metadata':
                results = [dict(r, seq=None, snippet='', score=None) for r in meta]
                results = results[:limit] if limit else results
                self._fill_title_fallback(conn, results)
                return results

            hits = {}  # conversation id -> best text row (rows arrive best-first)
            expr = build_match_expression(terms, mode)
            if expr is not None:
                sql, params = self._text_match_query(folder, repo)
                try:
                    for row in conn.execute(sql, [expr] + params):
                        hits.setdefault(row['id'], row)
                except sqlite3.OperationalError as e:
                    # A query FTS5 rejects despite quoting means "no text hits";
                    # lock/IO errors and non-FTS SQL errors must still propagate.
                    if not is_fts_query_error(e):
                        raise
                    hits = {}

            meta_by_id = {r['id']: r for r in meta}
            order = list(meta_by_id.keys() | hits.keys())  # sorted deterministically below
            started = {}
            if order:
                for i in range(0, len(order), 500):
                    chunk = order[i:i + 500]
                    started.update({r['id']: r['started_at'] or '' for r in conn.execute(
                        "SELECT id, started_at FROM conversations WHERE id IN (%s)"
                        % ','.join('?' for _ in chunk), chunk)})
            order.sort(key=lambda i: i)  # id, then recency: a deterministic base for the tier sort
            order.sort(key=lambda i: started.get(i, ''), reverse=True)
            order.sort(key=lambda i: (
                i not in meta_by_id,
                i not in hits,
                hits[i]['score'] if i in hits else 0.0,
            ))
            if limit:
                # Cap text-only rows; every metadata-tier row is kept (tier 0 sorts first).
                order = order[:len(meta_by_id) + limit]

            results = []
            for conv_id in order:
                base = meta_by_id.get(conv_id)
                if base is None:
                    base = self._get_summary_row(conn, conv_id)
                hit = hits.get(conv_id)
                results.append(dict(
                    base,
                    seq=hit['seq'] if hit else None,
                    snippet=hit['snippet'] if hit else '',
                    score=hit['score'] if hit else None,
                ))
            self._fill_title_fallback(conn, results)
            return results

    def _get_summary_row(self, conn, conv_id: str) -> dict:
        row = conn.execute(
            self._conversation_select() + " WHERE c.id = ? GROUP BY c.id", (conv_id,)
        ).fetchone()
        return self._row_to_dict(row)

    def _fill_title_fallback(self, conn, results: list) -> None:
        """Replace a null title with the first user message (80 chars), if one is archived."""
        for r in results:
            if r['title']:
                continue
            row = conn.execute(
                "SELECT text FROM messages WHERE conversation_id = ? AND role = 'user' "
                "ORDER BY seq LIMIT 1", (r['id'],)
            ).fetchone()
            if row:
                r['title'] = row['text'][:80]

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

    def get_show_header(self, conv_id: str):
        """Header fields for `towit show`, or None if the conversation is unknown.

        The title falls back to the first archived user message (80 chars), as in search.
        """
        self.validate()
        with self.connect() as conn:
            row = conn.execute(
                "SELECT id, title, folder, cwd, repo_key, started_at, last_active, archived "
                "FROM conversations WHERE id = ?", (conv_id,)
            ).fetchone()
            if row is None:
                return None
            header = dict(row)
            header['archived'] = bool(header['archived'])
            self._fill_title_fallback(conn, [header])
            return header

    def get_messages(self, conv_id: str, around: int = None, context: int = 5) -> list:
        """
        Return archived messages (keys seq, role, ts, text) ordered by seq.

        With `around`, only messages whose seq is within [around - context, around + context];
        the window clamps at both ends and may be empty. Unknown conversations return [].
        """
        self.validate()
        sql = "SELECT seq, role, ts, text FROM messages WHERE conversation_id = ?"
        params = [conv_id]
        if around is not None:
            sql += " AND seq BETWEEN ? AND ?"
            # Clamp so huge Python ints never overflow SQLite's 64-bit integers.
            top = 2**63 - 1
            params += [min(max(0, around - context), top), min(around + context, top)]
        sql += " ORDER BY seq"
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql, params).fetchall()]

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

    def _scope_clauses(self, repo: str = None, folder: str = None) -> tuple:
        clauses, params = [], []
        if repo is not None:
            sql, repo_params = self._repo_filter(repo, 'repo_key')
            clauses.append(sql)
            params += repo_params
        if folder is not None:
            clauses.append("cwd = ?")
            params.append(folder)
        return clauses, params

    def conversation_ids_for_scope(self, repo: str = None, folder: str = None) -> list:
        """Return ids of conversations in a scope: `repo` matches repo_key exactly or by
        final path component (as in search); `folder` matches cwd exactly (as in search
        and list). With neither, returns [] — callers must pick a scope explicitly."""
        self.validate()
        clauses, params = self._scope_clauses(repo, folder)
        if not clauses:
            return []
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM conversations WHERE " + " AND ".join(clauses)
                + " ORDER BY started_at DESC, id", params).fetchall()
            return [r['id'] for r in rows]

    def repo_count_for_scope(self, repo: str = None, folder: str = None) -> int:
        """Number of distinct repo_keys among the conversations in a scope (see
        conversation_ids_for_scope); lets a caller show how widely a basename matches."""
        self.validate()
        clauses, params = self._scope_clauses(repo, folder)
        if not clauses:
            return 0
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(DISTINCT repo_key) FROM conversations WHERE " + " AND ".join(clauses),
                params).fetchone()[0]

    def _prune_orphan_labels(self, conn):
        """Delete topics and keywords no conversation links to (their names derive from
        content that may just have been forgotten)."""
        conn.execute("DELETE FROM topics WHERE id NOT IN (SELECT topic_id FROM conversation_topics)")
        conn.execute("DELETE FROM keywords WHERE id NOT IN (SELECT keyword_id FROM conversation_keywords)")

    def _optimize_fts(self, conn):
        """Merge all FTS5 segments. An external-content 'delete' only appends a delete
        marker; the old segment keeps the (lowercased) terms until a merge rewrites it."""
        conn.execute("INSERT INTO messages_fts(messages_fts) VALUES ('optimize')")

    def _purge_free_space(self, conn) -> bool:
        """Rebuild the file (VACUUM drops pages freed earlier by any connection) and fold
        then truncate the WAL. Must run outside a transaction. Returns False if the WAL
        could not be fully truncated (e.g. another connection is reading)."""
        conn.execute("PRAGMA busy_timeout=2000")
        conn.execute("VACUUM")
        busy, log, checkpointed = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        return busy == 0 and checkpointed >= log

    def purge_free_space(self, example_id: str = '<session-id>') -> str | None:
        """Physically remove text freed earlier by any writer (VACUUM, then truncate the
        WAL). Idempotent, safe to run any time, and never raises: returns a warning
        string naming the retry command (`towit forget <example_id>`) if cleanup was
        incomplete, else None."""
        self.validate()
        retry = (f"Re-run `towit forget {example_id}` when no other towit process is "
                 f"active to finish cleanup.")
        try:
            with self.connect() as conn:
                if self._purge_free_space(conn):
                    return None
        except sqlite3.Error as exc:
            return (f"the conversations were forgotten, but physical cleanup was incomplete "
                    f"({exc}); deleted data may remain on disk. {retry}")
        return f"some deleted data may remain in the write-ahead log. {retry}"

    def forget_conversations(self, ids: list) -> int:
        """Permanently delete conversations and tombstone their ids; return how many existed.

        Forgets exactly the ids passed — a caller that resolved a scope and prompted the
        user passes the set matched at prompt time, so conversations that appear later
        are not swept up. One BEGIN IMMEDIATE transaction covers all ids, the orphan
        topic/keyword cleanup and the FTS merge, so a failure leaves nothing half
        forgotten. Deleting the conversation cascades to messages (whose delete trigger
        clears the FTS index) and to topic/keyword links. The tombstone keeps only the id
        and a timestamp. Ids that do not exist are ignored (no tombstone).

        After the commit, purge_free_space() VACUUMs and truncates the WAL. That never
        raises: on failure `self.cleanup_warning` holds a message and the forget itself
        still stands (it is None after a clean run).
        """
        self.validate()
        self.cleanup_warning = None
        forgotten = 0
        first_id = None
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                for conv_id in dict.fromkeys(ids):
                    if conn.execute("DELETE FROM conversations WHERE id = ?", (conv_id,)).rowcount:
                        conn.execute("INSERT OR IGNORE INTO forgotten (id) VALUES (?)", (conv_id,))
                        forgotten += 1
                        first_id = first_id or conv_id
                if forgotten:
                    self._prune_orphan_labels(conn)
                    self._optimize_fts(conn)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        if forgotten:
            self.cleanup_warning = self.purge_free_space(first_id)
        return forgotten

    def forget_conversation(self, conv_id: str) -> bool:
        """Forget one conversation (see forget_conversations); False if the id was unknown."""
        return self.forget_conversations([conv_id]) == 1

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

    def get_meta(self, key: str) -> str | None:
        """Return the value stored under `key` in the meta table, or None."""
        self.validate()
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            return row['value'] if row else None

    def set_meta(self, key: str, value: str) -> None:
        """Upsert a meta key/value pair."""
        self.validate()
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO meta (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, value),
            )

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
        self.validate()
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
