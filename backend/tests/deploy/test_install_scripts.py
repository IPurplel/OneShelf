"""The install, update and uninstall scripts (release requirement, 2026-09-21).

These run the real scripts against stub runtimes on a temporary PATH, in a temporary copy of the
repository. Nothing here needs Docker or Podman to be installed, and nothing here touches the
developer's own checkout — which is the same promise the scripts make to the person running them.
"""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPTS = ("install.sh", "update.sh", "uninstall.sh")


@pytest.fixture
def checkout(tmp_path):
    """A throwaway copy of just the parts the scripts read."""
    root = tmp_path / "OneShelf"
    (root / "deploy").mkdir(parents=True)
    for name in SCRIPTS:
        shutil.copy(REPO / name, root / name)
        os.chmod(root / name, 0o755)
    shutil.copy(REPO / "deploy" / "lib.sh", root / "deploy" / "lib.sh")
    shutil.copy(REPO / "deploy" / "compose.yaml", root / "deploy" / "compose.yaml")
    shutil.copy(REPO / ".env.example", root / ".env.example")
    return root


def stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text("#!/usr/bin/env bash\n" + body + "\n", encoding="utf-8")
    os.chmod(path, 0o755)


@pytest.fixture
def bin_dir(tmp_path):
    d = tmp_path / "bin"
    d.mkdir()
    # A log every stub appends to, so a test can see what was actually invoked.
    stub(d, "curl", 'exit 7')          # nothing is listening in these tests
    return d


def run(script, checkout, bin_dir, *args, env=None, tries="1"):
    environment = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(checkout.parent),
        "ONESHELF_READY_TRIES": tries,
        "ONESHELF_READY_DELAY": "0",
        "NO_COLOR": "1",
    }
    environment.update(env or {})
    return subprocess.run([str(checkout / script), *args], capture_output=True, text=True,
                          env=environment, cwd=str(checkout), timeout=120)


def working_runtime(bin_dir, name, *, compose=True, log=None):
    """A runtime that answers `info`, and optionally provides `<name> compose`."""
    logline = f'echo "{name} $*" >> "{log}"' if log else ":"
    stub(bin_dir, name, f'''
{logline}
case "$1" in
  info) exit 0 ;;
  --version) echo "{name} version 0.0-stub"; exit 0 ;;
  compose) shift; {"exit 0" if compose else "exit 1"} ;;
  run) exit 0 ;;
  *) exit 0 ;;
esac''')


# -- runtime detection -----------------------------------------------------------------------------

def test_docker_is_detected_when_it_is_the_one_that_works(checkout, bin_dir):
    working_runtime(bin_dir, "docker")
    result = run("install.sh", checkout, bin_dir)
    assert "using docker" in result.stdout, result.stdout + result.stderr


def test_podman_is_detected_and_is_preferred_where_both_answer(checkout, bin_dir):
    """Fedora with Podman is a first-class path, so it is not second in line to Docker."""
    working_runtime(bin_dir, "podman")
    working_runtime(bin_dir, "docker")
    result = run("install.sh", checkout, bin_dir)
    assert "using podman" in result.stdout, result.stdout + result.stderr


def test_with_no_runtime_at_all_it_says_so_and_fails(checkout, bin_dir):
    result = run("install.sh", checkout, bin_dir)
    assert result.returncode != 0
    assert "no container runtime found" in result.stderr
    assert "dnf install podman" in result.stderr        # tells you how to fix it
    assert "sudo" not in result.stdout                   # and never runs it itself


def test_a_runtime_that_is_installed_but_not_answering_is_reported_as_such(checkout, bin_dir):
    stub(bin_dir, "podman", 'case "$1" in info) exit 1 ;; *) exit 1 ;; esac')
    result = run("install.sh", checkout, bin_dir)
    assert result.returncode != 0
    assert "installed but not responding" in result.stderr
    assert "podman.socket" in result.stderr


def test_an_explicit_runtime_choice_is_honoured(checkout, bin_dir):
    working_runtime(bin_dir, "podman")
    working_runtime(bin_dir, "docker")
    result = run("install.sh", checkout, bin_dir, env={"ONESHELF_RUNTIME": "docker"})
    assert "using docker" in result.stdout


# -- compose provider ------------------------------------------------------------------------------

def test_the_compose_plugin_is_used_when_the_runtime_has_one(checkout, bin_dir):
    working_runtime(bin_dir, "podman", compose=True)
    result = run("install.sh", checkout, bin_dir)
    assert "using podman compose" in result.stdout


