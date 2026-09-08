"""Restore each unchanged line's original ending after a whole-file rewrite.

Two files in this repo are mixed CRLF/LF (a Windows history showing through),
and any tool that reads and rewrites them normalises the lot -- turning a
40-line edit into a 2,700-line diff. This re-emits every line that git still
recognises with its original bytes, and gives new lines the file's dominant
ending. Run it on anything `git diff --stat` reports as far larger than the
edit you actually made.
"""
import difflib
import pathlib
import subprocess
import sys


def repair(name: str) -> str:
    head = subprocess.run(["git", "show", f"HEAD:{name}"],
                          capture_output=True, check=True).stdout
    head_lines = head.splitlines(keepends=True)
    cur = pathlib.Path(name).read_bytes().splitlines(keepends=True)
    crlf = sum(1 for l in head_lines if l.endswith(b"\r\n")) > len(head_lines) / 2
    ending = b"\r\n" if crlf else b"\n"

    sm = difflib.SequenceMatcher(None, [l.rstrip(b"\r\n") for l in head_lines],
                                 [l.rstrip(b"\r\n") for l in cur], autojunk=False)
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out.extend(head_lines[i1:i2])
        elif tag in ("replace", "insert"):
            for line in cur[j1:j2]:
                body = line.rstrip(b"\r\n")
                out.append(body + ending if line != body else body)
    pathlib.Path(name).write_bytes(b"".join(out))
    return f"{name}: restored ({'CRLF' if crlf else 'LF'} dominant)"


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        print(repair(arg))
