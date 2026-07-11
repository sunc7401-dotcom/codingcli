from __future__ import annotations

from pathlib import Path

import pytest

from suncli_py.config.config import PaiCliConfig


def test_dotenv_lookup_walks_up_from_current_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    nested = tmp_path / "java-project" / "module"
    nested.mkdir(parents=True)
    (tmp_path / ".env").write_text("PAICLI_TEST_KEY=from-parent\n", encoding="utf-8")
    monkeypatch.chdir(nested)
    monkeypatch.delenv("PAICLI_ENV_FILE", raising=False)

    assert PaiCliConfig._read_from_dotenv("PAICLI_TEST_KEY") == "from-parent"


def test_explicit_dotenv_file_takes_priority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_env = tmp_path / ".env"
    explicit_env = tmp_path / "agent.env"
    project_env.write_text("PAICLI_TEST_KEY=from-project\n", encoding="utf-8")
    explicit_env.write_text("PAICLI_TEST_KEY=from-explicit\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PAICLI_ENV_FILE", str(explicit_env))

    assert PaiCliConfig._read_from_dotenv("PAICLI_TEST_KEY") == "from-explicit"
