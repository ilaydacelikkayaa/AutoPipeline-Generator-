import re
from pathlib import Path

import yaml


def _port(value) -> int:
    text = str(value).strip()
    fallback = re.fullmatch(r'\$\{[^}:]+:(\d+)\}', text)
    if fallback:
        text = fallback.group(1)
    if not text.isdecimal() or not 1 <= int(text) <= 65535:
        raise ValueError('Container portu çözümlenemedi; container_port belirtin.')
    return int(text)


def resolve_spring_boot_port(repository_path: Path) -> int | None:
    resources = repository_path / 'src/main/resources'
    properties = resources / 'application.properties'
    if properties.is_file():
        for line in properties.read_text(encoding='utf-8').splitlines():
            match = re.match(r'^\s*server\.port\s*[=:]\s*(.*?)\s*$', line)
            if match:
                return _port(match.group(1))
    for name in ('application.yml', 'application.yaml'):
        file = resources / name
        if file.is_file():
            documents = list(yaml.safe_load_all(file.read_text(encoding='utf-8')))
            if len(documents) != 1:
                raise ValueError('Birden fazla Spring profili var; container_port belirtin.')
            document = documents[0] or {}
            server = document.get('server', {}) if isinstance(document, dict) else {}
            if isinstance(server, dict) and 'port' in server:
                return _port(server['port'])
    if properties.is_file() or any((resources / name).is_file() for name in ('application.yml', 'application.yaml')):
        return 8080
    return None


def resolve_container_port(repository_path: Path) -> int | None:
    dockerfile = repository_path / 'Dockerfile'
    if dockerfile.is_file():
        # Only the final image's EXPOSE instructions describe the deployed image.
        ports = set()
        for line in dockerfile.read_text(encoding='utf-8').splitlines():
            if re.match(r'^\s*FROM\s', line, re.IGNORECASE):
                ports.clear()
            match = re.match(r'^\s*EXPOSE\s+(.+)', line, re.IGNORECASE)
            if match:
                for value in match.group(1).split('#', 1)[0].split():
                    if value.lower().endswith('/udp'):
                        continue
                    ports.add(_port(value.removesuffix('/tcp')))
        return next(iter(ports)) if len(ports) == 1 else None
    return resolve_spring_boot_port(repository_path)
