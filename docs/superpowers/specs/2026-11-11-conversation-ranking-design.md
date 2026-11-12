# Conversation-Level Search Design

**Date:** 2026-11-11
**Status:** Approved; amended during planning (see "Planning amendments")
**Plan:** not written yet

## Overview

`towit search` indexes one row per message, and `towit_db.search_archive` ranks a conversation by its single best-matching message (`bm25`, lower is better). Two consequences:

- **Missed matches.** In the default `AND` mode every term has to appear in the same message. A conversation that mentions `redis` in one message and `timeout` in another does not match `redis timeout` at all.
- **Thin ranking.** A conversation about the topic throughout ranks the same as one with a single strong message, and recency only breaks exact ties between equal scores.

This change makes matching and ranking work per conversation, with no schema change.

## Goals

- `AND` matches a conversation when every term appears somewhere in it, in any of its messages
- Rank a conversation by how many query terms it covers, how well they match, and how many messages match, with recency as the tiebreak
- Keep every result that matches today, with the same `seq`, `snippet` and `score`: the change only adds matches and reorders (a result's order may change; its fields do not)
- No schema change, no migration, nothing new stored (so nothing new for `forget`, redaction or `SECURITY.md`)

## Non-Goals

- Tool-output searchability (a separate follow-up)
- A conversation-level FTS index or any new table
- Changing the metadata search (`search()` and the keyword, title, summary and topic matching), `--only` semantics, or the output format
- A new output column for the conversation rank (open question 3)

## Decisions

- Matching and ranking are designed together, because the rank depends on what counts as a match.
- The sort is a tuple (predictable, explainable and testable), not a blended score. Recency only breaks ties.
- A metadata match still outranks every text-only match.
- `score` in `--format json` and `csv` keeps its meaning: the representative message's `bm25`, lower is better.

## Design

### Matching

`search_archive(scope='all' | 'text')` keeps the current message-level query, built from `build_match_expression(terms, mode)`. Every conversation it finds keeps the `seq`, `snippet` and `score` it has today (a *co-occurrence hit*).

For a query with two or more distinct terms (after de-duplicating case-insensitively, capped at 8 terms) it also runs one single-term FTS query per term, with the same `--folder` and `--repo` filters, and groups the rows by conversation:

- `mode='and'`: a conversation matches when it appears in every term's result (a *spread hit* when no single message holds all the terms).
- `mode='or'`: matching is unchanged; the per-term rows only provide term coverage and counts for ranking.

A single-term query needs no per-term queries: the message-level query already returns every matching message, so the conversation's best `bm25` and match count come from its rows. `scope='metadata'` is unchanged. Queries beyond the 8-term cap skip the per-term queries and are ranked from the message-level rows only (terms covered counts as 1).

**Representative message** (the `seq` and snippet shown): the message that matches the most terms, ties broken by best `bm25`. For a co-occurrence hit this is today's message.

### Ranking

The key applies to every text search, single-term included (a conversation about the topic throughout should beat one with a single strong message). Within `scope='all'` results, sort by it, ascending:

| Order | Key |
|---|---|
| 1 | metadata match first (unchanged) |
| 2 | more query terms covered by the conversation |
| 3 | conversation score, lower is better |
| 4 | newer `started_at` |
| 5 | id |

**Conversation score** = `(Σ over terms of that term's best message bm25)` × `(1 + ln(n))` (for one term, that term's best bm25), where `n` is the number of distinct messages that match any term. FTS5 sums per-term contributions within a message, so when all terms sit in one message the sum equals that message's own `bm25`. This keeps co-occurrence and spread hits comparable. `bm25` values are negative and `n = 1` gives a multiplier of 1, so a single-hit conversation keeps its raw score. There is no tuned constant. Because `bm25` is negative, a larger multiplier makes the score more negative, i.e. better.

`limit` still caps text-only rows after sorting; metadata-tier rows are never dropped.

### Output

`score` is the representative message's `bm25`. For a co-occurrence hit it is today's value. For a spread hit the representative message matches only some of the terms, and `score` is the sum of that message's single-term `bm25` values for the terms it matches (`bm25` is additive over terms within a message, which a test pins). The conversation score is used only for ordering.

### Error handling

- A per-term query that FTS rejects (`is_fts_query_error`) counts as "no hits for that term": in `AND` mode it empties the intersection, in `OR` mode the term is skipped. Lock, I/O and non-FTS SQL errors propagate, as they do today.
- Terms that contain no letter or digit are dropped by `build_match_expression` and are not counted.
- The automatic `OR` retry in `towit_search` (printed on stderr when an `AND` search finds nothing) is unchanged. It triggers less often, because `AND` now means "all terms somewhere in the conversation".

### Cost

The extra cost is `k` single-term queries for a `k`-term search (`2 ≤ k ≤ 8`), grouped in Python. A read-only spike on a real archive (16,389 messages, 35 conversations) measured 0–16 ms per single-term query, and SQLite refuses `bm25()` inside an aggregate (`unable to use function bm25 in the requested context`), so SQL-side grouping is not available. The statement count stays constant in the number of conversations (bounded by the work-count tests).

## Testing

TDD, failing tests first, ZOMBIES:

- **Z:** no terms or no hits behave as today; a single term is unchanged.
- **O:** `redis` in message 3 and `timeout` in message 40 of one conversation: `redis timeout` finds it; a term absent everywhere does not match.
- **M:** more terms covered ranks first; several matching messages beat one equally good hit; recency breaks only exact ties; metadata matches stay first; co-occurrence and spread hits are ordered by the conversation score.
- **B:** the `limit` cap on text-only rows; more than 500 conversations (the batch size); duplicate terms; the 8-term cap; deterministic order on equal keys.
- **I:** `--format json` and `csv` keep `score` semantics; `--folder`, `--repo` and `scope` apply to the per-term queries; `towit show --around <seq>` accepts the representative message's `seq`.
- **E:** an FTS-rejected term; a non-FTS `OperationalError` still propagates.
- **S:** a multi-conversation scenario through the CLI in BATS.
- **Compat pin:** the 17 pin cases in `towit_db_test.py` are re-captured, not left untouched, because ranking now applies to every search. The invariant that must hold for every conversation the old code returned: same `seq`, `snippet` and `score` (and the same metadata fields). Only the order may differ, and each reordered pin is reviewed and explained in the commit. Multi-term `AND` pins may also gain conversations.

## Documentation

- **README:** the Search section's ranking sentence and the `AND`/`OR` paragraph; whether the `--or` usage line needs a rewording is confirmed in the plan.
- **`bin/towit` help:** only if the `--or` wording changes.
- **`AGENTS.md`:** one sentence under `towit_db.py`.
- **`SECURITY.md`:** unaffected.
- **CHANGELOG:** a `Changed` entry (`AND` matches more than before). The release version (0.9.7 or 0.10.0) is decided at release time.

## Delivery

Three commits of under 300 lines each: per-term grouping and matching, then the ranking key, then docs.

## Planning amendments

- Ranking by match count applies to single-term searches too (decided with the user while planning); the single-term carve-out in the first draft is removed.
- Open question 1 (aggregating `bm25` in SQL) is closed by a spike: it is not possible, so rows are grouped in Python; cost is negligible.
- Open question 2 (`score` for a spread hit) is closed: the sum of the representative message's single-term `bm25` values.
- Open question 3 (exposing the conversation rank) stays closed: it is internal.
- Representative message: when a conversation has a row in the message-level query, that row is the representative for `AND` and `OR` alike (so a result's `seq`, `snippet` and `score` never change); only a spread hit gets a computed representative (most terms covered, ties to the lowest sum of single-term `bm25`). Spread-hit snippets are taken under the `OR` expression of the same terms.
