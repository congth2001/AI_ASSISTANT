"""Delete stale guest accounts and expired/revoked refresh tokens.

Dry-run is the default: nothing is deleted unless ``--apply`` is passed.

    .\env\Scripts\python.exe cleanup_auth_data.py --guest-days 30
    .\env\Scripts\python.exe cleanup_auth_data.py --guest-days 30 --apply
"""
import argparse
import asyncio

from config.config_manager import get_settings
from config.container import container


def positive_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be >= 0")
    return number


async def main() -> None:
    parser = argparse.ArgumentParser(description="Purge stale guest users and refresh tokens")
    parser.add_argument(
        "--guest-days", type=positive_int, default=30,
        help="delete guests (without conversations) created more than N days ago (default: 30)",
    )
    parser.add_argument(
        "--revoked-days", type=positive_int, default=7,
        help="also delete refresh tokens revoked more than N days ago (default: 7)",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="only report counts (default)")
    mode.add_argument("--apply", action="store_true", help="actually delete the rows")
    args = parser.parse_args()
    dry_run = not args.apply

    settings = get_settings()
    container.config.from_dict(settings.to_container_config())
    try:
        result = await container.auth_use_case().purge_expired_auth_data(
            args.guest_days, revoked_older_than_days=args.revoked_days, dry_run=dry_run,
        )
        verb = "Would delete" if dry_run else "Deleted"
        print(f"{verb} {result['guest_users']} guest user(s) and {result['refresh_tokens']} refresh token(s)")
        if dry_run:
            print("Dry run only. Re-run with --apply to delete.")
    finally:
        await container.postgres_client().close()


if __name__ == "__main__":
    asyncio.run(main())
