#!/usr/bin/env python3

import http.server
import os
import queue
import sqlite3
import subprocess
import sys
import threading
import time
import json
import socket
import base64
from mutagen import File as MutagenFile

PORT = 8001

ICECAST_HOST = "127.0.0.1"
ICECAST_PORT = 8002
ICECAST_MOUNT = "/forge.mp3"

ICECAST_SOURCE_USER = "source"
ICECAST_SOURCE_PASSWORD = "M!623G@g7"

sys.stdout.reconfigure(errors="backslashreplace")
sys.stderr.reconfigure(errors="backslashreplace")


DATABASE = "/var/lib/dennis-radio/radio.db"
MUSIC_ROOT = "/mnt/forge-storagebox/backups"

HOST = "127.0.0.1"
PORT = 8001

AUDIO_EXTENSIONS = {
    ".mp3",
    ".flac",
    ".ogg",
    ".m4a",
    ".aac",
    ".wav",
}

listeners = set()
listeners_lock = threading.Lock()

current_song = None
current_song_lock = threading.Lock()
# ============================================================
# Icecast source
# ============================================================

class IcecastSource:

    def __init__(self):
        self.sock = None
        self.lock = threading.Lock()

    def disconnect(self):

        with self.lock:

            if self.sock is not None:

                try:
                    self.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

                try:
                    self.sock.close()
                except OSError:
                    pass

                self.sock = None

    def connect(self):

        self.disconnect()

        print(
            "Connecting to Icecast..."
        )

        sock = socket.create_connection(
            (
                ICECAST_HOST,
                ICECAST_PORT,
            ),
            timeout=10,
        )

        credentials = base64.b64encode(
            (
                f"{ICECAST_SOURCE_USER}:"
                f"{ICECAST_SOURCE_PASSWORD}"
            ).encode()
        ).decode()

        request = (
            f"SOURCE {ICECAST_MOUNT} ICE/1.0\r\n"
            f"Host: {ICECAST_HOST}\r\n"
            f"Authorization: Basic {credentials}\r\n"
            f"Content-Type: audio/mpeg\r\n"
            f"Cache-Control: no-cache\r\n"
            f"ice-name: Dennis Forge Radio\r\n"
            f"ice-description: Dennis Forge Internet Radio\r\n"
            f"ice-url: https://radio.dennis-forge.com/\r\n"
            f"ice-public: 1\r\n"
            f"ice-audio-info: bitrate=128;samplerate=44100;channels=2\r\n"
            f"\r\n"
        )

        sock.sendall(
            request.encode()
        )

        response = sock.recv(4096)

        if b"200 OK" not in response:
            sock.close()

            raise RuntimeError(
                "Icecast rejected source connection: "
                f"{response!r}"
            )

        sock.settimeout(None)

        with self.lock:
            self.sock = sock

        print(
            "Icecast source connected: "
            f"{ICECAST_MOUNT}"
        )

    def send(self, data):

        with self.lock:

            sock = self.sock

            if sock is None:
                return False

            try:

                sock.sendall(data)

                return True

            except (
                BrokenPipeError,
                ConnectionResetError,
                ConnectionAbortedError,
                OSError,
            ):

                print(
                    "Icecast source connection lost."
                )

                try:
                    sock.close()
                except OSError:
                    pass

                self.sock = None

                return False

icecast_source = IcecastSource()

icecast_queue = queue.Queue(maxsize=16)

def icecast_worker():

    # One dedicated writer owns the Icecast socket.
    while True:
        data = icecast_queue.get()
        try:
            while True:
                try:
                    if icecast_source.sock is None:
                        icecast_source.connect()
                    if icecast_source.send(data):
                        break
                except Exception as exc:
                    print(f"Icecast worker error: {exc}")
                    icecast_source.disconnect()
                    time.sleep(2)
        finally:
            icecast_queue.task_done()

# ============================================================
# Radio database
# ============================================================

def get_next_song():

    connection = sqlite3.connect(DATABASE)

    try:

        row = connection.execute("""
            SELECT id, path, filename
            FROM songs
            WHERE enabled = 1
            ORDER BY RANDOM()
            LIMIT 1
        """).fetchone()

    finally:

        connection.close()

    if row is None:

        raise RuntimeError(
            "No enabled songs in radio database"
        )

    song_id, path, filename = row

    # SQLite stores path and filename as BLOBs.
    #
    # This is intentional. Some filesystem entries contain
    # byte sequences which cannot safely be decoded as UTF-8.

    path_bytes = bytes(path)
    filename_bytes = bytes(filename)

    filesystem_path = os.path.join(
        os.fsencode(MUSIC_ROOT),
        path_bytes,
    )

    return (
        song_id,
        filesystem_path,
        filename_bytes,
    )

def get_display_title(path, filename):
    """
    Try to obtain Artist + Title from embedded metadata.

    If metadata is unavailable or unusable, fall back to
    the filesystem filename.
    """

    fallback = os.fsdecode(filename)

    try:
        audio = MutagenFile(path, easy=True)

        if audio is not None:

            artist = audio.get("artist", [None])[0]
            title = audio.get("title", [None])[0]

            if artist and title:
                return f"{artist} — {title}"

            if title:
                return title

            if artist:
                return artist

    except Exception as exc:

        print(
            f"Metadata read failed for {fallback!r}: "
            f"{exc}"
        )

    return fallback

