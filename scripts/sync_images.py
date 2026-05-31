import argparse
import os
import subprocess
import sys

from yasuki_core.paths import SETS_DIR


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mirror the local set-image tree to the Cloudflare R2 bucket via rclone. "
        "Object keys mirror the local layout (sets/<slug>/<file>), matching the path stored in "
        "print_images and prefixed by IMAGE_BASE_URL at read time.",
    )
    parser.add_argument(
        "--bucket",
        default=os.environ.get("R2_BUCKET"),
        help="R2 bucket name (or set R2_BUCKET).",
    )
    parser.add_argument(
        "--remote",
        default=os.environ.get("R2_REMOTE"),
        help="rclone remote name (or set R2_REMOTE).",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Upload for real. Without this flag the run is a dry run.",
    )
    parser.add_argument("--transfers", type=int, default=16, help="Parallel transfers. Default 16.")
    args = parser.parse_args()

    if not args.bucket:
        parser.error("no bucket given (pass --bucket or set R2_BUCKET)")
    if not args.remote:
        parser.error("no rclone remote given (pass --remote or set R2_REMOTE)")
    if not SETS_DIR.exists():
        parser.error(f"set image directory not found: {SETS_DIR}")

    # sync mirrors the bucket to the local tree (stale remote objects are removed). Dry run first.
    cmd = [
        "rclone",
        "sync",
        str(SETS_DIR),
        f"{args.remote}:{args.bucket}/sets",
        "--checksum",
        f"--transfers={args.transfers}",
        "--fast-list",
        "--progress",
    ]
    if not args.execute:
        cmd.append("--dry-run")
        print("DRY RUN — pass --execute to upload. Command:")
    print(" ".join(cmd))
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
