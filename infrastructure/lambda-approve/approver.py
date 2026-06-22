import os
import json
import string
import secrets
import http.client
import base64
import urllib.parse
import socks

import boto3

kms = boto3.client("kms")
secretsmanager = boto3.client("secretsmanager")

KMS_KEY_ID = os.environ["KMS_KEY_ID"]
API_BASE_URL = os.environ["API_BASE_URL"]
API_USERNAME = os.environ["API_USERNAME"]

# Fetched from Secrets Manager at cold start — never in env vars.
API_PASSWORD = None


def _load_api_password():
    global API_PASSWORD
    if API_PASSWORD is None:
        secret_arn = os.environ["ADMIN_API_PASSWORD_ARN"]
        resp = secretsmanager.get_secret_value(SecretId=secret_arn)
        API_PASSWORD = resp["SecretString"]
    return API_PASSWORD

# Characters used to generate random passwords.
ALPHANUMERIC = string.ascii_letters + string.digits


def main(event, context):
    """Handle approve/deny requests from the registration email links.

    Called via Lambda Function URL with query parameters:
      ?action=approve&token=<kms-encrypted-username>&user=<username>
      ?action=deny&token=<kms-encrypted-username>&user=<username>
    """
    params = event.get("queryStringParameters") or {}
    action = params.get("action", "approve")
    token = params.get("token", "")
    user = params.get("user", "")

    if not token:
        return html_response(400, "<h1>Missing token</h1>")

    username = decrypt_token(token)
    if not username:
        return html_response(400, "<h1>Invalid or expired link</h1>")

    if action != "approve":
        return html_response(200, DENY_HTML.format(user=user))

    # action == "approve" (default)
    password = generate_password(16)
    result = create_new_user(username, password)

    # API returns 404 when the username is already taken.
    if result == 404:
        username = username + random_digits(2)
        result = create_new_user(username, password)

    if result == 200:
        print(f"Approved user {username}")
        return html_response(200, APPROVE_HTML.format(user=username, password=password))
    else:
        print(f"API returned status {result} for user {username}")
        return html_response(502, f"<h1>Upstream API error ({result})</h1>")


# ── HTTP via Tailscale SOCKS5 proxy ─────────────────────────────────────────

def create_new_user(username, password):
    """POST credentials to the registration API on the tailnet.

    Routes through the Tailscale SOCKS5 proxy (localhost:1055) set up by the
    bootstrap script.  Uses raw http.client + pysocks so that boto3 KMS calls
    are NOT proxied.
    """
    host, port, path = parse_url(API_BASE_URL)
    print(f"Connecting to {host}:{port}{path} via SOCKS5 proxy")

    sock = socks.socksocket()
    socks.set_default_proxy(socks.SOCKS5, "localhost", 1055)
    try:
        sock.connect((host, port))
    except Exception as exc:
        print(f"SOCKS5 connect failed: {type(exc).__name__}: {exc}")
        raise

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


def parse_url(url):
    """Extract hostname, port, and path from a URL string.

    Returns (host, port, path) where port defaults to 80 and path to "/".
    """
    parsed = urllib.parse.urlparse(url.strip())
    host = parsed.hostname or url.strip()
    port = parsed.port or 80
    path = parsed.path or "/"
    return host, port, path


# ── KMS helpers ──────────────────────────────────────────────────────────────

def decrypt_token(token):
    """Decrypt a KMS-encrypted URL-safe token. Returns plaintext or None."""
    try:
        padded = token + "=" * (-len(token) % 4)
        ciphertext = base64.urlsafe_b64decode(padded)
        resp = kms.decrypt(KeyId=KMS_KEY_ID, CiphertextBlob=ciphertext)
        return resp["Plaintext"].decode()
    except Exception as exc:
        print(f"KMS decrypt error: {exc}")
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