# ============================================================
# Now playing
# ============================================================

def set_current_song(
    song_id,
    path,
    filename,
):

    global current_song

    with current_song_lock:

        current_song = {
            "id": song_id,
            "filename": filename,
            "path": path,
            "display": get_display_title(path, filename),
            "started": time.time(),
        }


def clear_current_song():

    global current_song

    with current_song_lock:

        current_song = None
        


# ============================================================
# Radio loop
# ============================================================

def radio_loop():

    while True:

        process = None

        try:

            song_id, path, filename = get_next_song()

            # --------------------------------------------------
            # Verify filesystem entry.
            # --------------------------------------------------

            if not os.path.isfile(path):

                print()
                print(
                    "Skipping missing filesystem entry:"
                )

                print(
                    f"  ID:       {song_id}"
                )

                print(
                    f"  Filename: {filename!r}"
                )

                print(
                    f"  Path:     {path!r}"
                )

                continue

            # --------------------------------------------------
            # Announce current song.
            # --------------------------------------------------

            set_current_song(
                song_id,
                path,
                filename,
            )

            print()
            print("Now playing:")

            print(
                f"  ID:       {song_id}"
            )

            print(
                f"  Filename: {filename!r}"
            )

            print(
                f"  Path:     {path!r}"
            )

            # --------------------------------------------------
            # Start FFmpeg.
            # --------------------------------------------------

            process = subprocess.Popen(
                [
                    "/usr/bin/ffmpeg",

                    "-hide_banner",
                    "-loglevel",
                    "error",

                    "-re",
                    "-i",
                    path,

                    "-vn",

                    "-c:a",
                    "libmp3lame",

                    "-b:a",
                    "128k",

                    "-f",
                    "mp3",

                    "pipe:1",
                ],

                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )

            # --------------------------------------------------
            # Read FFmpeg continuously.
            #
            # This loop NEVER performs network I/O.
            # --------------------------------------------------

            while True:

                data = process.stdout.read(
                    64 * 1024
                )

                if not data:
                    break

                try:
                    icecast_queue.put(data, timeout=2)
                except queue.Full:
                    print(
                        "Icecast queue full; "
                        "dropping audio chunk."
                    )

            # --------------------------------------------------
            # Wait until FFmpeg really finishes.
            # --------------------------------------------------

            process.wait()

            if process.returncode != 0:

                error = process.stderr.read().decode(
                    errors="replace"
                )

                print(
                    f"FFmpeg failed for song "
                    f"{song_id}:"
                )

                print(
                    error.strip()
                )

            else:

                print(
                    f"Finished song {song_id}"
                )

        except Exception as exc:

            print(
                f"Radio error: {exc}"
            )

            time.sleep(2)

        finally:

            if process is not None:

                if process.poll() is None:

                    process.kill()

                    try:

                        process.wait(
                            timeout=2
                        )

                    except subprocess.TimeoutExpired:

                        pass

            clear_current_song()


# ============================================================
# HTTP status handler
# ============================================================

class RadioHandler(http.server.BaseHTTPRequestHandler):

    protocol_version = "HTTP/1.1"

    def log_message(self, format_string, *args):
        print(f"{self.client_address[0]} - {format_string % args}")

    def do_GET(self):
        if self.path != "/now-playing":
            self.send_error(404)
            return

        with current_song_lock:
            song = current_song
            if song is not None:
                response = {
                    "id": song["id"],
                    "filename": os.fsdecode(song["filename"]),
                    "path": os.fsdecode(song["path"]),
                    "display": song["display"],
                    "started": song["started"],
                }
            else:
                response = {"id": None, "filename": None, "path": None, "started": None}

        payload = json.dumps(response, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-cache, no-store")
        self.end_headers()
        self.wfile.write(payload)


# ============================================================
# Main
# ============================================================

def main():

    print(
        "Dennis Forge Radio Stream"
    )

    print(
        "========================="
    )

    print(
        f"Listening on "
        f"http://{HOST}:{PORT}/"
    )

    try:

        icecast_source.connect()

    except Exception as exc:

        print(
            "Initial Icecast connection failed: "
            f"{exc}"
        )

        print(
            "Radio will continue and retry Icecast."
        )

    icecast_thread = threading.Thread(
        target=icecast_worker,
        daemon=True,
    )

    icecast_thread.start()


    broadcaster = threading.Thread(
        target=radio_loop,
        daemon=True,
    )

    broadcaster.start()

    class ReusableHTTPServer(
        http.server.ThreadingHTTPServer
    ):

        allow_reuse_address = True

    server = ReusableHTTPServer(
        (HOST, PORT),
        RadioHandler,
    )

    try:

        server.serve_forever()

    except KeyboardInterrupt:

        print(
            "\nStopping radio..."
        )

    finally:

        server.server_close()


if __name__ == "__main__":

    main()