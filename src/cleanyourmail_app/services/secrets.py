"""Write the sidecar's ``password_file`` with owner-only access.

The app password is the one secret the app itself handles. It is written
directly to the path named by the config's ``password_file``; it never goes
through ``argv``, QSettings, a JSON file, a log or an error message.

The write is atomic and private: a temporary file is created in the target
directory with ``mkstemp`` (0600 on POSIX), flushed to disk, then
``os.replace``d over the target. On Windows the inherited ACL is replaced with
a grant for the current user, best effort: the file is already written and a
missing ``icacls`` must not undo a saved password.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

#: How long ``icacls`` may take before the ACL step is abandoned silently.
_ACL_TIMEOUT_SECONDS = 30


def save_app_password(path: str | os.PathLike[str], value: str) -> None:
    """Write ``value`` to ``path`` exactly, without a trailing newline.

    Rejects an empty or whitespace-only value and a directory target. The
    parent directory is created when missing. Nothing is printed or logged,
    and an exception never echoes the secret.
    """
    if not isinstance(value, str) or not value.strip():
        # The message deliberately contains no fragment of the value.
        raise ValueError("The app password cannot be empty or whitespace only.")

    target = Path(path)
    if target.is_dir():
        raise IsADirectoryError(f"The app password path is a directory: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)

    descriptor, temporary = tempfile.mkstemp(
        dir=str(target.parent),
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
            if os.name != "nt" and hasattr(os, "fchmod"):
                os.fchmod(handle.fileno(), 0o600)
        os.replace(temporary, target)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise

    try:
        _restrict_windows_acl(target)
    except OSError:
        # The file is already written; a permissions-only step must not report
        # a saved password as a failure.
        pass


def _restrict_windows_acl(path: Path) -> None:
    """Remove inherited ACEs and grant the current user full control.

    Best effort by design: the password is already on disk, so a missing or
    failing ``icacls`` is ignored rather than reported (which could tempt a
    caller to print context).
    """
    if os.name != "nt":
        return

    user = os.environ.get("USERNAME") or os.environ.get("USER")
    if not user:
        return

    try:
        subprocess.run(
            ["icacls", str(path), "/inheritance:r", "/grant:r", f"{user}:F"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=_ACL_TIMEOUT_SECONDS,
            check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        pass
