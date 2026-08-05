#!/usr/bin/env bash
# Create SSM Parameter Store SecureString parameters for the home-cloud stack.
#
# CloudFormation cannot create SecureString parameters, so this script must be
# run once before deploying the stack (or whenever you need to rotate secrets).
#
# Usage:
#   ./infrastructure-no-kms-ssm/setup-parameters.sh [--profile admin]
#
# Parameters created (all SecureString, encrypted with AWS-managed key):
#   /home-cloud/fernet-key            — auto-generated Fernet encryption key
#   /home-cloud/tailscale-auth-key    — prompted from user
#   /home-cloud/admin-api-password    — prompted from user

set -euo pipefail

# ── Parse arguments ──────────────────────────────────────────────────────────
PROFILE_FLAG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile)
      PROFILE_FLAG="--profile $2"
      shift 2
      ;;
    *)
      echo "Unknown option: $1"
      echo "Usage: $0 [--profile admin]"
      exit 1
      ;;
  esac
done

# ── Configuration ────────────────────────────────────────────────────────────
STACK_NAME="${STACK_NAME:-home-cloud}"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  SSM Parameter Store Setup for home-cloud                   ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Stack name:  ${STACK_NAME}                                 "
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# ── Helper to create or update an SSM parameter ──────────────────────────────
put_parameter() {
  local name="$1"
  local value="$2"
  local description="$3"
  local full_name="/${STACK_NAME}/${name}"

  # Check if parameter already exists
  if aws ssm get-parameter --name "$full_name" $PROFILE_FLAG &>/dev/null; then
    echo "  ↻ Updating existing parameter: ${full_name}"
    aws ssm put-parameter \
      --name "$full_name" \
      --value "$value" \
      --type SecureString \
      --description "$description" \
      --overwrite \
      $PROFILE_FLAG \
      --output text > /dev/null
  else
    echo "  ✓ Creating parameter: ${full_name}"
    aws ssm put-parameter \
      --name "$full_name" \
      --value "$value" \
      --type SecureString \
      --description "$description" \
      $PROFILE_FLAG \
      --output text > /dev/null
  fi
}

# ── Step 1: Generate Fernet key ─────────────────────────────────────────────
echo "Step 1: Generating Fernet encryption key..."
echo ""

# Check if cryptography is available
if ! python3 -c "from cryptography.fernet import Fernet" 2>/dev/null; then
  echo "  Installing cryptography library..."
  pip3 install --quiet cryptography
fi

FERNET_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

put_parameter "fernet-key" "$FERNET_KEY" \
  "Fernet symmetric encryption key for approve/deny tokens. Fetched at runtime. Do NOT share or rotate without re-deploying the Lambda."

echo ""
echo "  Encryption key generated and stored."
echo ""

# ── Step 2: Tailscale auth key ───────────────────────────────────────────────
echo "Step 2: Tailscale auth key"
echo "  Generate one at https://login.tailscale.com/admin/settings/keys"
echo "  Make sure it is set as 'reusable' and ephemeral."
echo ""

if [[ -t 0 ]]; then
  read -rp "  Enter Tailscale auth key (tskey-auth-...): " TAILSCALE_KEY
else
  echo "  Reading from stdin..."
  read -r TAILSCALE_KEY
fi

if [[ -z "$TAILSCALE_KEY" ]]; then
  echo "  ⚠ Skipping — no value provided. You can set it later with:"
  echo "    aws ssm put-parameter --name /${STACK_NAME}/tailscale-auth-key --type SecureString --value 'tskey-auth-...' --overwrite"
else
  put_parameter "tailscale-auth-key" "$TAILSCALE_KEY" \
    "Tailscale ephemeral auth key (tskey-auth-...). The Lambda fetches this at runtime."
fi

echo ""

# ── Step 3: Admin API password ───────────────────────────────────────────────
echo "Step 3: Admin API password"
echo "  Basic auth password for the admin user management API on your tailnet."
echo ""

if [[ -t 0 ]]; then
  read -rsp "  Enter admin API password: " API_PASSWORD
  echo ""
else
  echo "  Reading from stdin..."
  read -r API_PASSWORD
fi

if [[ -z "$API_PASSWORD" ]]; then
  echo "  ⚠ Skipping — no value provided. You can set it later with:"
  echo "    aws ssm put-parameter --name /${STACK_NAME}/admin-api-password --type SecureString --value 'your-password' --overwrite"
else
  put_parameter "admin-api-password" "$API_PASSWORD" \
    "Basic auth password for the admin user management API. The Lambda fetches this at runtime."
fi

echo ""

# ── Done ─────────────────────────────────────────────────────────────────────
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✓ All parameters created in SSM Parameter Store            ║"
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Parameters (all SecureString):                             ║"
echo "║    /${STACK_NAME}/fernet-key                                  "
echo "║    /${STACK_NAME}/tailscale-auth-key                          "
echo "║    /${STACK_NAME}/admin-api-password                          "
echo "╠══════════════════════════════════════════════════════════════╣"
echo "║  Next steps:                                                ║"
echo "║  1. Package and deploy the CloudFormation stack              ║"
echo "║  2. Build and push the approve Lambda Docker image           ║"
echo "╚══════════════════════════════════════════════════════════════╝"
