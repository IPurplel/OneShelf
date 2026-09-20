"""§49 EX-04 (and the architecture behind EX-03): plugins are declarations, not programs.

A plugin package is data that the runtime interprets. Nothing in the plugin path compiles, executes,
spawns or unpickles anything, and there is no restricted-RPC design hiding behind the declarative one —
because a sandbox with a call channel is still arbitrary code with extra steps.
"""
import re

from .conftest import BACKEND, code_lines

# `re.compile` is not code execution, so the call has to stand on its own to count.
EXECUTION = re.compile(r"(?<![.\w])(exec|eval|compile)\s*\(|\b__import__\s*\(|importlib\.import_module|"
                       r"subprocess|os\.system|os\.exec|os\.spawn|pty\.|runpy|marshal\.loads|pickle\.loads?|"
                       r"types\.FunctionType|CodeType")
RPC = re.compile(r"\b(xmlrpc|jsonrpc|grpc|pyro4|rpyc|multiprocessing|socketserver)\b|"
                 r"\bsocket\.socket\b")


def plugin_path():
    for directory in ("plugins", "generator"):
        yield from (BACKEND / "oneshelf" / directory).rglob("*.py")


def test_the_plugin_path_never_executes_what_it_loads():
    offenders = [f"{path.relative_to(BACKEND)}:{number}: {line.strip()}"
                 for path, number, line in code_lines(sorted(plugin_path())) if EXECUTION.search(line)]
    assert offenders == []


def test_there_is_no_rpc_channel_to_a_plugin():
    offenders = [f"{path.relative_to(BACKEND)}:{number}: {line.strip()}"
                 for path, number, line in code_lines(sorted(plugin_path())) if RPC.search(line)]
    assert offenders == []


def test_a_package_is_yaml_and_stays_yaml():
    """A package is read by a restricted loader: nothing in it can name a Python object to construct."""
    loader = (BACKEND / "oneshelf" / "plugins" / "yamlsafe.py").read_text(encoding="utf-8")
    assert "yaml.SafeLoader" in loader
    # `yaml.load` is allowed exactly once, with the restricted loader above named on the same line.
    unsafe = [f"{path.relative_to(BACKEND)}:{number}" for path, number, line in code_lines(sorted(plugin_path()))
              if re.search(r"yaml\.(load|unsafe_load|full_load)\s*\(|yaml\.Loader|UnsafeLoader|FullLoader", line)
              and "_RestrictedLoader" not in line]
    assert unsafe == []
