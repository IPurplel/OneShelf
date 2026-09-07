"""Desktop startup must preserve settings and recover from interrupted setup."""

import importlib.util
import os
from pathlib import Path
import subprocess

import pytest
import yaml


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    spec = importlib.util.find_spec('run')
    assert spec is not None, 'The desktop launcher is missing'
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path / 'OneShelf with spaces'
    root.mkdir()
    (root / 'requirements.txt').write_text('example-package==1.0\n')
    for key in list(os.environ):
        if key.startswith('MD_'):
            monkeypatch.delenv(key)
    return module, root


def fake_commands(module, monkeypatch, root, *, fail_module=None):
    calls = []

    def run(command, *, cwd, check=False, **kwargs):
        assert Path(cwd) == root
        calls.append(command)
        if command[1:3] == ['-m', 'venv']:
            directory = Path(command[3])
            executable = directory / ('Scripts/python.exe' if module.sys.platform == 'win32' else 'bin/python')
            executable.parent.mkdir(parents=True)
            executable.touch()
        if command[1:3] == ['-m', fail_module]:
            raise subprocess.CalledProcessError(1, command)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(module.subprocess, 'run', run)
    return calls


@pytest.mark.parametrize('platform,python_path', [
    ('win32', 'Scripts/python.exe'), ('darwin', 'bin/python'), ('linux', 'bin/python'),
])
def test_first_run_sets_up_once_and_uses_the_local_interpreter(launcher, monkeypatch, platform, python_path):
    module, root = launcher
    monkeypatch.setattr(module.sys, 'platform', platform)
    monkeypatch.setattr(module.shutil, 'which', lambda name: None)
    calls = fake_commands(module, monkeypatch, root)
    executable = module.ensure_environment(root)
    assert executable == root / '.venv-oneshelf' / python_path
    assert [command[2] for command in calls] == ['venv', 'pip', 'playwright', 'patchright']
    assert all(command[0] == str(executable) for command in calls[1:])
    calls.clear()
    assert module.ensure_environment(root) == executable
    assert calls == [], 'Subsequent launches should not contact package/browser servers'


def test_changed_requirements_trigger_setup_again(launcher, monkeypatch):
    module, root = launcher
    calls = fake_commands(module, monkeypatch, root)
    module.ensure_environment(root)
    calls.clear()
    (root / 'requirements.txt').write_text('example-package==2.0\n')
    module.ensure_environment(root)
    assert [command[2] for command in calls] == ['pip', 'playwright', 'patchright']


def test_failed_browser_setup_is_retried_on_next_launch(launcher, monkeypatch):
    module, root = launcher
    fake_commands(module, monkeypatch, root, fail_module='patchright')
    with pytest.raises(subprocess.CalledProcessError):
        module.ensure_environment(root)
    calls = fake_commands(module, monkeypatch, root)
    module.ensure_environment(root)
    assert [command[2] for command in calls] == ['pip', 'playwright', 'patchright']


def test_linux_with_apt_installs_browser_system_dependencies(launcher, monkeypatch):
    module, root = launcher
    monkeypatch.setattr(module.sys, 'platform', 'linux')
    monkeypatch.setattr(module.shutil, 'which', lambda name: '/usr/bin/apt-get')
    calls = fake_commands(module, monkeypatch, root)
    module.ensure_environment(root)
    browser_install = next(command for command in calls if command[2] == 'playwright')
    assert '--with-deps' in browser_install


def test_fresh_config_uses_local_storage_and_survives_restart(launcher):
    module, root = launcher
    path = module.ensure_config(root)
    values = yaml.safe_load(path.read_text())
    assert values['host'] == '127.0.0.1'
    assert values['output_dir'] == str(root / 'downloads')
    assert values['config_dir'] == str(root / '.state')
    edited = 'output_dir: custom-library\nport: 9090\n'
    path.write_text(edited)
    assert module.ensure_config(root).read_text() == edited


def test_explicit_config_path_is_resolved_from_project_not_callers_directory(launcher, monkeypatch, tmp_path):
    module, root = launcher
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('MD_CONFIG_FILE', 'my settings/custom.yaml')
    config = root / 'my settings/custom.yaml'
    config.parent.mkdir()
    config.write_text('port: 8123\n')
    assert module.ensure_config(root) == config
    assert config.read_text() == 'port: 8123\n'
    assert not (root / 'config.yaml').exists()


def test_server_receives_existing_environment_and_propagates_failure(launcher, monkeypatch):
    module, root = launcher
    fake_commands(module, monkeypatch, root)
    python = module.ensure_environment(root)
    monkeypatch.setenv('MD_PORT', '9090')
    monkeypatch.setenv('MD_OUTPUT_DIR', 'my library')

    def server(command, *, cwd, env):
        assert command == [str(python), '-m', 'app.main']
        assert Path(cwd) == root
        assert env['MD_PORT'] == '9090'
        assert env['MD_OUTPUT_DIR'] == 'my library'
        assert env['MD_CONFIG_FILE'] == str(root / 'config.yaml')
        class Process:
            def wait(self):
                return 7
        return Process()

    monkeypatch.setattr(module.subprocess, 'Popen', server)
    assert module.main(root) == 7


def test_ctrl_c_allows_server_to_finish_saving_before_launcher_exits(launcher, monkeypatch):
    module, root = launcher
    fake_commands(module, monkeypatch, root)
    module.ensure_environment(root)

    class Process:
        waits = 0

        def wait(self, timeout=None):
            self.waits += 1
            if self.waits == 1:
                raise KeyboardInterrupt
            assert timeout >= 10
            return 0

    process = Process()
    monkeypatch.setattr(module.subprocess, 'Popen', lambda *args, **kwargs: process)
    assert module.main(root) == 0
    assert process.waits == 2
