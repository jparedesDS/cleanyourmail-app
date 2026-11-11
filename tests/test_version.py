import subprocess
import sys

from cleanyourmail_app.version import __version__


def test_version_is_0_5_0():
    assert __version__ == "0.5.0"


def test_module_version_flag():
    result = subprocess.run(
        [sys.executable, "-m", "cleanyourmail_app", "--version"],
        check=False, capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "0.5.0" in result.stdout
