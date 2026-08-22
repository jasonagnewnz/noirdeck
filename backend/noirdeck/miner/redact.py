"""Secret-shape redaction. Applied to ALL transcript text before it reaches an LLM
prompt. Matches by VALUE shape, not filename (estate rule: filename scans miss
hardcoded secrets). Raw matches are never logged: only counts."""

from __future__ import annotations

import re

PATTERNS: list[tuple[str, re.Pattern]] = [
    (
        "private_key_block",
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]{0,8000}?-----END [A-Z ]*PRIVATE KEY-----"),
    ),
    ("aws_access_key", re.compile(r"\b(A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16}\b")),
    ("github_token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{36,}\b")),
    ("github_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}\b")),
    ("anthropic_key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{32,}\b")),
    ("slack_token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("google_key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{5,}\b")),
    ("bearer_header", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")),
    ("stripe_key", re.compile(r"\bsk_(live|test)_[A-Za-z0-9]{16,}\b")),
    (
        "kv_secret",
        # The keyword is NOT anchored with \b. `_` is a word character, so
        # \bpassword\b cannot match the PASSWORD inside DB_PASSWORD: which meant
        # SCREAMING_SNAKE_CASE=value, the commonest shape a secret takes in
        # terminal output and .env files, went through completely unredacted
        # (PASSWORD= was caught, DB_PASSWORD= was not). The surrounding
        # [A-Za-z0-9_.-]* lets the keyword sit anywhere inside an identifier, and
        # the lookarounds treat `_` as a separator rather than a letter.
        # Over-redaction is the safe direction here; under-redaction leaks.
        re.compile(
            r"(?i)(?<![A-Za-z0-9])[A-Za-z0-9_.-]*"
            r"(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret|credential)"
            r"[A-Za-z0-9_.-]*\s*[=:]\s*[\"']?[^\s\"',;]{6,}"
        ),
    ),
]


def redact(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    for name, pat in PATTERNS:
        text, n = pat.subn(f"[REDACTED:{name}]", text)
        if n:
            counts[name] = n
    return text, counts