def test_a_standalone_compose_is_used_when_the_plugin_is_missing(checkout, bin_dir):
    working_runtime(bin_dir, "podman", compose=False)
    stub(bin_dir, "podman-compose", "exit 0")
    result = run("install.sh", checkout, bin_dir)
    assert "using podman-compose" in result.stdout


def test_a_runtime_without_any_compose_is_a_clear_failure(checkout, bin_dir):
    working_runtime(bin_dir, "podman", compose=False)
    result = run("install.sh", checkout, bin_dir)
    assert result.returncode != 0
    assert "no Compose provider" in result.stderr
    assert "podman-compose" in result.stderr


# -- configuration ---------------------------------------------------------------------------------

def test_a_first_run_creates_env_from_the_example(checkout, bin_dir):
    working_runtime(bin_dir, "podman")
    assert not (checkout / ".env").exists()
    run("install.sh", checkout, bin_dir)
    created = checkout / ".env"
    assert created.is_file()
    assert "ONESHELF_BIND=127.0.0.1" in created.read_text(encoding="utf-8")
    assert oct(created.stat().st_mode)[-3:] == "600"


def test_an_existing_env_is_never_overwritten(checkout, bin_dir):
    working_runtime(bin_dir, "podman")
    mine = checkout / ".env"
    mine.write_text("ONESHELF_PORT=9999\nONESHELF_BIND=127.0.0.1\n# my own notes\n", encoding="utf-8")
    before = mine.read_text(encoding="utf-8")
    result = run("install.sh", checkout, bin_dir)
    assert mine.read_text(encoding="utf-8") == before
    assert "existing .env" in result.stdout
    assert "9999" in result.stdout               # and it is honoured, not ignored


def test_running_install_again_changes_nothing_it_should_not(checkout, bin_dir):
    working_runtime(bin_dir, "podman")
    first = run("install.sh", checkout, bin_dir)
    env_after_first = (checkout / ".env").read_text(encoding="utf-8")
    dirs_after_first = sorted(p.name for p in (checkout / "deploy" / "volumes").iterdir())
    second = run("install.sh", checkout, bin_dir)
    assert first.returncode == second.returncode
    assert (checkout / ".env").read_text(encoding="utf-8") == env_after_first
    assert sorted(p.name for p in (checkout / "deploy" / "volumes").iterdir()) == dirs_after_first


def test_it_prepares_its_own_directories_and_no_others(checkout, bin_dir):
    working_runtime(bin_dir, "podman")
    run("install.sh", checkout, bin_dir)
    volumes = checkout / "deploy" / "volumes"
    assert sorted(p.name for p in volumes.iterdir()) == ["backups", "content", "data", "keys", "plugins"]


def test_no_secret_is_ever_printed(checkout, bin_dir):
    """OneShelf generates its own session key on its own volume; nothing secret belongs in this output."""
    working_runtime(bin_dir, "podman")
    result = run("install.sh", checkout, bin_dir)
    combined = result.stdout + result.stderr
    for word in ("BEGIN PRIVATE KEY", "session.key contents", "secret="):
        assert word not in combined


# -- failures propagate ------------------------------------------------------------------------------

def test_a_readiness_failure_fails_the_install(checkout, bin_dir):
    working_runtime(bin_dir, "podman")          # compose succeeds, but nothing ever answers
    result = run("install.sh", checkout, bin_dir)
    assert result.returncode != 0
    assert "did not become ready" in result.stderr
    assert "logs --tail" in result.stdout        # and says how to look


def test_a_failing_container_command_fails_the_install(checkout, bin_dir):
    stub(bin_dir, "podman", '''
case "$1" in
  info) exit 0 ;;
  --version) echo "podman stub"; exit 0 ;;
  compose) exit 9 ;;
  *) exit 0 ;;
esac''')
    stub(bin_dir, "podman-compose", "exit 9")
    result = run("install.sh", checkout, bin_dir)
    assert result.returncode != 0


# -- update ------------------------------------------------------------------------------------------

def test_update_refuses_to_run_before_an_install(checkout, bin_dir):
    working_runtime(bin_dir, "podman")
    result = run("update.sh", checkout, bin_dir)
    assert result.returncode != 0 and "run ./install.sh first" in result.stderr


