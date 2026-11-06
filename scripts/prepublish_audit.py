#!/usr/bin/env python3
"""Basic staged-file hygiene audit; not a replacement for security or license review."""
from pathlib import Path
import re
import subprocess
root=Path(__file__).resolve().parents[1]
patterns=[
    re.compile(r'(^|/)\.env($|\.)'),
    re.compile(r'\.(sqlite3?|db)(-|$)'),
    re.compile(r'(^|/)__pycache__/'),
    re.compile(r'(^|/)out/'),
    re.compile(r'(^|/)\.venv/'),
]
try:
    tracked=subprocess.run(['git','ls-files'],cwd=root,text=True,capture_output=True,check=True).stdout.splitlines()
    paths=[root/p for p in tracked]
except (OSError,subprocess.CalledProcessError):
    paths=[p for p in root.rglob('*') if p.is_file() and '.git' not in p.parts]
errors=[]
for p in paths:
    rel=p.relative_to(root).as_posix()
    if not p.is_file(): errors.append(f'Missing tracked file: {rel}');continue
    if any(rx.search(rel) for rx in patterns) and rel!='.env.example':
        errors.append(f'Unexpected tracked data/artifact: {rel}')
    if p.suffix in ('.py','.js','.md','.html','.css','.yml','.yaml','.txt'):
        contents=p.read_text(errors='replace')
        if re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----',contents):
            errors.append(f'Private key marker: {rel}')
if errors:
    print('\n'.join(errors));raise SystemExit(1)
print(f'Hygiene check passed for {len(paths)} tracked files; full secret/license review still required.')
