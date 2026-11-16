#!/usr/bin/env python3
"""Build a throwaway To Wit home for recording the README demo (see demo.tape).

Usage: python3 docs/demo/seed.py [DEMO_HOME]      (default /tmp/towit-demo)

Everything lives under DEMO_HOME, used as $HOME: a fake ~/.claude/projects with synthetic
transcripts, a ~/.towit database with LLM indexing off (titles, summaries, keywords and topics are
written directly), and a stub `claude` so `towit resume` prints its command instead of launching
Claude Code. Nothing in your real ~/.towit or ~/.claude is read or written. Session ids are
deterministic, so the ids in your recording script stay valid across reseeds.
"""
import json
import os
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timedelta, timezone

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEMO_HOME = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else '/tmp/towit-demo')
if os.path.basename(DEMO_HOME) != 'towit-demo':
    sys.exit(f"refusing to reset {DEMO_HOME}: the directory name must be 'towit-demo'")

API = f'{DEMO_HOME}/work/acme-api'
WEB = f'{DEMO_HOME}/work/acme-web'

# (key, cwd, start, title, summary, keywords, topics, [(role, text), ...])
SESSIONS = [
    ('retry', API, '2026-10-22T14:05:00Z',
     'Choosing a retry strategy for webhook delivery',
     'Compared fixed, linear and exponential retry for failed webhook deliveries; chose exponential '
     'backoff with jitter, six attempts, then a dead-letter queue.',
     ['webhooks', 'retry', 'backoff', 'dead-letter-queue'], ['Webhooks', 'Reliability'], [
         ('user', 'Customers say webhooks sometimes never arrive. How should we retry failed deliveries?'),
         ('assistant', 'Right now a failed delivery is dropped after one attempt. Three common options: '
                       'fixed interval, linear backoff, or exponential backoff with jitter.'),
         ('user', 'What goes wrong with a fixed interval?'),
         ('assistant', 'When a customer endpoint recovers, every queued retry fires at the same moment '
                       'and knocks it over again. That is the thundering herd problem.'),
         ('user', 'Okay. Which one do you recommend, and how many attempts?'),
         ('assistant', 'Use exponential backoff with jitter: delay = min(cap, base * 2^attempt) plus noise. Six attempts, then dead-letter.'),
         ('user', 'Decided: full jitter on exponential backoff, six attempts, then the dead-letter queue. Add a replay button.'),
         ('assistant', 'Done. I added a RetryPolicy class, a dead_letter_events table, and a test that '
                       'fakes the clock to verify the schedule.'),
     ]),
    ('index', API, '2026-10-27T10:30:00Z',
     'Slow orders query: adding a composite index',
     'The orders list took four seconds for large accounts; EXPLAIN showed a sequential scan. Added a '
     'composite index on account_id and created_at.',
     ['postgres', 'index', 'explain', 'performance'], ['Database', 'Performance'], [
         ('user', 'The orders page takes four seconds for our biggest accounts. Can you find out why?'),
         ('assistant', 'EXPLAIN ANALYZE shows a sequential scan over the orders table, then a sort. '
                       'The filter is on account_id and the order is by created_at.'),
         ('user', 'Would two single-column indexes help?'),
         ('assistant', 'Not much: Postgres would pick one and still sort. A composite index on '
                       '(account_id, created_at DESC) serves both the filter and the ordering.'),
         ('user', 'Go ahead, and use CONCURRENTLY so we do not lock writes.'),
         ('assistant', 'Migration added with CREATE INDEX CONCURRENTLY. The query now uses an index scan '
                       'and drops from four seconds to about twenty milliseconds.'),
     ]),
    ('ratelimit', API, '2026-11-03T16:20:00Z',
     'Rate limiting the public API',
     'Evaluated fixed window, sliding window and token bucket limits; chose a Redis token bucket at '
     '100 requests per minute per API key, with a Retry-After header.',
     ['rate-limit', 'redis', 'token-bucket', 'api'], ['API', 'Reliability'], [
         ('user', 'We need rate limiting on the public API before the partner launch. Options?'),
         ('assistant', 'Fixed window is simplest but allows bursts at the boundary. Sliding window is '
                       'smoother but costs more to store. A token bucket allows short bursts and a steady '
                       'average rate.'),
         ('user', 'Where do we keep the counters?'),
         ('assistant', 'Redis, with an atomic Lua script so the check and the decrement cannot race.'),
         ('user', 'Decision: token bucket in Redis, 100 requests per minute per API key. Return 429 with a '
                  'Retry-After header.'),
         ('assistant', 'Implemented as Rack middleware. Limits are configurable per key, and the 429 '
                       'response includes Retry-After and the remaining quota.'),
         ('user', 'Can partners get a higher limit?'),
         ('assistant', 'Yes: a rate_limit override column on api_keys, defaulting to NULL for the standard '
                       'limit.'),
     ]),
    ('flaky', API, '2026-11-10T09:15:00Z',
     'Fixing the flaky signup test',
     'The signup test failed on CI about one run in ten because of a timezone boundary; froze time in '
     'the test setup.',
     ['flaky-test', 'timezone', 'ci'], ['Testing'], [
         ('user', 'test_signup_sets_trial_end fails on CI about one run in ten. Local runs pass.'),
         ('assistant', 'The assertion compares trial_end with Date.today, but the app uses UTC and the CI '
                       'runner is in a different zone. Near midnight the two dates differ.'),
         ('user', 'So it only fails late in the evening for us?'),
         ('assistant', 'Exactly. Freezing the clock in the test makes it deterministic.'),
         ('user', 'Do that, and add a comment explaining why.'),
         ('assistant', 'Added travel_to(Time.utc(2026, 1, 15, 23, 30)) in setup, with a comment about the '
                       'midnight boundary. Ran the file fifty times with no failures.'),
     ]),
    ('darkmode', WEB, '2026-11-06T13:40:00Z',
     'Dark mode toggle flashes on page load',
     'The page flashed light before switching to dark; fixed by setting the theme attribute from an '
     'inline script in the document head before first paint.',
     ['dark-mode', 'css', 'flash', 'theme'], ['Frontend'], [
         ('user', 'When a user has dark mode on, the page flashes white for a moment on load. Why?'),
         ('assistant', 'The theme is applied by a script at the end of the body, after the first paint. '
                       'The browser renders the default light theme until it runs.'),
         ('user', 'Can we do it earlier?'),
         ('assistant', 'Yes: a tiny inline script in the head that reads localStorage and sets '
                       'data-theme on the html element before anything is painted.'),
         ('user', 'Do it, and keep the system preference as the fallback.'),
         ('assistant', 'Added the inline script with a prefers-color-scheme fallback. The flash is gone '
                       'in Chrome, Firefox and Safari.'),
     ]),
]

