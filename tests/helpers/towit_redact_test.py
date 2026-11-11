# Tests for libexec/towit/towit_redact.py
#
# Run with: python3 tests/helpers/towit_redact_test.py

import io
import os
import sys
import time
import unittest
import unittest.mock

HELPERS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'libexec', 'towit'))
sys.path.insert(0, HELPERS_DIR)

import towit_redact
from towit_redact import REDACTION_PATTERNS, redact

# Fake secrets are assembled from pieces so this file never contains a complete
# secret-shaped literal.
FAKE_SECRETS = {
    'aws_key_id': 'AKIA' + 'A' * 16,
    'github_token': 'gh' + 'p_' + 'a' * 36,
    'anthropic_key': 'sk-' + 'ant-' + 'api03-' + 'a' * 40,
    'openai_key': 'sk-' + 'a1b2' * 12,
    'stripe_key': 'sk_' + 'live_' + 'a' * 24,
    'slack_token': 'xox' + 'b-' + '1234567890-' + 'a' * 12,
    'jwt': 'eyJ' + 'a' * 10 + '.eyJ' + 'b' * 10 + '.' + 'c' * 10,
    'private_key': '-----BEGIN RSA ' + 'PRIVATE KEY-----\n' + 'MIIB' * 10 + '\n-----END RSA ' + 'PRIVATE KEY-----',
    'bearer_token': 'Bearer ' + 'a1b2c3' * 6,
    'url_credentials': 'https://user:' + 'pw123456' + '@example.com/path',
    'secret_assignment': 'API_' + 'TOKEN=' + 'a1b2c3d4' * 3,
}


class TestRedactKinds(unittest.TestCase):
    def test_every_kind_has_a_fake_secret(self):
        self.assertEqual(set(REDACTION_PATTERNS), set(FAKE_SECRETS))

    def test_each_kind_is_redacted(self):
        for kind, secret in FAKE_SECRETS.items():
            with self.subTest(kind=kind):
                out = redact('before ' + secret + ' after')
                self.assertIn('[REDACTED:%s]' % kind, out)
                # Compare against the secret's sensitive core, not scheme/key name
                core = secret.split('=')[-1].split(':')[-1].split('@')[0].split(' ')[-1]
                if kind == 'private_key':
                    core = 'MIIB' * 10
                self.assertNotIn(core, out)
                self.assertTrue(out.startswith('before '))
                self.assertTrue(out.endswith(' after'))

    def test_url_credentials_keep_scheme_and_host(self):
        self.assertEqual(
            redact('postgresql://user:pw123456@db.internal:5432/x'),
            'postgresql://[REDACTED:url_credentials]@db.internal:5432/x')

    def test_secret_assignment(self):
        value = 'a1b2c3d4' * 3
        out = redact('STRIPE_WEBHOOK_SECRET=' + value)
        self.assertEqual(out, 'STRIPE_WEBHOOK_SECRET=[REDACTED:secret_assignment]')

    def test_secret_assignment_quoted_and_colon(self):
        value = 'a1b2c3d4' * 3
        self.assertNotIn(value, redact('password: "%s"' % value))
        self.assertNotIn(value, redact("db_password = '%s'" % value))

    def test_password_values_redacted_regardless_of_shape(self):
        # Passphrases need no digit; special characters must not end the value early.
        for value in ['correcthorsebatterystaple', 'Sup3r$' + 'ecretPassw0rd!xyz',
                      'abcdefghij0123!' + 'tail9999']:
            with self.subTest(value=value):
                out = redact('PASSWORD=' + value)
                self.assertEqual(out, 'PASSWORD=[REDACTED:secret_assignment]')
                self.assertEqual(redact(out), out)

    def test_secret_assignment_length_boundary(self):
        self.assertEqual(redact('API_TOKEN=' + 'a1' * 7 + 'b'), 'API_TOKEN=' + 'a1' * 7 + 'b')  # 15 chars
        out = redact('API_TOKEN=' + 'a1' * 8)  # 16 chars
        self.assertEqual(out, 'API_TOKEN=[REDACTED:secret_assignment]')
        self.assertEqual(redact(out), out)

    def test_secret_assignment_digit_late_in_value(self):
        out = redact('API_TOKEN=' + 'abcdefghijklmnopqrs' + '7')
        self.assertEqual(out, 'API_TOKEN=[REDACTED:secret_assignment]')

    def test_secret_assignment_special_chars_for_non_password_key(self):
        out = redact('API_SECRET=' + 'ab$cd!ef#gh%ij1kl')
        self.assertEqual(out, 'API_SECRET=[REDACTED:secret_assignment]')

    def test_all_letter_bare_value_under_non_password_key_is_not_redacted(self):
        # Known best-effort limit: without a digit, a bare-word value looks like
        # an identifier (max_tokens = some_long_name), so it is left alone.
        text = 'API_TOKEN=' + 'abcdefghijklmnopqrstuvwxyz'
        self.assertEqual(redact(text), text)

    def test_bearer_keeps_prefix(self):
        out = redact('Authorization: Bearer ' + 'a1b2c3' * 6)
        self.assertEqual(out, 'Authorization: Bearer [REDACTED:bearer_token]')


