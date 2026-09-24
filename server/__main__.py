"""Start the server: python -m server [--port 8000] [--brain reduced|full] [--https ...].

HTTPS (needed by iOS Safari for shake and camera), either:
  --certfile cert.pem --keyfile key.pem   (e.g. made with mkcert for this machine's LAN IP)
  or run `ngrok http 8000` next to the plain server; the dashboard QR code picks it up.
"""

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
    ap.add_argument("--certfile", default=SERVER.certfile, help="PEM certificate for HTTPS")
    ap.add_argument("--keyfile", default=SERVER.keyfile, help="PEM private key for HTTPS")
    ap.add_argument("--public-url", default=SERVER.public_url,
                    help="URL for the dashboard QR code (default: FLY_PUBLIC_URL, ngrok, LAN)")
    args = ap.parse_args()
    if bool(args.certfile) != bool(args.keyfile):
        ap.error("--certfile and --keyfile go together")
    cfg = dataclasses.replace(SERVER, host=args.host, port=args.port, brain_mode=args.brain,
                              certfile=args.certfile, keyfile=args.keyfile,
                              public_url=args.public_url)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")

    import uvicorn
    from server.app import create_app
    from server.web import phone_url
    scheme = "https" if cfg.certfile else "http"
    logging.getLogger("fly.server").info(
        "dashboard: %s://localhost:%d/dashboard/   phone: %s", scheme, cfg.port,
        phone_url(cfg)["url"])
    uvicorn.run(create_app(cfg), host=cfg.host, port=cfg.port, log_level="info",
                ssl_certfile=cfg.certfile, ssl_keyfile=cfg.keyfile)


if __name__ == "__main__":
    main()
