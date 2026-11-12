# Conversation-Level Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `towit search` matches a conversation when every term appears somewhere in it, and ranks conversations by terms covered, match quality and number of matching messages, with recency as the tiebreak.

**Architecture:** `towit_db.search_archive` keeps its message-level FTS query and adds one single-term query per term (2 to 8 distinct terms). A pure function groups all rows by conversation and produces, per conversation, a representative message (`seq`, `snippet`, `score`) and an ordering key. No schema change.

**Tech Stack:** Python 3.11+ stdlib, SQLite FTS5, `unittest`, BATS.

**Spec:** [docs/superpowers/specs/2026-11-11-conversation-ranking-design.md](../specs/2026-11-11-conversation-ranking-design.md)

## Global Constraints

- No schema change, no migration, nothing new stored; all SQL stays in `libexec/towit/towit_db.py`, parameterized, FTS expressions built only by `build_match_expression`.
- A result's `seq`, `snippet`, `score` and metadata fields never change for a conversation the old code returned; only order and membership may change (spec, Goals).
- `score` in `--format json`/`csv` keeps its meaning: the representative message's `bm25`, lower is better. The conversation score orders results and is never output.
- Per-term queries: only for 2 to `MAX_RANK_TERMS = 8` distinct terms; fewer or more use the message-level rows only (terms covered counts as 1).
- Statement count must stay constant in the number of conversations (`TestSearchArchiveWorkCount`).
- Directives: plan approved before code; failing tests first; commits of at most 300 changed lines (ask before exceeding); `wt switch --create`, never raw `git worktree`.

## Clarifications to the spec

