"""Create local development secrets without overwriting existing configuration."""

from pathlib import Path
import os
import re
import secrets
import tempfile


def initialize(root: Path) -> bool:
    target = root / ".env"
    content = (root / ".env.example").read_text(encoding="utf-8")
    content = content.replace("GENERATE_DATABASE_PASSWORD", secrets.token_hex(24))
    content = content.replace("GENERATE_APP_DATABASE_PASSWORD", secrets.token_hex(24))
    content = content.replace("GENERATE_SEARCH_DATABASE_PASSWORD", secrets.token_hex(24))
    content = content.replace("GENERATE_AI_SERVICE_TOKEN", secrets.token_hex(32))
    try:
        with open(target, "x", encoding="utf-8", opener=lambda path, flags: os.open(path, flags, 0o600)) as file:
            file.write(content)
    except FileExistsError:
        previous = target.read_text(encoding="utf-8")
        present = set(re.findall(r"^[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z_0-9]*)=", previous, re.MULTILINE))
        missing = [line for line in content.splitlines()
                   if (match := re.match(r"^([A-Za-z_][A-Za-z_0-9]*)=", line)) and match[1] not in present]
        old_connection = 'ConnectionStrings__Database="Host=127.0.0.1;Port=${POSTGRES_PORT};Database=${POSTGRES_DB};Username=${POSTGRES_USER};Password=${POSTGRES_PASSWORD};Timeout=5"'
        if old_connection in previous.splitlines():
            previous = previous.replace(old_connection, "# Runtime connection moved below the service credentials.")
            missing.append(next(line for line in content.splitlines() if line.startswith("ConnectionStrings__Database=")))
        if not missing:
            return False
        updated = previous.rstrip() + "\n\n# Added service credentials and Google login settings.\n" + "\n".join(missing) + "\n"
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=root, prefix=".env.", delete=False) as file:
                temporary = Path(file.name)
                file.write(updated)
            temporary.replace(target)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return True
    return True


if __name__ == "__main__":
    created = initialize(Path(__file__).resolve().parents[1])
    print("Initialized .env settings; existing secrets preserved." if created else ".env already exists; kept unchanged.")
