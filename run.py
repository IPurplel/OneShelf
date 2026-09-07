#!/usr/bin/env python3
"""Set up and run OneShelf on a desktop, using only Python's standard library."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parent


def ensure_environment(root: Path) -> Path:
    """Install once; retry incomplete setup and refresh changed requirements."""
    directory = root / '.venv-oneshelf'
    python = directory / ('Scripts/python.exe' if sys.platform == 'win32' else 'bin/python')
    requirements = root / 'requirements.txt'
    marker = directory / '.requirements.sha256'
    fingerprint = hashlib.sha256(requirements.read_bytes()).hexdigest()
    created = not python.is_file()
    if created:
        print('Creating the OneShelf Python environment...', flush=True)
        subprocess.run([sys.executable, '-m', 'venv', str(directory)], cwd=root, check=True)

    if created or not marker.is_file() or marker.read_text().strip() != fingerprint:
        # Never treat a partially completed install as ready on the next run.
        marker.unlink(missing_ok=True)
        print('Setting up packages and Chromium. The first run can take a few minutes.', flush=True)
        subprocess.run([str(python), '-m', 'pip', 'install', '-r', str(requirements)], cwd=root, check=True)
        browser_args = ['install', 'chromium']
        if sys.platform.startswith('linux') and shutil.which('apt-get'):
            print('Installing browser system libraries; sudo may ask for your password.', flush=True)
            browser_args.insert(1, '--with-deps')
        elif sys.platform.startswith('linux'):
            print('On this Linux distribution, Chromium system libraries must already be installed.', flush=True)
        subprocess.run([str(python), '-m', 'playwright', *browser_args], cwd=root, check=True)
        subprocess.run([str(python), '-m', 'patchright', 'install', 'chromium'], cwd=root, check=True)
        marker.write_text(fingerprint + '\n', encoding='utf-8')
    return python


def ensure_config(root: Path) -> Path:
    """Write desktop defaults only when the selected config does not exist."""
    path = Path(os.environ.get('MD_CONFIG_FILE', str(root / 'config.yaml')))
    if not path.is_absolute():
        path = root / path
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    defaults = {
        'host': '127.0.0.1',
        'port': 8080,
        'output_dir': str(root / 'downloads'),
        'config_dir': str(root / '.state'),
        'headless': False,
    }
    try:
        with path.open('x', encoding='utf-8') as config:
            config.write('# OneShelf desktop settings. Editable here or in the app.\n')
            for key, value in defaults.items():
                # JSON scalars are valid YAML, including Windows paths with backslashes.
                config.write(f'{key}: {json.dumps(value, ensure_ascii=False)}\n')
    except FileExistsError:
        pass  # Another launch created it; keep those settings.
    return path


def main(root: Path = ROOT) -> int:
    if sys.version_info < (3, 11):
        print('OneShelf requires Python 3.11 or newer. Use Python 3.12 for the documented setup.', file=sys.stderr)
        return 1
    try:
        python = ensure_environment(root)
        config = ensure_config(root)
        environment = os.environ.copy()
        environment['MD_CONFIG_FILE'] = str(config)
        print('\nStarting OneShelf. Open the address shown below in your browser.', flush=True)
        print('Keep this terminal open. Press Ctrl+C to stop.\n', flush=True)
        process = subprocess.Popen([str(python), '-m', 'app.main'], cwd=root, env=environment)
        try:
            return process.wait()
        except KeyboardInterrupt:
            # Ctrl+C reaches both processes in the terminal. Let the server
            # save its queue and close the browser instead of killing it.
            print('\nWaiting for OneShelf to finish shutting down...', flush=True)
            try:
                return process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    return process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    return process.wait()
    except KeyboardInterrupt:
        print('\nOneShelf stopped.')
        return 130
    except (OSError, subprocess.CalledProcessError) as error:
        print(f'\nOneShelf could not start: {error}', file=sys.stderr)
        print('Fix the error shown above, then run the same command again. Your existing settings and downloads are kept.', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