STUB_CLAUDE = '#!/bin/sh\necho "claude $*"\n'
DEMO_SHELL = f"""#!/bin/sh
# Clean prompt, demo home, stub claude. Exit the shell when done recording.
export HOME={DEMO_HOME}
export PATH={DEMO_HOME}/bin:$PATH
export PS1='$ '
cd {API}
exec zsh -f
"""


def encode_dir(path):
    return path.replace('/', '-').replace('.', '-')


def write(path, text, mode=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as fh:
        fh.write(text)
    if mode:
        os.chmod(path, mode)


def build():
    if os.path.exists(DEMO_HOME):
        shutil.rmtree(DEMO_HOME)
    for d in (API, WEB):
        os.makedirs(d)
    write(f'{DEMO_HOME}/bin/claude', STUB_CLAUDE, 0o755)
    write(f'{DEMO_HOME}/demo-shell.sh', DEMO_SHELL, 0o755)
    write(f'{DEMO_HOME}/.towit/config.toml', '[indexing]\nenabled = false\n')
    os.chmod(f'{DEMO_HOME}/.towit', 0o700)

    paths = {}
    for key, cwd, start, *_rest, msgs in SESSIONS:
        sid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f'towit-demo-{key}'))
        t = datetime.fromisoformat(start.replace('Z', '+00:00'))
        lines = []
        for i, (role, text) in enumerate(msgs):
            ts = (t + timedelta(minutes=2 * i)).astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
            lines.append(json.dumps({'type': role, 'timestamp': ts, 'cwd': cwd, 'sessionId': sid,
                                     'message': {'role': role, 'content': text}}))
        path = f'{DEMO_HOME}/.claude/projects/{encode_dir(cwd)}/{sid}.jsonl'
        write(path, '\n'.join(lines) + '\n')
        paths[key] = (sid, path)
    return paths


def main():
    paths = build()
    os.environ['HOME'] = DEMO_HOME           # before the towit modules read ~
    os.environ['TOWIT_CONFIG_PATH'] = f'{DEMO_HOME}/.towit/config.toml'
    for var in ('TOWIT_DB_PATH', 'TOWIT_SETTINGS_PATH', 'TOWIT_INDEXING'):
        os.environ.pop(var, None)
    for sub in ('setup', 'install-hook'):  # install-hook writes the demo home's settings.json only
        subprocess.run([f'{REPO}/bin/towit', sub], check=True, stdout=subprocess.DEVNULL)

    sys.path.insert(0, f'{REPO}/libexec/towit')
    import towit_ingest
    from towit_db import Database

    db = Database()
    for key, cwd, _start, title, summary, keywords, topics, msgs in SESSIONS:
        sid, path = paths[key]
        status = towit_ingest.ingest_transcript(path, db)
        parsed = towit_ingest.parse_transcript(path)
        db.upsert_conversation({
            'id': sid, 'folder': os.path.realpath(os.path.dirname(path)), 'cwd': cwd,
            'started_at': parsed.started_at, 'last_active': parsed.last_active,
            'title': title, 'summary': summary, 'message_count': len(msgs),
            'keywords': keywords, 'topics': topics,
        })
        print(f'{status:9} {sid}  {title}')
    print(f'\nDemo home ready: {DEMO_HOME}\nStart a clean shell with: {DEMO_HOME}/demo-shell.sh')


if __name__ == '__main__':
    main()