class TestRedactSafety(unittest.TestCase):
    def test_benign_text_unchanged(self):
        samples = [
            'Please refactor the indexer so that it skips trivial sessions.',
            '/Users/alice/src/myapp/libexec/towit/towit_index.py:120',
            'commit 7cb8dec0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6 fixed it',
            'reindex_delta = 2',
            'max_tokens = max_output_tokens_default',
            'the secret to good tests is a fast feedback loop',
            'see https://example.com/docs/page?x=1',
            'user@example.com wrote: Bearer of bad news',
        ]
        for s in samples:
            with self.subTest(s=s):
                self.assertEqual(redact(s), s)

    def test_idempotent(self):
        text = '\n'.join(FAKE_SECRETS.values()) + '\nplain text'
        once = redact(text)
        self.assertEqual(redact(once), once)

    def test_empty_and_non_string(self):
        self.assertEqual(redact(''), '')
        self.assertIsNone(redact(None))

    def test_deterministic(self):
        text = 'x ' + FAKE_SECRETS['github_token']
        self.assertEqual(redact(text), redact(text))

    def test_long_near_matches_are_fast(self):
        pieces = ['AKIA', 'ghp_', 'sk-ant-', 'sk-', 'xoxb-', 'eyJ', 'eyJa.eyJ',
                  '-----BEGIN PRIVATE KEY-----', 'Bearer ', '://', '://user:',
                  'SECRET=', 'TOKEN: "', 'KEY', 'sk_live_', 'a' * 5]
        for piece in pieces:
            with self.subTest(piece=piece):
                text = (piece * (200000 // len(piece) + 1))[:200000]
                start = time.monotonic()
                redact(text)
                self.assertLess(time.monotonic() - start, 1.0)
        for text in ['a' * 200000, '-' * 200000, ' ' * 200000, 'A_' * 100000,
                     'eyJ-' * 50000, 'key=' * 50000]:
            start = time.monotonic()
            redact(text)
            self.assertLess(time.monotonic() - start, 1.0)


class TestExtraPatterns(unittest.TestCase):
    def setUp(self):
        towit_redact._warned.clear()
        towit_redact._extra_cache.clear()

    def test_extra_pattern(self):
        self.assertEqual(redact('order 99-ABC', [r'\d{2}-[A-Z]{3}']), 'order [REDACTED:custom]')

    def test_invalid_extra_pattern_is_ignored_with_warning(self):
        err = io.StringIO()
        with unittest.mock.patch('sys.stderr', err):
            out = redact('keep (this)', ['('])
            redact('keep (this)', ['('])
        self.assertEqual(out, 'keep (this)')
        self.assertIn('towit', err.getvalue())
        self.assertEqual(err.getvalue().count('invalid'), 1)  # warned once

    def test_invalid_pattern_does_not_disable_valid_ones(self):
        err = io.StringIO()
        with unittest.mock.patch('sys.stderr', err):
            out = redact('order 99-ABC', ['(', r'\d{2}-[A-Z]{3}'])
        self.assertEqual(out, 'order [REDACTED:custom]')

    def test_empty_matching_pattern_ignored(self):
        err = io.StringIO()
        with unittest.mock.patch('sys.stderr', err):
            self.assertEqual(redact('abc', ['x*']), 'abc')


if __name__ == '__main__':
    unittest.main()
