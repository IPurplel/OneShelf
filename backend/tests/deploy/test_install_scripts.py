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

# Handoff regressions: external runtimes are stubbed, filesystem and Git operations are real.
def healthy_probe(bin_dir):
    stub(bin_dir, "curl", '''case "${@: -1}" in
      */api/ready) echo '{"ready":true,"schema_version":12,"migrations_pending":0}' ;;
      */api/health) echo '{"status":"ok"}' ;;
      *) exit 7 ;;
    esac''')


def test_install_success_repeats_and_checks_health(checkout, bin_dir):
    working_runtime(bin_dir, "podman")
    healthy_probe(bin_dir)
    for _ in range(2):
        result = run("install.sh", checkout, bin_dir)
        assert result.returncode == 0, result.stdout + result.stderr
        assert "health check passed" in result.stdout
        assert "http://127.0.0.1:8420" in result.stdout


def test_http_200_with_unhealthy_payload_is_failure(checkout, bin_dir):
    working_runtime(bin_dir, "podman")
    stub(bin_dir, "curl", '''case "${@: -1}" in
      */api/ready) echo '{"ready":true}' ;;
      *) echo '{"status":"error"}' ;;
    esac''')
    result = run("install.sh", checkout, bin_dir)
    assert result.returncode != 0
    assert "is running at" not in result.stdout


def test_missing_probe_tools_cannot_report_success(checkout, bin_dir):
    working_runtime(bin_dir, "podman")
    (bin_dir / "curl").unlink()
    # A genuinely restricted PATH without curl/wget; do not depend on host installed tools.
    for name in ("bash", "dirname", "head", "cp", "chmod", "grep", "tail", "tr", "mkdir", "basename", "realpath", "cat", "sed", "sleep"):
        (bin_dir / name).symlink_to(shutil.which(name))
    result = run("install.sh", checkout, bin_dir, env={"PATH": str(bin_dir)})
    assert result.returncode != 0
    assert "curl" in result.stderr and "wget" in result.stderr
    assert "is running at" not in result.stdout


def test_compose_receives_explicit_env_file_and_same_port_as_probe(checkout, bin_dir):
    working_runtime(bin_dir, "podman", log=checkout / "runtime.log")
    healthy_probe(bin_dir)
    (checkout / ".env").write_text('ONESHELF_PORT="9999" # chosen port\n')
    result = run("install.sh", checkout, bin_dir)
    assert result.returncode == 0, result.stderr
    assert "http://127.0.0.1:9999" in result.stdout
    assert f"--env-file {checkout}/.env" in (checkout / "runtime.log").read_text()


def test_exported_configuration_overrides_env_consistently(checkout, bin_dir):
    working_runtime(bin_dir, "podman")
    healthy_probe(bin_dir)
    result = run("install.sh", checkout, bin_dir, env={"ONESHELF_PORT": "9998"})
    assert result.returncode == 0, result.stderr
    assert "http://127.0.0.1:9998" in result.stdout


def test_directory_creation_failure_stops_before_build(checkout, bin_dir):
    log = checkout / "runtime.log"
    working_runtime(bin_dir, "podman", log=log)
    healthy_probe(bin_dir)
    (checkout / "deploy" / "volumes").write_text("not a directory")
    result = run("install.sh", checkout, bin_dir)
    assert result.returncode != 0
    assert " build" not in log.read_text()


@pytest.mark.parametrize("path", ["/", "..", "../..", "/home", "/var", ""])
def test_unsafe_mount_paths_stop_before_container_commands(checkout, bin_dir, path):
    log = checkout / "runtime.log"
    working_runtime(bin_dir, "podman", log=log)
    healthy_probe(bin_dir)
    (checkout / ".env").write_text(f"ONESHELF_DATA_PATH={path}\n")
    result = run("install.sh", checkout, bin_dir)
    assert result.returncode != 0
    assert " build" not in log.read_text()


def test_default_uninstall_does_not_create_missing_directories(checkout, bin_dir):
    working_runtime(bin_dir, "podman")
    shutil.copy(checkout / ".env.example", checkout / ".env")
    result = run("uninstall.sh", checkout, bin_dir)
    assert result.returncode == 0
    assert not (checkout / "deploy" / "volumes").exists()


