import logging
import sys
from pathlib import Path

import psycopg
import yaml

logger = logging.getLogger(__name__)

# Generic card backs keyed by (deck, era); image_path resolves like any other served image.
CARD_BACKS = [
    ("Fate", "old", "sets/backs/fate_old.jpg"),
    ("Fate", "new", "sets/backs/fate_new.jpg"),
    ("Dynasty", "old", "sets/backs/dynasty_old.jpg"),
    ("Dynasty", "new", "sets/backs/dynasty_new.jpg"),
    ("Dynasty", "token", "sets/backs/dynasty_token.jpg"),
]


def load_print_images(images_dir: Path, dsn: str) -> None:
    """
    Populate ``print_images`` from the per-set image manifests.

    Each manifest (``<set_slug>.yaml``) maps a printing — identified by ``(card_id, printing_id)`` —
    to its image files, in front-then-back order. The stored ``path`` is ``sets/<set_slug>/<file>``,
    resolved at read time against the local set tree or the configured image base URL.

    Parameters
    ----------
    images_dir : path
        Directory of per-set image manifests.
    dsn : str
        PostgreSQL connection string.
    """
    manifests = sorted(images_dir.glob("*.yaml"))
    rows: list[tuple] = []
    missing = 0

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute("SELECT print_id, card_id, printing_id FROM prints")
        print_ids = {(card_id, pid): print_id for print_id, card_id, pid in cur.fetchall()}

        for manifest in manifests:
            data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
            set_slug = manifest.stem
            for image in data.get("images", []):
                print_id = print_ids.get((image["card_id"], image["printing_id"]))
                if print_id is None:
                    missing += 1
                    logger.warning(
                        "No print for (%s, %s) in %s",
                        image["card_id"],
                        image["printing_id"],
                        manifest.name,
                    )
                    continue
                for image_index, file_info in enumerate(image["files"]):
                    rows.append(
                        (
                            print_id,
                            image_index,
                            file_info["role"],
                            "master",
                            file_info["sha256"],
                            f"sets/{set_slug}/{file_info['file']}",
                        )
                    )

        cur.executemany(
            """
            INSERT INTO print_images (print_id, image_index, role, size, sha256, path)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (print_id, image_index, size) DO NOTHING
            """,
            rows,
        )
        conn.commit()

    logger.info(
        "Loaded %d print images from %d manifests (%d unmatched)",
        len(rows),
        len(manifests),
        missing,
    )


def apply_errata_art(dsn: str) -> None:
    """Point each errata'd printing's front image at its current errata render (matched by set slug),
    so every art surface resolves the latest version. Preserve the pre-errata front on the card's
    revision 0 for the compare view.
    """
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            """
            SELECT p.print_id, p.card_id, front.path, cr.image_path
            FROM prints p
            JOIN l5r_sets s ON s.set_id = p.set_id
            JOIN print_images front
                ON front.print_id = p.print_id AND front.role = 'front' AND front.size = 'master'
            JOIN LATERAL (
                SELECT image_path FROM card_revisions
                WHERE card_id = p.card_id AND split_part(image_path, '/', 2) = s.set_slug
                ORDER BY revision_index DESC
                LIMIT 1
            ) cr ON TRUE
            """
        )
        printings = cur.fetchall()
        for print_id, card_id, original_path, errata_path in printings:
            cur.execute(
                "UPDATE card_revisions SET image_path = %s "
                "WHERE card_id = %s AND revision_index = 0 AND image_path IS NULL",
                (original_path, card_id),
            )
            cur.execute(
                "UPDATE print_images SET path = %s "
                "WHERE print_id = %s AND role = 'front' AND size = 'master'",
                (errata_path, print_id),
            )
        conn.commit()
    logger.info("Applied errata art to %d printing(s)", len(printings))


def seed_card_backs(dsn: str) -> None:
    """Seed the five generic card backs (Fate/Dynasty × old/new, plus the Dynasty token back)."""
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO card_backs (deck, era, image_path) VALUES (%s, %s, %s)
            ON CONFLICT (deck, era) DO UPDATE SET image_path = EXCLUDED.image_path
            """,
            CARD_BACKS,
        )
        conn.commit()
    logger.info("Seeded %d card backs", len(CARD_BACKS))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    load_print_images(Path(sys.argv[1]), sys.argv[2])
    seed_card_backs(sys.argv[2])
