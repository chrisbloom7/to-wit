# Conversation-Level Search Design

**Date:** 2026-11-11
**Status:** Draft, awaiting review
**Plan:** not written yet

## Overview

`towit search` indexes one row per message, and `towit_db.search_archive` ranks a conversation by its single best-matching message (`bm25`, lower is better). Two consequences:

- **Missed matches.** In the default `AND` mode every term has to appear in the same message. A conversation that mentions `redis` in one message and `timeout` in another does not match `redis timeout` at all.
- **Thin ranking.** A conversation about the topic throughout ranks the same as one with a single strong message, and recency only breaks exact ties between equal scores.

This change makes matching and ranking work per conversation, with no schema change.

## Goals

- `AND` matches a conversation when every term appears somewhere in it, in any of its messages
- Rank a conversation by how many query terms it covers, how well they match, and how many messages match, with recency as the tiebreak
- Keep every result that matches today, with the same `seq`, `snippet` and `score`: the change only adds matches and reorders
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

A single-term query, `scope='metadata'`, and queries beyond the 8-term cap take today's code path.

**Representative message** (the `seq` and snippet shown): the message that matches the most terms, ties broken by best `bm25`. For a co-occurrence hit this is today's message.

### Ranking

Within `scope='all'` results, sort by this key, ascending:

| Order | Key |
|---|---|
| 1 | metadata match first (unchanged) |
| 2 | more query terms covered by the conversation |
| 3 | conversation score, lower is better |
| 4 | newer `started_at` |
| 5 | id |

**Conversation score** = `(Σ over terms of that term's best message bm25)` × `(1 + ln(n))`, where `n` is the number of distinct messages that match any term. FTS5 sums per-term contributions within a message, so when all terms sit in one message the sum equals that message's own `bm25`. This keeps co-occurrence and spread hits comparable. `bm25` values are negative and `n = 1` gives a multiplier of 1, so a single-hit conversation is scored as it is today. There is no tuned constant.

`limit` still caps text-only rows after sorting; metadata-tier rows are never dropped.

### Output

`score` is the representative message's `bm25`. When that message matches only some of the terms (a spread hit), it is the `bm25` of the message under the terms it matches (open question 2). The conversation score is used only for ordering.

### Error handling

- A per-term query that FTS rejects (`is_fts_query_error`) counts as "no hits for that term": in `AND` mode it empties the intersection, in `OR` mode the term is skipped. Lock, I/O and non-FTS SQL errors propagate, as they do today.
- Terms that contain no letter or digit are dropped by `build_match_expression` and are not counted.
- The automatic `OR` retry in `towit_search` (printed on stderr when an `AND` search finds nothing) is unchanged. It triggers less often, because `AND` now means "all terms somewhere in the conversation".

### Cost

The extra cost is `k` single-term queries for a `k`-term search (`2 ≤ k ≤ 8`). Before the plan is final, time it read-only against a real archive. If it is noticeably slower than today, group rows in SQL (open question 1) or lower the cap.

## Testing

TDD, failing tests first, ZOMBIES:

- **Z:** no terms or no hits behave as today; a single term is unchanged.
- **O:** `redis` in message 3 and `timeout` in message 40 of one conversation: `redis timeout` finds it; a term absent everywhere does not match.
- **M:** more terms covered ranks first; several matching messages beat one equally good hit; recency breaks only exact ties; metadata matches stay first; co-occurrence and spread hits are ordered by the conversation score.
- **B:** the `limit` cap on text-only rows; more than 500 conversations (the batch size); duplicate terms; the 8-term cap; deterministic order on equal keys.
- **I:** `--format json` and `csv` keep `score` semantics; `--folder`, `--repo` and `scope` apply to the per-term queries; `towit show --around <seq>` accepts the representative message's `seq`.
- **E:** an FTS-rejected term; a non-FTS `OperationalError` still propagates.
- **S:** a multi-conversation scenario through the CLI in BATS.
- **Compat pin:** every existing search test, including the 17 pin cases in `towit_db_test.py`, passes unchanged: that is the proof that results which match today do not move.

## Documentation

- **README:** the Search section's ranking sentence and the `AND`/`OR` paragraph; whether the `--or` usage line needs a rewording is confirmed in the plan.
- **`bin/towit` help:** only if the `--or` wording changes.
- **`AGENTS.md`:** one sentence under `towit_db.py`.
- **`SECURITY.md`:** unaffected.
- **CHANGELOG:** a `Changed` entry (`AND` matches more than before). The release version (0.9.7 or 0.10.0) is decided at release time.

## Delivery

Three commits of under 300 lines each: per-term grouping and matching, then the ranking key, then docs.

## Open Questions

1. Can `bm25` be aggregated per conversation in SQL, or must Python group the rows? Decided by a timing spike on a real archive.
2. How exactly is `score` defined for a spread hit whose representative message matches only some of the terms?
3. Should the conversation-level rank be exposed as an output field, or stay internal?
