"""Run as an HA OS app or an explicitly local development server."""

import argparse
import json
import os
from pathlib import Path

from aiohttp import web

from .server import create_app


def main():
    parser = argparse.ArgumentParser(description="HartNet app")
    parser.add_argument("--dev", action="store_true", help="API sin token, solo en loopback")
    parser.add_argument("--port", type=int, default=8099)
    parser.add_argument("--data", default="/data/project.json")
    args = parser.parse_args()
    options_file = Path("/data/options.json")
    options = json.loads(options_file.read_text()) if options_file.exists() else {}
    token = options.get("api_token") or os.environ.get("HARTNET_API_TOKEN", "")
    app = create_app(args.data, token, dev=args.dev)
    web.run_app(app, host="127.0.0.1" if args.dev else "0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
