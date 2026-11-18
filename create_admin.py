"""Create the initial administrator without exposing a public registration API."""
import argparse
import asyncio
from getpass import getpass

from config.config_manager import get_settings
from config.container import container
from src.modules.auth.domain.ports.i_password_hasher import MAX_PASSWORD_BYTES, password_byte_length


async def main() -> None:
    parser = argparse.ArgumentParser(description="Create an administrator account")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()

    password = getpass(f"Password (8-{MAX_PASSWORD_BYTES} bytes, UTF-8): ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    # bcrypt ignores everything after 72 BYTES, so validate the encoded length.
    if not 8 <= password_byte_length(password) <= MAX_PASSWORD_BYTES:
        raise SystemExit(f"Password must contain 8-{MAX_PASSWORD_BYTES} bytes (UTF-8 encoded)")

    settings = get_settings()
    container.config.from_dict(settings.to_container_config())
    try:
        user = await container.auth_use_case().bootstrap_admin(args.email, args.name, password)
        print(f"Created admin {user['email']} ({user['id']})")
    finally:
        await container.postgres_client().close()


if __name__ == "__main__":
    asyncio.run(main())