def test_destructive_uninstall_refuses_custom_directory_even_with_confirmation(checkout, bin_dir):
    working_runtime(bin_dir, "podman")
    outside = checkout.parent / "shared-files"
    outside.mkdir()
    keep = outside / "keep"
    keep.write_text("unrelated")
    (checkout / ".env").write_text(f"ONESHELF_CONTENT_PATH={outside}\n")
    result = subprocess.run([str(checkout / "uninstall.sh"), "--delete-data"],
                            input="delete my library\n", capture_output=True, text=True,
                            env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(checkout.parent)})
    assert result.returncode != 0
    assert keep.read_text() == "unrelated"


def test_destructive_uninstall_rejects_symlinked_volume_parent(checkout, bin_dir):
    working_runtime(bin_dir, "podman")
    outside = checkout.parent / "shared-files"
    (outside / "data").mkdir(parents=True)
    keep = outside / "data" / "keep"
    keep.write_text("unrelated")
    (checkout / "deploy" / "volumes").symlink_to(outside, target_is_directory=True)
    shutil.copy(checkout / ".env.example", checkout / ".env")
    result = subprocess.run([str(checkout / "uninstall.sh"), "--delete-data"],
                            input="delete my library\n", capture_output=True, text=True,
                            env={"PATH": f"{bin_dir}:/usr/bin:/bin", "HOME": str(checkout.parent)})
    assert result.returncode != 0
    assert keep.read_text() == "unrelated"


def init_repo(checkout):
    subprocess.run(["git", "init", "-qb", "main"], cwd=checkout, check=True)
    (checkout / ".gitignore").write_text(".env\ndeploy/volumes/\nruntime.log\n")
    subprocess.run(["git", "add", "."], cwd=checkout, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base"],
                   cwd=checkout, check=True)


@pytest.mark.parametrize("state", ["detached", "wrong-branch", "merge"])
def test_update_refuses_unsafe_git_states(checkout, bin_dir, state):
    init_repo(checkout)
    if state == "detached":
        subprocess.run(["git", "checkout", "--detach", "-q"], cwd=checkout, check=True)
    elif state == "wrong-branch":
        subprocess.run(["git", "checkout", "-qb", "experiment"], cwd=checkout, check=True)
    else:
        (checkout / ".git" / "MERGE_HEAD").write_text(subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout, text=True))
    working_runtime(bin_dir, "podman", log=checkout / "runtime.log")
    healthy_probe(bin_dir)
    shutil.copy(checkout / ".env.example", checkout / ".env")
    result = run("update.sh", checkout, bin_dir)
    assert result.returncode != 0
    assert " build" not in (checkout / "runtime.log").read_text()


@pytest.mark.parametrize("action", ["build", "up"])
def test_compose_action_failure_is_propagated(checkout, bin_dir, action):
    stub(bin_dir, "podman", f'''case "$*" in
      *" {action}"|*" {action} "*) exit 19 ;;
      *) exit 0 ;;
    esac''')
    healthy_probe(bin_dir)
    result = run("install.sh", checkout, bin_dir)
    assert result.returncode != 0
    assert "is running at" not in result.stdout


def test_custom_plugin_and_backup_paths_match_compose(checkout, bin_dir):
    working_runtime(bin_dir, "podman")
    healthy_probe(bin_dir)
    plugins, backups = checkout.parent / "my plugins", checkout.parent / "my backups"
    (checkout / ".env").write_text(f'ONESHELF_PLUGIN_PATH="{plugins}"\nONESHELF_BACKUP_PATH="{backups}"\n')
    result = run("install.sh", checkout, bin_dir)
    assert result.returncode == 0, result.stderr
    assert plugins.is_dir() and backups.is_dir()
    assert not (checkout / "deploy/volumes/plugins").exists()
    assert not (checkout / "deploy/volumes/backups").exists()


def test_ownership_failure_prevents_start(checkout, bin_dir):
    log = checkout / "runtime.log"
    stub(bin_dir, "podman", f'''echo "$*" >> "{log}"
    case "$1" in run) exit 23 ;; *) exit 0 ;; esac''')
    healthy_probe(bin_dir)
    result = run("install.sh", checkout, bin_dir)
    assert result.returncode != 0
    assert " up -d" not in log.read_text()


