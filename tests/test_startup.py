"""Exercise the real Bash entry point with Docker replaced at the CLI boundary."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def startup(tmp_path):
    project = tmp_path / 'OneShelf with spaces'
    project.mkdir()
    if (ROOT / 'startup.sh').exists():
        shutil.copy(ROOT / 'startup.sh', project / 'startup.sh')
    (project / 'deploy').mkdir()
    shutil.copy(ROOT / 'deploy/docker-compose.yml', project / 'deploy/docker-compose.yml')
    binaries = tmp_path / 'bin'
    binaries.mkdir()
    # Keep the host's Docker/network tools out of these offline tests.
    for name in ('dirname', 'awk', 'sort'):
        (binaries / name).symlink_to(shutil.which(name))
    fake = binaries / 'docker'
    fake.write_text(f'#!{Path(sys.executable).resolve()}\n' + r'''
import json, os, sys
from pathlib import Path
args = sys.argv[1:]
with open(os.environ['CALLS'], 'a') as log:
    log.write(json.dumps(args) + '\n')
mode = os.environ.get('SCENARIO', '')
if args == ['compose', 'version']:
    sys.exit(1 if mode == 'no_compose' else 0)
if args == ['info']:
    sys.exit(1 if mode == 'no_daemon' else 0)
if args[:2] == ['container', 'ls']:
    assert args[2:] == ['--all', '--filter', 'label=com.docker.compose.project=oneshelf', '--filter', 'label=com.docker.compose.service=oneshelf', '--format', '{{.ID}}'], args
    if mode == 'renamed_conflict':
        print('old-container-id')
    sys.exit(0)
if args[:2] == ['container', 'inspect']:
    if args[-1] == 'old-container-id':
        print('oneshelf|oneshelf|bind::/data/manga|bind::/config')
        sys.exit(0)
    if 'State.Health.Status' in args[-2]:
        print({'unhealthy': 'unhealthy', 'timeout': 'starting'}.get(mode, 'healthy'))
    elif mode == 'conflict':
        print('deploy|oneshelf|bind::/data/manga|bind::/config')
    elif mode == 'wrong_mounts':
        print('oneshelf|oneshelf|volume:other_downloads:/data/manga|volume:oneshelf_config:/config')
    elif Path(os.environ['STARTED']).exists():
        print('oneshelf|oneshelf|volume:oneshelf_downloads:/data/manga|volume:oneshelf_config:/config')
    else:
        sys.exit(1)
elif args[0] == 'compose':
    assert args[1:3] == ['--project-name', 'oneshelf'], args
    assert args[3] == '--file' and Path(args[4]).is_file(), args
    command = args[5:]
    if command == ['build']:
        if mode == 'build_fail':
            print('specific build failure', file=sys.stderr)
            sys.exit(1)
    elif command == ['up', '-d']:
        if mode == 'up_fail':
            print('port is already allocated', file=sys.stderr)
            sys.exit(1)
        Path(os.environ['STARTED']).touch()
    elif command == ['logs', '--tail', '60', 'oneshelf']:
        print('diagnostic container logs')
    elif command[:3] == ['exec', '-T', 'oneshelf']:
        if mode == 'storage_fail':
            print('Permission denied', file=sys.stderr)
            sys.exit(1)
    else:
        raise AssertionError(command)
else:
    raise AssertionError(args)
''')
    fake.chmod(0o755)
    hostname = binaries / 'hostname'
    hostname.write_text('#!/bin/sh\n[ "$SCENARIO" = "no_lan" ] && exit 1\nprintf "127.0.0.1 192.168.1.42 2001:db8::1 192.168.1.42\\n"\n')
    hostname.chmod(0o755)
    sleep = binaries / 'sleep'
    sleep.write_text('#!/bin/sh\nexit 0\n')
    sleep.chmod(0o755)
    environment = dict(os.environ, PATH=str(binaries), CALLS=str(tmp_path / 'calls'),
                       STARTED=str(tmp_path / 'started'), SCENARIO='')

    def run(scenario=''):
        environment['SCENARIO'] = scenario
        return subprocess.run(
            ['/bin/bash', str(project / 'startup.sh')], cwd=tmp_path,
            env=environment, text=True, capture_output=True, timeout=10,
        )

    def calls():
        path = tmp_path / 'calls'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    return run, calls, fake


def test_builds_from_other_directory_and_prints_lan_only_after_ready(startup):
    run, calls, _ = startup
    result = run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'http://localhost:8080' in result.stdout
    assert result.stdout.count('http://192.168.1.42:8080') == 1
    assert 'http://127.0.0.1:8080' not in result.stdout
    assert 'http://2001:db8::1' not in result.stdout
    commands = calls()
    assert next(i for i, c in enumerate(commands) if c[-1] == 'build') < next(
        i for i, c in enumerate(commands) if c[-2:] == ['up', '-d'])


def test_repeated_start_preserves_container_data(startup):
    run, calls, _ = startup
    for _ in range(2):
        result = run()
        assert result.returncode == 0, result.stdout + result.stderr
    assert not any(word in ('rm', 'down', 'prune') for c in calls() for word in c)


@pytest.mark.parametrize('scenario,message', [
    ('no_compose', 'Compose'), ('no_daemon', 'Docker'),
    ('build_fail', 'specific build failure'), ('up_fail', 'port is already allocated'),
    ('conflict', 'existing'), ('wrong_mounts', 'existing'),
    ('renamed_conflict', 'existing'),
    ('unhealthy', 'diagnostic container logs'), ('storage_fail', 'Permission denied'),
    ('timeout', '120 seconds'),
])
def test_failures_never_claim_success(startup, scenario, message):
    run, calls, _ = startup
    result = run(scenario)
    assert result.returncode != 0
    assert message in result.stdout + result.stderr
    assert 'http://localhost:8080' not in result.stdout
    if scenario in ('no_compose', 'no_daemon', 'conflict', 'wrong_mounts', 'renamed_conflict'):
        assert not any(c[-1] == 'build' for c in calls())


def test_missing_docker_has_actionable_error(startup):
    run, _, docker = startup
    docker.unlink()
    result = run()
    assert result.returncode != 0
    assert 'Docker' in result.stderr
    assert 'install' in result.stderr.lower()


def test_no_lan_detection_prints_instructions_not_localhost_as_lan(startup):
    run, _, _ = startup
    result = run('no_lan')
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'LAN IP' in result.stdout
    assert result.stdout.count('http://localhost:8080') == 1
