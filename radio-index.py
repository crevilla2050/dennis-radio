#!/usr/bin/env python3

import os
import sqlite3
import sys
import time


DATABASE = "/var/lib/dennis-radio/radio.db"
MUSIC_ROOT = "/mnt/forge-storagebox/backups"

SOURCES = (
    "Music",
    "Musica",
    "MusicaCons",
)

AUDIO_EXTENSIONS = {
    ".mp3",
    ".flac",
    ".ogg",
    ".m4a",
    ".aac",
    ".wav",
}


def scan_source(source):
    """
    Scan one music source.

    Filesystem paths are deliberately handled as bytes because the
    Storage Box contains filenames which cannot always be represented
    as valid UTF-8 Python strings.
    """

    root = os.path.join(
        os.fsencode(MUSIC_ROOT),
        os.fsencode(source),
    )

    for directory, _, files in os.walk(root):
        for filename_bytes in files:

            # Determine the extension using filesystem bytes.
            extension = os.path.splitext(filename_bytes)[1].lower()

            if extension not in {
                ext.encode("ascii")
                for ext in AUDIO_EXTENSIONS
            }:
                continue

            absolute_path = os.path.join(
                directory,
                filename_bytes,
            )

            try:
                stat = os.stat(absolute_path)
            except OSError as exc:
                print(
                    "WARNING: cannot stat filesystem entry:",
                    repr(absolute_path),
                    file=sys.stderr,
                )
                print(
                    f"         {exc}",
                    file=sys.stderr,
                )
                continue

            relative_path_bytes = os.path.relpath(
                absolute_path,
                os.fsencode(MUSIC_ROOT),
            )

            yield (
                relative_path_bytes,
                os.fsencode(source),
                filename_bytes,
                stat.st_size,
                int(stat.st_mtime),
            )


def main():
    started = time.monotonic()

    print("Dennis Forge Radio Index")
    print("========================")

    connection = sqlite3.connect(DATABASE)

    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")

    added = 0
    updated = 0
    unchanged = 0
    scan_errors = 0

    for source in SOURCES:
        print(f"Scanning {source}...")

        source_count = 0

        for (
            path,
            source_name,
            filename,
            size_bytes,
            mtime,
        ) in scan_source(source):

            source_count += 1

            row = connection.execute(
                """
                SELECT size_bytes, mtime
                FROM songs
                WHERE path = ?
                """,
                (path,),
            ).fetchone()

            if row is None:

                connection.execute(
                    """
                    INSERT INTO songs
                        (
                            path,
                            source,
                            filename,
                            size_bytes,
                            mtime,
                            enabled
                        )
                    VALUES
                        (?, ?, ?, ?, ?, 1)
                    """,
                    (
                        path,
                        source_name,
                        filename,
                        size_bytes,
                        mtime,
                    ),
                )

                added += 1

            elif (
                row[0] != size_bytes
                or row[1] != mtime
            ):

                connection.execute(
                    """
                    UPDATE songs
                    SET
                        source = ?,
                        filename = ?,
                        size_bytes = ?,
                        mtime = ?,
                        enabled = 1
                    WHERE path = ?
                    """,
                    (
                        source_name,
                        filename,
                        size_bytes,
                        mtime,
                        path,
                    ),
                )

                updated += 1

            else:
                unchanged += 1

        print(f"  {source_count:,} audio files")

    connection.commit()

    total = connection.execute(
        """
        SELECT COUNT(*)
        FROM songs
        WHERE enabled = 1
        """
    ).fetchone()[0]

    connection.close()

    elapsed = time.monotonic() - started

    print()
    print("------------------------")
    print(f"Added:       {added:,}")
    print(f"Updated:     {updated:,}")
    print(f"Unchanged:   {unchanged:,}")
    print(f"Total songs: {total:,}")
    print(f"Elapsed:     {elapsed:.2f}s")
    print("------------------------")
    print()
    print("Index policy: NON-DESTRUCTIVE")
    print("Missing filesystem files are retained in the database.")


if __name__ == "__main__":
    main()