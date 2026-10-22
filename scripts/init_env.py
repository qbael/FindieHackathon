"""Create local development secrets without overwriting existing configuration."""

from pathlib import Path
import os
import secrets


def initialize(root: Path) -> bool:
    target = root / ".env"
    content = (root / ".env.example").read_text(encoding="utf-8")
    content = content.replace("GENERATE_DATABASE_PASSWORD", secrets.token_hex(24))
    content = content.replace("GENERATE_AI_SERVICE_TOKEN", secrets.token_hex(32))
    try:
        with open(target, "x", encoding="utf-8", opener=lambda path, flags: os.open(path, flags, 0o600)) as file:
            file.write(content)
    except FileExistsError:
        return False
    return True


if __name__ == "__main__":
    created = initialize(Path(__file__).resolve().parents[1])
    print("Created .env with local secrets." if created else ".env already exists; kept unchanged.")
