"""Start the server: python -m server [--port 8000] [--brain reduced|full]."""

from __future__ import annotations

import argparse
import dataclasses
import logging

from server.config import SERVER


def main() -> None:
    ap = argparse.ArgumentParser(description="Fly Tamagotchi brain server")
    ap.add_argument("--host", default=SERVER.host)
    ap.add_argument("--port", type=int, default=SERVER.port)
    ap.add_argument("--brain", choices=("reduced", "full"), default=SERVER.brain_mode,
                    help="brain mode (default: FLY_BRAIN env var, else reduced)")
    args = ap.parse_args()
    cfg = dataclasses.replace(SERVER, host=args.host, port=args.port, brain_mode=args.brain)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    import uvicorn
    from server.app import create_app
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, log_level="info")


if __name__ == "__main__":
    main()
