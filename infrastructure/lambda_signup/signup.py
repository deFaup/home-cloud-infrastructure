import os
import json
import base64
import urllib.parse
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ses = boto3.client("ses")
kms = boto3.client("kms")
lmbd = boto3.client("lambda")

FROM_ADMIN_EMAIL = os.environ["FROM_ADMIN_EMAIL"]
TO_ADMIN_EMAIL = os.environ.get("TO_ADMIN_EMAIL", "") or FROM_ADMIN_EMAIL
KMS_KEY_ID = os.environ["KMS_KEY_ID"]
APPROVE_FUNCTION_NAME = os.environ.get("APPROVE_FUNCTION_NAME", "")

# Read the HTML once at cold start
REGISTRATION_HTML = (Path(__file__).parent / "signup.html").read_text()


def main(event, context):
    method = event["requestContext"]["http"]["method"]
    path = event["rawPath"]
    print(f"Received {method} request for {path}")

    if method == "GET" and path == "/":
        return html_response(200, REGISTRATION_HTML)

    if method == "POST" and path == "/":
        return handle_registration(event)

    if method == "GET" and path == "/approver":
        return handle_approval(event)

    return html_response(404, "<h1>404 — Not Found</h1>")

def html_response(status, body):
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "text/html; charset=utf-8",
            "Cache-Control": "no-store",
        },
        "body": body,
    }

# ── Handlers ─────────────────────────────────────────────────────────────────

def handle_registration(event):
    body = event.get("body", "")
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode()

    print("Received registration body:", body)
    params = urllib.parse.parse_qs(body)
    username = (params.get("username", [""])[0]).strip()
    email = (params.get("email", [""])[0]).strip()

    if not username or not email:
        return html_response(400, "<h1>Missing fields</h1><p>Username and email are required.</p>")

    base_url = get_base_url(event)
    approve_token = encrypt_token({"email": email, "user": username, "approved": "true"})
    deny_token = encrypt_token({"email": email, "user": username, "approved": "false"})
    approve_url = f"{base_url}/approver?token={approve_token}"
    deny_url = f"{base_url}/approver?token={deny_token}"

    email_body = (
        f"New registration request\n"
        f"────────────────────────\n"
        f"Username: {username}\n"
        f"Email:    {email}\n\n"
        f"Actions:\n"
        f"  ✅ Approve: {approve_url}\n"
        f"  ❌ Deny:    {deny_url}\n"
    )
    try:
        ses.send_email(
            Source=FROM_ADMIN_EMAIL,
            Destination={"ToAddresses": [TO_ADMIN_EMAIL]},
            Message={
                "Subject": {"Data": f"Registration request from {username}"},
                "Body": {"Text": {"Data": email_body}},
            },
        )
    except ClientError as exc:
        print(f"SES error: {exc}")
        return html_response(500, "<h1>Email send failed</h1><p>Please try again later.</p>")

    return html_response(200, SUCCESS_HTML)

def handle_approval(event):
    """Handle approve/deny requests from the registration email links.

    Called via Lambda Function URL with query parameters:
      ?token=<fernet-encrypted-payload>

    The token decrypts to a JSON dict: {email, user, approved}.
    """
    params = urllib.parse.parse_qs(event.get("rawQueryString", ""))
    token = (params.get("token", [""])[0]).strip()

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
        # TODO implement smtp email to requester
        return html_response(200, f"""
            <h1>❌ Denied</h1>
            <p>User <strong>{user}</strong> ({email}) has been denied.</p>
        """)

    return invoke_approve_function(token)

def invoke_approve_function(token):
    """Invoke the approve Lambda synchronously and return its response."""
    if not APPROVE_FUNCTION_NAME:
        return html_response(500, "<h1>Approve function not configured</h1>")

    payload = {
        "queryStringParameters": {
            "token": token,
        }
    }

    try:
        resp = lmbd.invoke(
            FunctionName=APPROVE_FUNCTION_NAME,
            InvocationType="RequestResponse",
            Payload=json.dumps(payload),
        )
        body = resp["Payload"].read().decode()
        status_code = resp.get("StatusCode", 200)

        if status_code != 200 or resp.get("FunctionError"):
            print(f"Approve Lambda error: {body}")
            return html_response(502, "<h1>Approve function error</h1>")

        # The approve Lambda returns a JSON response with statusCode and body.
        result = json.loads(body)
        return {
            "statusCode": result.get("statusCode", 200),
            "headers": {
                "Content-Type": result.get("headers", {}).get("Content-Type", "text/html"),
                "Cache-Control": "no-store",
            },
            "body": result.get("body", ""),
        }
    except Exception as exc:
        print(f"Lambda invoke error: {exc}")
        return html_response(500, "<h1>Failed to process request</h1>")

# ── KMS helpers ──────────────────────────────────────────────────────────────

def encrypt_token(payload):
    """Encrypt a dict payload with KMS, return URL-safe token."""
    try:
        plaintext = json.dumps(payload).encode()
        resp = kms.encrypt(KeyId=KMS_KEY_ID, Plaintext=plaintext)
        return base64.urlsafe_b64encode(resp["CiphertextBlob"]).rstrip(b"=").decode()
    except Exception as exc:
        print(f"KMS encrypt error: {exc}")
        return None

def decrypt_token(token):
    """Decrypt URL-safe token back to dict. Returns None if invalid."""
    try:
        padded = token + "=" * (-len(token) % 4)
        ciphertext = base64.urlsafe_b64decode(padded)
        resp = kms.decrypt(CiphertextBlob=ciphertext)
        return json.loads(resp["Plaintext"].decode())
    except Exception as exc:
        print(f"KMS decrypt error: {exc}")
        return None

# ── Helpers ──────────────────────────────────────────────────────────────────

def get_base_url(event):
    headers = event.get("headers", {})
    host = headers.get("host", "")
    scheme = headers.get("x-forwarded-proto", "https")
    return f"{scheme}://{host}"

SUCCESS_HTML = """
<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Request Submitted</title>
<style>
  :root{--bg:#0f172a;--surface:#1e293b;--border:#334155;--text:#e2e8f0;--text-secondary:#94a3b8;--radius:10px}
  @media(prefers-color-scheme:light){:root{--bg:#f8fafc;--surface:#fff;--border:#e2e8f0;--text:#1e293b;--text-secondary:#475569}}
  *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:var(--bg);color:var(--text);min-height:100vh;display:flex;align-items:center;justify-content:center;padding:2rem}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius);padding:2.5rem 2rem;max-width:440px;width:100%;text-align:center}
  .check{font-size:3rem;margin-bottom:0.75rem}h2{font-size:1.25rem;margin-bottom:0.5rem}
  p{color:var(--text-secondary);font-size:0.9rem;line-height:1.6}
</style></head><body>
<div class="card">
  <div class="check">✅</div>
  <h2>Application Submitted</h2>
  <p>Thank you for signing up! Your request has been received and is being reviewed.</p>
  <p style="margin-top:0.75rem">You will receive a confirmation by email with follow-up information once your request is accepted.</p>
</div>
</body></html>
"""
