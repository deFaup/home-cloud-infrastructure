import os
import json
import socket
import struct
import string
import secrets
import http.client
import base64
import urllib.parse

import boto3
from cryptography.fernet import Fernet

ssm = boto3.client("ssm")

FERNET_KEY_PARAM = os.environ["FERNET_KEY_PARAM"]
API_BASE_URL = os.environ["API_BASE_URL"]
API_USERNAME = os.environ["API_USERNAME"]

# Fetched from SSM Parameter Store at cold start — never in env vars.
_fernet = None
API_PASSWORD = None


def _get_fernet():
    global _fernet
    if _fernet is None:
        resp = ssm.get_parameter(Name=FERNET_KEY_PARAM, WithDecryption=True)
        key = resp["Parameter"]["Value"].encode()
        _fernet = Fernet(key)
    return _fernet


def _load_api_password():
    global API_PASSWORD
    if API_PASSWORD is None:
        param_name = os.environ["ADMIN_API_PASSWORD_PARAM"]
        resp = ssm.get_parameter(Name=param_name, WithDecryption=True)
        API_PASSWORD = resp["Parameter"]["Value"]
    return API_PASSWORD

# Characters used to generate random passwords.
ALPHANUMERIC = string.ascii_letters + string.digits


def main(event, context):
    """Invoked by the approver Lambda.
    If the encrypted token parameter is valid then a new user is created via the registration API on the tailnet.
    Token decrypts to a JSON dict: {email, user, approved}.
    """
    params = event.get("queryStringParameters") or {}
    token = params.get("token", "")

    if not token:
        return html_response(400, "<h1>Missing token</h1>")

    data = decrypt_token(token)
    if not data:
        return html_response(400, "<h1>Invalid or expired link</h1>")

    user = data.get("user", "")
    email = data.get("email", "")
    approved = data.get("approved", "")

    if not user or not email or approved not in ("true", "false"):
        return html_response(400, "<h1>Invalid token payload</h1>")

    if approved == "false":
        return html_response(200, DENY_HTML.format(user=user))

    password = generate_password(16)
    result = create_new_user(user, password)

    # API returns 404 when the username is already taken.
    if result == 404:
        user = user + random_digits(2)
        result = create_new_user(user, password)

    if result == 201:
        return html_response(200, APPROVE_HTML.format(user=user, password=password))
    else:
        print(f"User management API returned status {result} for user {user}")
        return html_response(502, f"<h1>Upstream API error ({result})</h1>")

    # TODO - send email with user password and username asynchronously


# ── HTTP via Tailscale SOCKS5 proxy ─────────────────────────────────────────

def create_new_user(username, password):
    """POST credentials to the registration API on the tailnet.

    Routes through the Tailscale SOCKS5 proxy (localhost:1055) set up by the
    bootstrap script.  Uses raw SOCKS5 handshake (pysocks is incompatible
    with tailscaled's SOCKS5 implementation).
    """
    host, port, path = parse_url(API_BASE_URL)
    print(f"Connecting to {host}:{port}{path} via SOCKS5 proxy")

    sock = socks5_connect("localhost", 1055, host, port)

    conn = http.client.HTTPConnection(host, port)
    conn.sock = sock

    payload = json.dumps({"username": username, "password": password})
    auth = base64.b64encode(
        f"{API_USERNAME}:{_load_api_password()}".encode()
    ).decode()

    conn.request(
        "POST",
        path,
        body=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Basic {auth}",
        },
    )

    resp = conn.getresponse()
    status = resp.status
    body = resp.read().decode()
    conn.close()

    print(f"API POST -> {status}: {body}")
    return status


