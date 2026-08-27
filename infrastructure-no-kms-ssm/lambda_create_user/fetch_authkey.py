"""Fetch the Tailscale auth key from SSM Parameter Store at cold start.

Called by the bootstrap script before tailscale up. Writes the plaintext key to
/tmp/tailscale-authkey so the bootstrap script can read it.

The Lambda execution role needs ssm:GetParameter permission.
"""

import os
import boto3

PARAM_NAME = os.environ["TAILSCALE_AUTHKEY_PARAM"]
OUTPUT_FILE = "/tmp/tailscale-authkey"

ssm = boto3.client("ssm")

resp = ssm.get_parameter(Name=PARAM_NAME, WithDecryption=True)
key = resp["Parameter"]["Value"]

with open(OUTPUT_FILE, "w") as f:
    f.write(key)

print(f"Auth key written to {OUTPUT_FILE}")
