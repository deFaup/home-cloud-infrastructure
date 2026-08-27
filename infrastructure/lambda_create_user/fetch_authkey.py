"""Fetch the Tailscale auth key from Secrets Manager at cold start.

Called by the bootstrap script before tailscale up. Writes the plaintext key to
/tmp/tailscale-authkey so the bootstrap script can read it.

The Lambda execution role needs secretsmanager:GetSecretValue permission.
"""

import os
import boto3

SECRET_ARN = os.environ["TAILSCALE_AUTHKEY_ARN"]
OUTPUT_FILE = "/tmp/tailscale-authkey"

secretsmanager = boto3.client("secretsmanager")

resp = secretsmanager.get_secret_value(SecretId=SECRET_ARN)
key = resp["SecretString"]

with open(OUTPUT_FILE, "w") as f:
    f.write(key)

print(f"Auth key written to {OUTPUT_FILE}")
