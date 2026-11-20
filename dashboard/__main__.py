"""py -m dashboard --config repos.json: serve the live Dashboard on localhost and open it.

If a Dashboard is already running on the port, just open it. Safe to run repeatedly.
"""
import argparse
import json
import os
import sys
import webbrowser

from . import app, collect
from .cache import Cache
from .launcher import probe
from .server import DEFAULT_PORT, make_server


def main(argv=None):
    ap = argparse.ArgumentParser(prog="dashboard", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", default=os.environ.get("FACTORY_REPOS", "repos.json"),
                    help="JSON list of repos (default: $FACTORY_REPOS, else ./repos.json); see config/repos.example.json")
    ap.add_argument("--port", type=int, default=DEFAULT_PORT, help="port on 127.0.0.1 (0 picks a free one)")
    ap.add_argument("--no-open", action="store_true", help="do not open the browser")
    a = ap.parse_args(argv)

    cfg = os.path.abspath(a.config)
    if not os.path.isfile(cfg):
        sys.exit(f"No repo list at {cfg}. Copy config/repos.example.json, edit it, and pass --config or set FACTORY_REPOS.")
    with open(cfg, encoding="utf-8") as f:
        repos = json.load(f)

    if a.port:
        kind = probe(a.port)
        if kind == "dashboard":
            url = f"http://127.0.0.1:{a.port}/"
            print(url, flush=True)
            if not a.no_open:
                webbrowser.open(url)
            return
        if kind == "foreign":
            sys.exit(f"Port {a.port} is in use by something that is not the Dashboard. Pick another with --port.")

    cache = Cache()
    collect.register(cache, repos)
    try:
        server = make_server(lambda: app.build_state(repos, cache), port=a.port)
    except OSError as e:
        sys.exit(f"Cannot listen on port {a.port}: {e}. Pick another with --port.")
    cache.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(url, flush=True)
    if not a.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        cache.stop()
        server.server_close()


if __name__ == "__main__":
    main()
