"""Create the initial administrator without exposing a public registration API."""
import argparse
import asyncio
from getpass import getpass

from config.config_manager import get_settings
from config.container import container


async def main() -> None:
    parser = argparse.ArgumentParser(description="Create an administrator account")
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()

    password = getpass("Password (8-72 characters): ")
    confirmation = getpass("Confirm password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    if not 8 <= len(password) <= 72:
        raise SystemExit("Password must contain 8-72 characters")

    settings = get_settings()
    container.config.from_dict(settings.model_dump())
    try:
        user = await container.auth_use_case().bootstrap_admin(args.email, args.name, password)
        print(f"Created admin {user['email']} ({user['id']})")
    finally:
        await container.postgres_client().close()


if __name__ == "__main__":
    asyncio.run(main())