- **Representative message.** When a conversation has a row in the message-level query (today's query), that row is the representative, for `AND` and `OR` alike. Only a spread hit (matched by per-term queries but by no single message) gets a computed representative: the message covering the most terms, ties broken by the lowest sum of single-term `bm25`; its `score` is that sum. This is what keeps the "same `seq`, `snippet`, `score`" guarantee true for `OR` searches, where today's best message can match a single term.
- **Snippets.** A spread-hit message does not satisfy the full `AND` expression, so its snippet is taken under the `OR` expression of the same terms. Message-level rows keep the expression they use today.
- **Branching.** Implementation branch `feat/conversation-ranking` is cut from `main` (the spec and this plan merge separately in a docs PR).

## Review Focus

Inputs the spec implies but no task's behavior tests cover by default; each has a test in the owning task.

1. One conversation with hundreds of matching messages (counted once as one result, `n` correct) — Task 1.
2. Terms in a different order (`timeout redis` vs `redis timeout`) give identical results and order — Task 2.
3. A forgotten conversation never appears as a spread hit — Task 2.
4. Hostile or non-searchable extra terms (`'"'`, `'*'`) next to a real one behave as the single real term — Task 2.
5. Duplicate terms that differ only in case (`Redis`, `redis`) count once — Task 1.

## File Structure

- Modify: `libexec/towit/towit_db.py` (grouping function, `distinct_search_terms`, `_term_rows`, `search_archive`).
- Modify: `tests/helpers/towit_db_test.py` (new test classes, pin re-capture, work-count test).
- Modify: `tests/bin/towit.bats` (one scenario test).
- Modify: `README.md`, `AGENTS.md`, `CHANGELOG.md` (and `bin/towit` or `towit_search.py` help only if the `--or` wording changes).

---

### Task 1: Pure grouping and the score formula

**Files:**
- Modify: `libexec/towit/towit_db.py` (module level, next to `build_match_expression`)
- Test: `tests/helpers/towit_db_test.py` (new classes `TestDistinctSearchTerms`, `TestGroupConversationHits`, `TestBm25Additivity`)

**Interfaces:**
- Produces: `MAX_RANK_TERMS = 8`; `distinct_search_terms(terms: list) -> list` (keeps terms with at least one letter or digit, de-duplicates case-insensitively, keeps first-seen order and spelling); `ConversationHit` (frozen dataclass: `conv_id: str, rowid: int, seq: int, message_score: float, terms_covered: int, rank_score: float, spread: bool`); `group_conversation_hits(term_rows: list, message_rows: list | None, mode: str = 'and') -> dict` mapping conversation id to `ConversationHit`.
- Row shape (dict-like with keys `id`, `seq`, `rowid`, `score`): `term_rows[i]` are the rows of term `i`'s single-term query; `message_rows` are the rows of the message-level query (best-first), or `None`.

- [ ] **Step 1: Write the failing tests**

`TestDistinctSearchTerms`: `['Redis', 'redis', 'timeout']` gives `['Redis', 'timeout']`; `['"', '*', 'redis']` gives `['redis']`; `[]` gives `[]`.

`TestGroupConversationHits` (plain dict rows, no database):
- `test_no_rows_gives_no_hits`: `([], None)` and `([[]], [])` both give `{}`.
- `test_single_term_one_message`: one row `c1, seq 2, rowid 10, score -3.0`: `terms_covered == 1`, `rank_score == -3.0`, `spread is False`, `(seq, rowid, message_score) == (2, 10, -3.0)`.
- `test_many_matches_scale_the_score` (Review Focus 1): one term, 300 rows for `c1` with score `-1.0` and distinct rowids: one entry, `rank_score == -1.0 * (1 + math.log(300))`, representative is the lowest-score row, ties to the lowest rowid.
- `test_and_spread_hit`: term 0 in message rowid 1 (score -2.0), term 1 in message rowid 2 (score -3.0), `message_rows=[]`, mode `and`: matched, `spread is True`, `terms_covered == 2`, `rank_score == (-2.0 + -3.0) * (1 + math.log(2))`, representative is rowid 2 (lowest sum), `message_score == -3.0`.
- `test_and_requires_every_term`: term 1 has no row for `c1`: `{}` for mode `and`; mode `or` returns `c1` with `terms_covered == 1`.
- `test_message_level_row_is_the_representative`: `message_rows` holds `c1, seq 5, rowid 7, score -4.0`: representative is that row, `spread is False`, `message_score == -4.0`.
- `test_spread_representative_prefers_more_terms`: mode `or`, `message_rows=None`, rowid 1 matches terms 0 and 1, rowid 2 matches only term 0 with a better score: representative is rowid 1, `message_score` is the sum of rowid 1's two single-term scores.
- `test_equal_scores_are_deterministic`: two rows with equal scores: the lower `rowid` wins in both input orders.

`TestBm25Additivity` (real `Database`, temp file): one message containing `alpha` and `beta`: `bm25` under `build_match_expression(['alpha','beta'], 'and')` equals the sum of the two single-term `bm25` values (`assertAlmostEqual`, 5 places). If this fails, stop: the `rank_score` formula needs revisiting with the user.

- [ ] **Step 2: Run to verify failure**

Run: `./run-tests tests/helpers/towit_db_test.py --filter "DistinctSearchTerms|GroupConversationHits|Bm25Additivity"` (the additivity test may pass already; it validates the formula, the others must fail with `ImportError`/`AttributeError`).

- [ ] **Step 3: Implement** `distinct_search_terms`, `ConversationHit` and `group_conversation_hits` in `towit_db.py`.

  Per conversation: `terms_covered` is the number of terms with at least one row; a conversation matches in `and` mode only if every term has a row; `n` is the number of distinct `rowid`s over all terms; `rank_score` is the sum over covered terms of that term's lowest score, multiplied by `1 + ln(n)`; the representative follows the Clarifications section. Row order never matters, ties break on the lowest `rowid`.

- [ ] **Step 4: Run to verify pass:** `./run-tests tests/helpers/towit_db_test.py`

- [ ] **Step 5: Commit** (`feat: group search hits by conversation`, tests and code together).

---

### Task 2: Wire matching and ranking into `search_archive`

**Files:**
- Modify: `libexec/towit/towit_db.py` (`_term_rows`, `search_archive`)
- Test: `tests/helpers/towit_db_test.py` (`TestSearchArchive`, `TestSearchArchiveOutputPins`, `TestSearchArchiveWorkCount`, and `tests/helpers/towit_forget_test.py` only if it asserts multi-term results)

**Interfaces:**
- Consumes: `distinct_search_terms`, `group_conversation_hits`, `MAX_RANK_TERMS`, `ConversationHit`, `build_match_expression`, `_text_match_query(folder, repo)`, `is_fts_query_error`, `_hit_snippets`.
- Produces: `Database._term_rows(self, conn, terms: list, folder, repo) -> list` (one list of rows per term, each term's query built with `build_match_expression([term], 'and')`; a query FTS rejects gives `[]` for that term, other errors propagate). `search_archive`'s signature is unchanged.

- [ ] **Step 1: Write the failing tests** in `TestSearchArchive` (fixture helpers `_conv`, `_m`; add a small `_archive(cid, texts, **conv)` helper):
  - `test_and_matches_terms_spread_across_messages`: `redis` in message 1 and `timeout` in message 5 of `s10`: `search_archive(['redis', 'timeout'], scope='text')` returns `s10`, with `seq` of the lower-scoring message and a snippet that contains `[`.
  - `test_and_needs_every_term_somewhere`: a conversation with only `redis` is not returned for `['redis', 'timeout']`.
  - `test_co_occurrence_hit_keeps_todays_seq_snippet_score`: both terms in one message: result equals what the message-level query alone gave (compare to the pinned value for the existing fixture).
  - `test_more_terms_covered_ranks_first` (mode `or`): conversation covering both terms ranks above one covering one term with a better bm25.
  - `test_more_matching_messages_beats_one_equal_hit`: single term, equal best score, three matching messages versus one: the three-message conversation is first.
  - `test_recency_only_breaks_exact_ties`: equal keys, newer `started_at` first; a worse-scoring newer conversation does not outrank a better-scoring older one.
  - `test_metadata_match_still_first`: a keyword-matched conversation outranks a text-only conversation with more matches.
  - `test_term_order_does_not_change_results` (Review Focus 2): `['redis','timeout']` and `['timeout','redis']` return the same ids in the same order.
  - `test_forgotten_conversation_is_not_a_spread_hit` (Review Focus 3): after `db.forget`, a spread-hit conversation is gone.
  - `test_unsearchable_extra_terms_are_ignored` (Review Focus 4): `['redis', '"', '*']` equals `['redis']`.
  - `test_folder_and_repo_filters_apply_to_spread_hits`, `test_limit_caps_text_only_spread_hits`, `test_more_than_500_conversations_spread` (batch size), `test_nine_terms_use_message_level_rows_only` (cap).
  - `test_fts_rejected_term_in_and_mode_empties_text_hits` (patch the connection like `_FailingMatchConn`; metadata hits still returned) and `test_non_fts_operational_error_propagates`.
  - Work count: `test_multi_term_statements_are_constant` in `TestSearchArchiveWorkCount`: two terms, 5 versus 30 conversations, the statement count grows by at most 2 and stays at most 16.

- [ ] **Step 2: Run to verify failure:** `./run-tests tests/helpers/towit_db_test.py --filter "SearchArchive"`. Confirm each new test fails for the intended reason; the existing pins still pass at this point.

- [ ] **Step 3: Implement** `_term_rows` and rewire `search_archive`:
  - message-level rows: keep today's query but collect all rows, best-first;
  - `per_term = self._term_rows(...)` only when `2 <= len(distinct) <= MAX_RANK_TERMS`, otherwise `[message_rows]`;
  - `hits = group_conversation_hits(per_term, message_rows, mode)`;
  - order by `(i not in meta_by_id, i not in hits, -terms_covered, rank_score, newer started_at, id)`, keeping the existing stable-sort passes for the recency and id tiebreaks and `0.0` for conversations without a text hit;
  - snippets: `_hit_snippets` under `expr` for rows from the message-level query, and once more under `build_match_expression(distinct, 'or')` for spread hits;
  - result fields `seq`, `snippet`, `score` come from the representative.

- [ ] **Step 4: Re-capture the pins.** Run `TestSearchArchiveOutputPins`. For every failing case, print old versus new, check the invariant (same fields per conversation, only order or membership differ; `and_two_terms`, `or_two_terms`, `all_or` may gain rows), update `SNIPPET_PIN_EXPECTED` in place, and add a comment above each changed entry saying why. List the reordered cases in the commit message. If any conversation's `seq`, `snippet` or `score` changed, stop: that breaks the spec guarantee.

- [ ] **Step 5: Run to verify pass:** `./run-tests` (full suite).

- [ ] **Step 6: Commit** (`feat: match and rank search results per conversation`). If the diff exceeds 300 lines because of the pin re-capture, ask before committing it as one.

---

### Task 3: CLI scenario

**Files:**
- Test: `tests/bin/towit.bats`

- [ ] **Step 1: Write the failing test** `towit: search matches terms spread across messages and keeps the any-term retry`: following the end-to-end test's setup (indexing disabled, `setup`, a `sessions` directory, `backfill --folder`), archive two sessions: `session-rank-0001` with `redis` in one message and `timeout` in another, `session-rank-0002` with only `redis`. Assert: `search redis timeout --format json` returns only `session-rank-0001`; `score` and `seq` are present; `search redis zzzmissing` still prints `No results for all terms; showing results matching any term.` on stderr and returns `session-rank-0002` and `session-rank-0001`.
- [ ] **Step 2: Confirm red, then green.** Run `./run-tests tests/bin/towit.bats --filter "spread across messages"` on a checkout of `main` (the spread-hit assertion must fail there), then on the feature branch (it must pass).
- [ ] **Step 3: Commit** (`test: cover conversation-level search through the CLI`).

---

### Task 4: Docs

**Files:**
- Modify: `README.md`, `AGENTS.md`, `CHANGELOG.md`; `bin/towit` and `libexec/towit/towit_search.py` only if the `--or` wording changes.

- [ ] **Step 1:** README Search section: replace "ranks conversations with a metadata match first and then by relevance (`bm25`) of the best-matching message" with the tuple order (metadata match, terms covered, relevance and number of matching messages, recency); in the AND/OR paragraph state that all terms may appear in different messages of a conversation, that the stderr retry is unchanged, and that ranking looks at the first 8 distinct terms. Line ~99: `--or` reads "Match any term instead of all terms in the conversation" only if the help text is changed to match.
- [ ] **Step 2:** `AGENTS.md`: one sentence under `towit_db.py` on conversation-level matching and ranking (`group_conversation_hits`, the 8-term cap).
- [ ] **Step 3:** `CHANGELOG.md` under `## [Unreleased]` `### Changed`: `towit search` matches a conversation when every term appears somewhere in it (not only in one message) and ranks conversations by terms covered, relevance, number of matching messages and recency; results that matched before keep their message, snippet and score, but their order can change.
- [ ] **Step 4:** Run `TOWIT_RELEASE_CHECK=1 ./run-tests tests/helpers/docs_consistency_test.py` (must pass), `bin/towit help`, then `./run-tests`.
- [ ] **Step 5: Commit** (`docs: document conversation-level search`).

## Delivery

Branch `feat/conversation-ranking`; four commits (code and tests together for Tasks 1 and 2, then CLI test, then docs); push and open the PR only after the user approves; release as 0.9.7 or 0.10.0 (decided at release time via the `release-towit` skill).
