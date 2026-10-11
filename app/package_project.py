"""Create a reproducible source archive without local credentials or records."""
from pathlib import Path
import hashlib
import json
import zipfile
import argparse

ROOT = Path(__file__).resolve().parent
ALLOW_FILES = {'server.py', 'start.ps1', 'start.command', '.env.example', '.gitignore',
               'opencode.json', 'package_project.py', 'README.txt'}
ALLOW_DIRS = {'public', 'tests', 'manual', 'evidence'}
BLOCK_DIRS = {'__pycache__', '.data', '.git', 'node_modules'}


def selected_files():
    for path in sorted(ROOT.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(ROOT)
        if any(part in BLOCK_DIRS or part.startswith('runtime-') for part in relative.parts):
            continue
        if path.name.startswith('.env') and path.name != '.env.example':
            continue
        if path.suffix in {'.sqlite', '.sqlite3', '.db', '.pyc', '.log'}:
            continue
        if relative.parts[0] in ALLOW_DIRS or str(relative) in ALLOW_FILES:
            yield path, relative.as_posix()


def package(destination):
    destination = Path(destination).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = {name: hashlib.sha256(path.read_bytes()).hexdigest()
                for path, name in selected_files()}
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path, name in selected_files():
            archive.write(path, 'AirAssist_V1/' + name)
        archive.writestr('AirAssist_V1/SOURCE_MANIFEST.json', json.dumps(manifest, indent=2))
    print(json.dumps({'archive': str(destination), 'files': len(manifest),
                      'sha256': hashlib.sha256(destination.read_bytes()).hexdigest()}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('destination')
    package(parser.parse_args().destination)
