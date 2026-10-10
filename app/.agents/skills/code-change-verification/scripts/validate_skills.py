import argparse
import re
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit


def validate_file(path: Path, names: set[str]) -> list[str]:
    errors: list[str] = []
    try:
        content = path.read_text(encoding='utf-8')
    except (OSError, UnicodeError) as error:
        return [f'{path}: cannot read UTF-8 file: {error}']

    lines = content.splitlines()
    if not lines or lines[0] != '---':
        return [f'{path}: missing frontmatter']
    try:
        boundary = lines.index('---', 1)
    except ValueError:
        return [f'{path}: unclosed frontmatter']

    metadata: dict[str, str] = {}
    for line in lines[1:boundary]:
        match = re.fullmatch(r'(name|description): (\S.*)', line)
        if match is None:
            errors.append(f'{path}: expected plain name/description fields')
            continue
        field, value = match.groups()
        if field in metadata:
            errors.append(f'{path}: duplicate field {field}')
        if value.startswith(('"', "'", '|', '>', '[', '{')) or ': ' in value:
            errors.append(f'{path}: unsupported scalar syntax in {field}')
        metadata[field] = value

    name = metadata.get('name', '')
    if (
        not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name)
        or len(name) > 64
        or name != path.parent.name
    ):
        errors.append(f'{path}: invalid name or folder mismatch')
    if name in names:
        errors.append(f'{path}: duplicate skill name {name}')
    names.add(name)

    description = metadata.get('description', '')
    if not description or len(description) > 1024 or re.search(r'[<>]', description):
        errors.append(f'{path}: invalid description')
    if not any(line.strip() for line in lines[boundary + 1:]):
        errors.append(f'{path}: missing instructions')
    if re.search(r'\[TODO:', content):
        errors.append(f'{path}: unfinished TODO placeholder')

    for number, line in enumerate(lines, 1):
        if line != line.rstrip():
            errors.append(f'{path}:{number}: trailing whitespace')

    for reference in re.findall(r'\]\(([^)]+)\)', content):
        parsed = urlsplit(reference)
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        target = path.parent / unquote(parsed.path)
        if not target.exists():
            errors.append(f'{path}: missing reference {reference}')
    return errors


def validate_root(root: Path) -> tuple[int, list[str]]:
    if not root.is_dir():
        return 0, [f'{root}: skill root is not a directory']
    skills = sorted(root.rglob('SKILL.md'))
    if not skills:
        return 0, [f'{root}: no skills found']
    names: set[str] = set()
    errors = [error for path in skills for error in validate_file(path, names)]
    return len(skills), errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Read-only skill structure checks; not a full YAML validator.'
    )
    parser.add_argument(
        '--root', type=Path, default=Path(__file__).resolve().parents[2]
    )
    arguments = parser.parse_args()
    count, errors = validate_root(arguments.root)
    if errors:
        for error in errors:
            print(error, file=sys.stderr)
        return 1
    print(f'PASS: {count} skills; metadata, references and whitespace checked.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
