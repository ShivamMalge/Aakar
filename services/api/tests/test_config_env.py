"""D-060 — `.env` is read at startup, and the environment wins.

The trap this closes: `.env.example` opened with "copy to .env and fill" while nothing read
the file, so the documented way to configure this project did not work and an API key placed
exactly where the template said was invisible to the application.

Precedence is the part that has to be tested rather than assumed. Environment-over-file is
what makes loading a file safe to ship: a container that exports `AAKAR_MODEL` must keep its
value even if a stray `.env` is baked into the image. The reverse would let a file committed
by accident silently override a deployment, which is a worse failure than the one being
fixed.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from aakar import config
from aakar.config import Settings, load_env_file


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each test starts with the loader unarmed and the relevant variables unset.

    `load_env_file` is deliberately once-per-process, so without this the first test to run
    would decide the outcome of the rest — the module-level flag is the thing under test as
    much as the precedence rule is.
    """
    monkeypatch.setattr(config, "_loaded", False)
    for name in ("AAKAR_MODEL", "AAKAR_API_KEY", "AAKAR_PROVIDER_MODE"):
        monkeypatch.delenv(name, raising=False)


def test_a_value_set_only_in_dot_env_reaches_settings(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The ruling, as a test. Before D-060 this value went nowhere."""
    (tmp_path / ".env").write_text("AAKAR_API_KEY=from-the-file\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    assert Settings.from_env().api_key == "from-the-file"


def test_the_environment_wins_over_the_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A deployment that exports a value keeps it. This is the direction that makes reading
    a file at all safe, and it is the one that would be easy to get backwards."""
    (tmp_path / ".env").write_text("AAKAR_MODEL=from-the-file\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / ".env")
    monkeypatch.setenv("AAKAR_MODEL", "from-the-environment")
    load_env_file(force=True)
    assert os.environ["AAKAR_MODEL"] == "from-the-environment"


def test_a_missing_env_file_is_not_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The normal case in CI and in production. Raising here would make every container need
    a file it has no reason to carry."""
    monkeypatch.setattr(config, "ENV_FILE", tmp_path / "nothing-here")
    assert load_env_file() is False
    assert Settings.from_env().provider_mode == "replay"


def test_the_file_is_read_once_per_process(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Re-reading on every `from_env()` would let an edit take effect halfway through a
    running process, which is the "it worked a minute ago" failure a config layer must not
    produce. `force` exists so a test can reload deliberately."""
    env = tmp_path / ".env"
    env.write_text("AAKAR_MODEL=first\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_FILE", env)

    assert load_env_file() is True
    assert os.environ["AAKAR_MODEL"] == "first"

    env.write_text("AAKAR_MODEL=second\n", encoding="utf-8")
    assert load_env_file() is False, "a second call must not re-read"
    assert os.environ["AAKAR_MODEL"] == "first"

    # Even a forced reload does not override what is already set — precedence still holds,
    # and `first` is now in the environment.
    monkeypatch.delenv("AAKAR_MODEL")
    load_env_file(force=True)
    assert os.environ["AAKAR_MODEL"] == "second"


def test_the_example_file_documents_what_is_actually_read() -> None:
    """The failure being closed was a document that lied about the code. A test that the
    document says the right thing is the only thing keeping it from drifting back."""
    example = (config.REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "READ AT STARTUP" in example
    assert "Environment variables win" in example or "**Environment variables win**" in example
    # And the two certified values must match what the code ships, or the template becomes
    # the stale-floor trap again (D-050 shipped 0.35 in this file after the code moved).
    assert "AAKAR_RELEVANCE_FLOOR=0.75" in example
    assert "AAKAR_CACHE_THRESHOLD=0.92" in example
