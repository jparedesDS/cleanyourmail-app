"""Fake CleanYourMail sidecar for tests.

The real sidecar is a frozen executable and never runs in unit tests. This
script imitates it with three environment variables:

- ``FAKE_CLI_RESPONSE``: path to a file whose text is printed to stdout as is
  (JSON payloads and plain ``--version`` lines both work).
- ``FAKE_CLI_EXIT``: process exit code, 0 when unset.
- ``FAKE_CLI_ARGV``: path to a JSON file that records ``sys.argv[1:]``.
- ``FAKE_CLI_STDERR``: optional path to a file printed to stderr.

Run it as ``python fake_cli.py <args>``; the client is given
``[sys.executable, str(fake_cli)]`` so no launcher is needed on Windows.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def main() -> int:
    argv_path = os.environ.get("FAKE_CLI_ARGV")
    if argv_path:
        Path(argv_path).write_text(
            json.dumps(sys.argv[1:]), encoding="utf-8"
        )

    response_path = os.environ.get("FAKE_CLI_RESPONSE")
    if response_path:
        sys.stdout.write(_read(response_path))
        sys.stdout.flush()

    stderr_path = os.environ.get("FAKE_CLI_STDERR")
    if stderr_path:
        sys.stderr.write(_read(stderr_path))
        sys.stderr.flush()

    try:
        return int(os.environ.get("FAKE_CLI_EXIT", "0"))
    except ValueError:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
