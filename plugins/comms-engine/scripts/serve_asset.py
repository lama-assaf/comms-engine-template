#!/usr/bin/env python3
"""Serve one local file at http://127.0.0.1:8765/asset with a CORS header.

Used by the linkedin-post skill: LinkedIn's media editor keeps its file input in
an iframe the browser extension cannot target, so the page loads the image from
here (img-src allows any origin) and hands it to the input from page script.
Serves exactly the one file named on the command line, nothing else, to the
loopback interface only. Stop it with Ctrl-C.
"""
from __future__ import annotations

import argparse
import http.server
import mimetypes
import sys
from pathlib import Path

HOST, PORT, ROUTE = "127.0.0.1", 8765, "/asset"


def make_handler(path: Path):
    data = path.read_bytes()
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

    class Handler(http.server.BaseHTTPRequestHandler):
        def _send(self, body: bool) -> None:
            if self.path.split("?")[0] != ROUTE:
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if body:
                self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            self._send(True)

        def do_HEAD(self) -> None:  # noqa: N802
            self._send(False)

        def log_message(self, *args) -> None:
            pass

    return Handler


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("file", help="the one file to serve")
    args = ap.parse_args(argv)
    path = Path(args.file).expanduser().resolve()
    if not path.is_file():
        print(f"not a file: {path}", file=sys.stderr)
        return 2
    server = http.server.ThreadingHTTPServer((HOST, PORT), make_handler(path))
    print(f"serving {path.name} at http://{HOST}:{PORT}{ROUTE}  (Ctrl-C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
