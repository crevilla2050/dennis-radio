#!/usr/bin/env python3

import os
import sqlite3

DATABASE = "/var/lib/dennis-radio/radio.db"
MUSIC_ROOT = "/mnt/forge-storagebox/backups"


def get_next_song():
    connection = sqlite3.connect(DATABASE)

    row = connection.execute("""
        SELECT id, path, filename
        FROM songs
        WHERE enabled = 1
        ORDER BY RANDOM()
        LIMIT 1
    """).fetchone()

    connection.close()

    if row is None:
        raise RuntimeError("No enabled songs in radio database")

    song_id, path, filename = row

    # Database paths are stored as BLOBs because some filenames
    # contain filesystem byte sequences that cannot safely be
    # represented as UTF-8 text.
    path_bytes = bytes(path)
    filename_bytes = bytes(filename)

    filesystem_path = os.path.join(
        os.fsencode(MUSIC_ROOT),
        path_bytes,
    )

    return song_id, filesystem_path, filename_bytes


def main():
    print("Dennis Forge Radio — Next Song")
    print("================================")

    song_id, path, filename = get_next_song()

    print(f"ID:       {song_id}")
    print(f"Source:   {os.fsdecode(path).split(os.sep)[5]}")
    print(f"Filename: {os.fsdecode(filename)}")
    print(f"Path:     {os.fsdecode(path)}")

    print()

    # Optional sanity check with ffprobe.
    import subprocess

    result = subprocess.run(
        [
            "/usr/bin/ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    if result.returncode == 0:
        duration = result.stdout.decode(
            errors="replace"
        ).strip()

        print(f"Duration: {duration} seconds")
    else:
        print("Duration: unavailable")


if __name__ == "__main__":
    main()
    