def test_update_refuses_when_the_checkout_has_local_changes(checkout, bin_dir):
    working_runtime(bin_dir, "podman")
    (checkout / ".env").write_text("ONESHELF_PORT=8420\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
    subprocess.run(["git", "add", "-A"], cwd=checkout, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"],
                   cwd=checkout, check=True)
    (checkout / "install.sh").write_text("#!/usr/bin/env bash\necho changed\n", encoding="utf-8")
    result = run("update.sh", checkout, bin_dir)
    assert result.returncode != 0
    assert "local changes" in result.stderr
    assert "library and .env are untouched" in result.stderr


def test_update_keeps_going_without_git_and_says_so(checkout, bin_dir):
    working_runtime(bin_dir, "podman")
    (checkout / ".env").write_text("ONESHELF_PORT=8420\n", encoding="utf-8")
    result = run("update.sh", checkout, bin_dir)
    assert "not a git checkout" in result.stderr
    assert "did not become ready" in result.stderr        # it still verifies afterwards
    assert result.returncode != 0


# -- uninstall ------------------------------------------------------------------------------------------

def test_uninstall_keeps_every_byte_of_the_library_by_default(checkout, bin_dir):
    working_runtime(bin_dir, "podman")
    run("install.sh", checkout, bin_dir)
    data = checkout / "deploy" / "volumes" / "data"
    (data / "oneshelf.db").write_text("pretend library", encoding="utf-8")
    content = checkout / "deploy" / "volumes" / "content"
    (content / "a-book.epub").write_text("pretend book", encoding="utf-8")

    result = run("uninstall.sh", checkout, bin_dir)
    assert result.returncode == 0
    assert (data / "oneshelf.db").read_text(encoding="utf-8") == "pretend library"
    assert (content / "a-book.epub").read_text(encoding="utf-8") == "pretend book"
    assert "library has been kept" in result.stdout
    assert "--delete-data" in result.stdout


def test_uninstall_refuses_an_option_it_does_not_know(checkout, bin_dir):
    working_runtime(bin_dir, "podman")
    result = run("uninstall.sh", checkout, bin_dir, "--purge")
    assert result.returncode != 0 and "unknown option" in result.stderr


def test_deleting_data_requires_typing_the_whole_sentence(checkout, bin_dir):
    working_runtime(bin_dir, "podman")
    run("install.sh", checkout, bin_dir)
    data = checkout / "deploy" / "volumes" / "data"
    (data / "oneshelf.db").write_text("pretend library", encoding="utf-8")

    result = subprocess.run([str(checkout / "uninstall.sh"), "--delete-data"], input="yes\n",
                            capture_output=True, text=True, cwd=str(checkout), timeout=60,
                            env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(checkout.parent),
                                 "NO_COLOR": "1"})
    assert result.returncode != 0
    assert "Nothing was deleted" in result.stdout
    assert (data / "oneshelf.db").is_file()


def test_deleting_data_does_delete_it_when_that_is_genuinely_asked_for(checkout, bin_dir):
    working_runtime(bin_dir, "podman")
    run("install.sh", checkout, bin_dir)
    data = checkout / "deploy" / "volumes" / "data"
    (data / "oneshelf.db").write_text("pretend library", encoding="utf-8")
    outside = checkout / "not-oneshelf"
    outside.mkdir()
    (outside / "keep-me.txt").write_text("untouched", encoding="utf-8")

    result = subprocess.run([str(checkout / "uninstall.sh"), "--delete-data"],
                            input="delete my library\n", capture_output=True, text=True,
                            cwd=str(checkout), timeout=60,
                            env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(checkout.parent),
                                 "NO_COLOR": "1"})
    assert result.returncode == 0, result.stdout + result.stderr
    assert not data.exists()
    assert (outside / "keep-me.txt").read_text(encoding="utf-8") == "untouched"


# -- hygiene -------------------------------------------------------------------------------------------

def test_the_scripts_are_executable_in_git():
    for name in SCRIPTS:
        mode = subprocess.run(["git", "ls-files", "-s", name], cwd=REPO, capture_output=True,
                              text=True).stdout.split()
        assert mode and mode[0] == "100755", f"{name} is not executable in git: {mode}"


@pytest.mark.skipif(shutil.which("shellcheck") is None, reason="shellcheck is not installed here")
def test_shellcheck_is_happy():
    result = subprocess.run(["shellcheck", "-S", "warning", *SCRIPTS, "deploy/lib.sh"],
                            cwd=REPO, capture_output=True, text=True)
    assert result.returncode == 0, result.stdout