@pytest.mark.parametrize("state", ["ahead", "diverged", "fast-forward", "unchanged", "worktree-dirty"])
def test_update_with_real_git_remote_preserves_data(checkout, bin_dir, state):
    init_repo(checkout)
    origin = checkout.parent / "origin.git"
    subprocess.run(["git", "clone", "--bare", str(checkout), str(origin)], check=True, capture_output=True)
    subprocess.run(["git", "remote", "add", "origin", str(origin)], cwd=checkout, check=True)
    subprocess.run(["git", "fetch", "origin"], cwd=checkout, check=True, capture_output=True)
    subprocess.run(["git", "branch", "--set-upstream-to=origin/main"], cwd=checkout, check=True, capture_output=True)
    if state in ("ahead", "diverged"):
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "--allow-empty", "-qm", "local"], cwd=checkout, check=True)
    if state in ("fast-forward", "diverged"):
        other = checkout.parent / "publisher"
        subprocess.run(["git", "clone", str(origin), str(other)], check=True, capture_output=True)
        (other / "release-note").write_text("new release")
        subprocess.run(["git", "add", "."], cwd=other, check=True)
        subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "remote"], cwd=other, check=True)
        subprocess.run(["git", "push"], cwd=other, check=True, capture_output=True)
    if state == "worktree-dirty":
        linked = checkout.parent / "linked"
        subprocess.run(["git", "worktree", "add", "--detach", str(linked)], cwd=checkout, check=True, capture_output=True)
        checkout = linked
        (checkout / "install.sh").write_text("changed")
    working_runtime(bin_dir, "podman", log=checkout / "runtime.log")
    healthy_probe(bin_dir)
    shutil.copy(checkout / ".env.example", checkout / ".env")
    before = (checkout / ".env").read_bytes()
    data = checkout / "deploy/volumes/data"
    data.mkdir(parents=True)
    (data / "oneshelf.db").write_bytes(b"persistent library")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout)
    result = run("update.sh", checkout, bin_dir)
    if state in ("ahead", "diverged", "worktree-dirty"):
        assert result.returncode != 0, result.stdout
        assert " build" not in (checkout / "runtime.log").read_text()
        assert subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=checkout) == head
    else:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "health check passed" in result.stdout
        if state == "fast-forward":
            assert (checkout / "release-note").read_text() == "new release"
    assert (data / "oneshelf.db").read_bytes() == b"persistent library"
    assert (checkout / ".env").read_bytes() == before


def test_update_leaves_an_env_with_the_historical_registry_url_byte_for_byte(checkout, bin_dir):
    """The old default Registry URL is aliased in the application, never rewritten in the owner's .env."""
    working_runtime(bin_dir, "podman", log=checkout / "runtime.log")
    healthy_probe(bin_dir)
    env = checkout / ".env"
    env.write_text("ONESHELF_BIND=127.0.0.1\n"
                   "ONESHELF_REGISTRY_URL=https://raw.githubusercontent.com/IPurplel/OneShelf/main/registry/index.json\n",
                   encoding="utf-8")
    before = env.read_bytes()
    result = run("update.sh", checkout, bin_dir)
    assert result.returncode == 0, result.stdout + result.stderr
    assert env.read_bytes() == before


def test_legacy_nested_data_blocks_install_before_it_can_be_hidden(checkout, bin_dir):
    # A pre-release image stored plugins/backups beneath /data, ignoring separate mounts.
    # A helper detects existing content there; never mount an empty store over that content.
    log = checkout / "runtime.log"
    stub(bin_dir, "podman", f'''echo "$*" >> "{log}"
    case "$*" in *"/legacy"*) exit 24 ;; *) exit 0 ;; esac''')
    healthy_probe(bin_dir)
    result = run("install.sh", checkout, bin_dir)
    assert result.returncode != 0
    assert " up -d" not in log.read_text()
    assert "legacy" in result.stderr.lower()


def test_install_refuses_unmarked_nonempty_custom_storage_before_runtime_mounts(checkout, bin_dir):
    custom = checkout.parent / "personal-books"
    custom.mkdir()
    (custom / "keep.epub").write_text("personal")
    (checkout / ".env").write_text(f"ONESHELF_CONTENT_PATH={custom}\n")
    log = checkout / "runtime.log"
    working_runtime(bin_dir, "podman", log=log)
    healthy_probe(bin_dir)
    result = run("install.sh", checkout, bin_dir)
    assert result.returncode != 0
    assert " run " not in log.read_text()
    assert (custom / "keep.epub").read_text() == "personal"
