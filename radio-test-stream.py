#!/usr/bin/env python3

import os
import sqlite3
import subprocess
import sys

DATABASE = "/var/lib/dennis-radio/radio.db"
MUSIC_ROOT = "/mnt/forge-storagebox/backups"
PORT = 8001


def get_song():
    connection = sqlite3.connect(DATABASE)

    row = connection.execute("""
        SELECT path
        FROM songs
        WHERE enabled = 1
        ORDER BY RANDOM()
        LIMIT 1
    """).fetchone()

    connection.close()

    if row is None:
        raise RuntimeError("No enabled songs in catalog")

    return os.fsencode(MUSIC_ROOT) + b"/" + os.fsencode(row[0])


def main():
    song = get_song()

    print("Streaming test song:")
    print(os.fsdecode(song))
    print()

    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "warning",

        "-re",
        "-i", song,

        "-vn",

        "-c:a", "libmp3lame",
        "-b:a", "192k",
        "-ar", "44100",
        "-ac", "2",

        "-f", "mp3",

        "http://127.0.0.1:8001/?listen=1",
    ]

    print("Starting FFmpeg...")
    print("Stream: http://127.0.0.1:8001/?listen=1")
    print()

    process = subprocess.run(command)

    sys.exit(process.returncode)


if __name__ == "__main__":
    main()
