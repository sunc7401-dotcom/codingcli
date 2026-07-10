from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from suncli_py.refactor_agent.commands import RefactorAgentError, run_scan
from suncli_py.refactor_agent.project_detector import ProjectDetector


def _runner(command: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    del cwd
    if list(command) == ["git", "status", "--porcelain"]:
        return subprocess.CompletedProcess(command, 0, stdout=" M src/main/java/Demo.java\n", stderr="")
    if list(command) == ["mvn", "-v"]:
        return subprocess.CompletedProcess(command, 0, stdout="Apache Maven 3.9.9\nJava version: 21\n", stderr="")
    if list(command) == ["java", "-version"]:
        return subprocess.CompletedProcess(command, 0, stdout="", stderr='openjdk version "21.0.1"\n')
    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


def test_project_detector_builds_profile_for_maven_git_project(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "src" / "main" / "java").mkdir(parents=True)
    (tmp_path / "module-a" / "src" / "test" / "java").mkdir(parents=True)
    (tmp_path / "pom.xml").write_text(
        """
        <project xmlns="http://maven.apache.org/POM/4.0.0">
          <modules>
            <module>module-a</module>
          </modules>
        </project>
        """,
        encoding="utf-8",
    )

    profile = ProjectDetector(tmp_path, command_runner=_runner).detect()

    assert profile.is_git_repo is True
    assert profile.is_maven_project is True
    assert profile.has_main_java is True
    assert profile.has_test_java is True
    assert profile.is_git_clean is False
    assert profile.maven_version == "Apache Maven 3.9.9"
    assert profile.java_version == 'openjdk version "21.0.1"'
    assert len(profile.modules) == 1
    assert "Git 工作区不干净" in "\n".join(profile.warnings)


def test_scan_reports_non_maven_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)

    with pytest.raises(RefactorAgentError, match="不是 Maven 项目"):
        run_scan()


def test_scan_json_outputs_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "src" / "main" / "java").mkdir(parents=True)
    (tmp_path / "pom.xml").write_text("<project />", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    exit_code = run_scan(output_format="json", llm_assistant=_FakeTriageAssistant())

    assert exit_code == 0
    output = capsys.readouterr().out
    assert '"is_git_repo": true' in output
    assert '"is_maven_project": true' in output


class _FakeTriageAssistant:
    def triage_issues(self, root: Path, issues: list) -> list:
        del root
        return issues
