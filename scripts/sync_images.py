import argparse
import os
import subprocess
import sys

from yasuki_core.paths import BUNDLED_IMAGES_DIR, SETS_DIR


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Mirror the image trees to the Cloudflare R2 bucket via rclone. Object keys "
        "mirror the local layout and are prefixed by IMAGE_BASE_URL at read time: set art under "
        "sets/<slug>/<file>, plus the bundled overlays/ (holding flair, keyword mons) and defaults/ "
        "the deck builder loads directly.",
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

    # (local dir, remote prefix, extra rclone args). Each is a scoped mirror, so stale remote
    # objects under that prefix are removed but other prefixes are untouched. Skip the raw mon
    # sources (local-only working files) under overlays/.
    targets = [
        (SETS_DIR, "sets", []),
        (
            BUNDLED_IMAGES_DIR / "overlays",
            "overlays",
            ["--exclude", "mon_raw/**", "--exclude", "*_raw.png"],
        ),
        (BUNDLED_IMAGES_DIR / "defaults", "defaults", []),
    ]

    rc = 0
    for local, prefix, extra in targets:
        if not local.exists():
            print(f"skip {prefix}: {local} not found")
            continue
        # sync mirrors the bucket prefix to the local tree (stale remote objects removed).
        cmd = [
            "rclone",
            "sync",
            str(local),
            f"{args.remote}:{args.bucket}/{prefix}",
            "--checksum",
            f"--transfers={args.transfers}",
            "--fast-list",
            "--progress",
            *extra,
        ]
        if not args.execute:
            cmd.append("--dry-run")
        print(("DRY RUN — " if not args.execute else "") + " ".join(cmd))
        rc = subprocess.call(cmd) or rc
    if not args.execute:
        print("\nDry run only — pass --execute to upload.")
    return rc


if __name__ == "__main__":
    sys.exit(main())
