#!/usr/bin/env python3
"""Local dev server for web/ -- with HTTP Range support.

`python -m http.server` ignores the Range header and answers 200 with the whole body.
That would silently "work" here: MapLibre would receive the entire 382 MB archive for
every tile request and the page would appear fine on a fast laptop while being nothing
like production. Serving 206s locally keeps dev honest.

    python3 serve.py [port]        # default 8899
"""

import os
import re
import sys
from functools import partial
from http.server import HTTPServer, SimpleHTTPRequestHandler

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


class RangeHandler(SimpleHTTPRequestHandler):
    extensions_map = {
        **SimpleHTTPRequestHandler.extensions_map,
        ".mjs": "text/javascript",
        ".js": "text/javascript",
        ".json": "application/json",
        ".pbf": "application/x-protobuf",
        ".pmtiles": "application/octet-stream",
    }

    def end_headers(self):
        # Advertised so clients know ranges are available at all.
        self.send_header("Accept-Ranges", "bytes")
        # Local dev only: never cache, so an edit is visible on reload.
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def send_head(self):
        rng = self.headers.get("Range")
        if not rng:
            return super().send_head()

        m = RANGE_RE.match(rng.strip())
        if not m:
            self.send_error(400, "malformed Range")
            return None

        path = self.translate_path(self.path)
        if os.path.isdir(path):
            return super().send_head()
        try:
            f = open(path, "rb")
        except OSError:
            self.send_error(404)
            return None

        size = os.fstat(f.fileno()).st_size
        first, last = m.group(1), m.group(2)
        if first == "":
            # Suffix form: "bytes=-500" means the final 500 bytes.
            length = min(int(last or 0), size)
            start, end = size - length, size - 1
        else:
            start = int(first)
            end = min(int(last), size - 1) if last else size - 1

        if start >= size or start > end:
            f.close()
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{size}")
            self.end_headers()
            return None

        self.send_response(206)
        self.send_header("Content-Type", self.guess_type(path))
        self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(end - start + 1))
        self.end_headers()
        f.seek(start)
        return _Slice(f, end - start + 1)


class _Slice:
    """File wrapper that stops at `remaining` bytes, so copyfile sends only the range."""

    def __init__(self, f, remaining):
        self.f, self.remaining = f, remaining

    def read(self, n=-1):
        if self.remaining <= 0:
            return b""
        if n < 0 or n > self.remaining:
            n = self.remaining
        chunk = self.f.read(n)
        self.remaining -= len(chunk)
        return chunk

    def close(self):
        self.f.close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8899
    handler = partial(RangeHandler, directory=ROOT)
    print(f"serving {ROOT} on http://localhost:{port}  (Range supported)")
    HTTPServer(("127.0.0.1", port), handler).serve_forever()
