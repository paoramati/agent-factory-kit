"""Decide what to do about the port before starting: reuse a running Dashboard, or refuse a foreign one."""
import http.client
import json

from .app import APP

CONNECT_TIMEOUT = 5.0


def probe(port, host="127.0.0.1", timeout=2.0):
    """'dashboard' if our Dashboard answers there, 'free' if nothing listens, else 'foreign'."""
    # Windows can take ~2s to refuse a loopback connect, so connecting gets a longer timeout than reading.
    c = http.client.HTTPConnection(host, port, timeout=CONNECT_TIMEOUT)
    try:
        c.connect()
        c.sock.settimeout(timeout)
        c.request("GET", "/api/state")
        r = c.getresponse()
        try:
            return "dashboard" if json.loads(r.read()).get("app") == APP else "foreign"
        except (ValueError, AttributeError):
            return "foreign"
    except ConnectionRefusedError:
        return "free"
    except OSError:  # accepted the connection but never spoke HTTP, or reset it
        return "foreign"
    finally:
        c.close()