def socks5_connect(proxy_host, proxy_port, dest_host, dest_port, timeout=10):
    """Create a TCP connection through a SOCKS5 proxy using raw sockets.

    pysocks is incompatible with tailscaled's SOCKS5 implementation
    (packet header parsing error), so we do the handshake manually.
    """
    sock = socket.create_connection((proxy_host, proxy_port), timeout=timeout)

    # SOCKS5 greeting: version=5, 1 auth method, no-auth=0
    sock.send(b"\x05\x01\x00")
    resp = sock.recv(2)
    if resp != b"\x05\x00":
        raise ConnectionError(f"SOCKS5 auth failed: {resp.hex()}")

    # SOCKS5 CONNECT: version=5, cmd=1(connect), rsv=0, atyp=1(IPv4)
    addr = socket.inet_aton(dest_host)
    port = struct.pack("!H", dest_port)
    sock.send(b"\x05\x01\x00\x01" + addr + port)

    resp = sock.recv(10)
    if len(resp) < 2 or resp[1] != 0x00:
        raise ConnectionError(f"SOCKS5 connect failed: {resp.hex()}")

    return sock


def parse_url(url):
    """Extract hostname, port, and path from a URL string.

    Returns (host, port, path) where port defaults to 80 and path to "/".
    """
    parsed = urllib.parse.urlparse(url.strip())
    host = parsed.hostname or url.strip()
    port = parsed.port or 80
    path = parsed.path or "/"
    return host, port, path


# ── Fernet helpers ───────────────────────────────────────────────────────────

def decrypt_token(token):
    """Decrypt a Fernet-encrypted URL-safe token. Returns dict or None."""
    try:
        padded = token + "=" * (-len(token) % 4)
        f = _get_fernet()
        plaintext = f.decrypt(padded.encode())
        return json.loads(plaintext.decode())
    except Exception as exc:
        print(f"Fernet decrypt error: {exc}")
        return None


# ── Utility ──────────────────────────────────────────────────────────────────

def generate_password(length):
    return "".join(secrets.choice(ALPHANUMERIC) for _ in range(length))


def random_digits(count):
    return "".join(secrets.choice(string.digits) for _ in range(count))


def html_response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-store",
        },
        "body": body,
    }


# ── HTML templates ───────────────────────────────────────────────────────────

APPROVE_HTML = """
<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Approved</title>
<style>
  :root{{--bg:#0f172a;--surface:#1e293b;--border:#334155;--text:#e2e8f0;--text-secondary:#94a3b8;--radius:10px}}
  @media(prefers-color-scheme:light){{:root{{--bg:#f8fafc;--surface:#fff;--border:#e2e8f0;--text:#1e293b;--text-secondary:#475569}}}}
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:2rem}}
  .card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:2.5rem 2rem;max-width:440px;width:100%;text-align:center}}
  .check{{font-size:3rem;margin-bottom:0.75rem}}h2{{font-size:1.25rem;margin-bottom:0.5rem}}
  p{{color:var(--text-secondary);font-size:0.9rem;line-height:1.6}}
  .creds{{background:var(--bg);border:1px solid var(--border);border-radius:8px;padding:1rem;margin-top:1rem;text-align:left;font-family:monospace;font-size:0.85rem}}
  .creds div{{margin:0.25rem 0}}
  .creds span{{color:var(--text-secondary)}}
</style></head><body>
<div class="card">
  <div class="check">✅</div>
  <h2>Account Created</h2>
  <p>Your account has been approved and is ready to use.</p>
  <div class="creds">
    <div><span>Username:</span> {user}</div>
    <div><span>Password:</span> {password}</div>
  </div>
</div>
</body></html>
"""

DENY_HTML = """
<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Denied</title>
<style>
  :root{{--bg:#0f172a;--surface:#1e293b;--border:#334155;--text:#e2e8f0;--text-secondary:#94a3b8;--radius:10px}}
  @media(prefers-color-scheme:light){{:root{{--bg:#f8fafc;--surface:#fff;--border:#e2e8f0;--text:#1e293b;--text-secondary:#475569}}}}
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:2rem}}
  .card{{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:2.5rem 2rem;max-width:440px;width:100%;text-align:center}}
  .check{{font-size:3rem;margin-bottom:0.75rem}}h2{{font-size:1.25rem;margin-bottom:0.5rem}}
  p{{color:var(--text-secondary);font-size:0.9rem;line-height:1.6}}
</style></head><body>
<div class="card">
  <div class="check">❌</div>
  <h2>Request Denied</h2>
  <p>The registration request for <strong>{user}</strong> has been denied.</p>
</div>
</body></html>
"""
