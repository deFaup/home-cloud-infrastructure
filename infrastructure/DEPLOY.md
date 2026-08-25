# Infrastructure
## Architecture

```
User browser  ──GET /──►  Signup Lambda (public URL)
               POST /        │
                             ▼
                    Lambda (Python 3.14)
                       │          │
                       ▼          ▼
                  Serve HTML    SES → admin email
                  (from file)   (with KMS-encrypted approve/deny links)

Admin clicks  ──────────►  Signup Lambda (/approve or /deny)
  approve link                  │
                                ▼
                          lambda.invoke()
                                │
                                ▼
                          Approve Lambda (private, no public URL)
                                │
                                ▼
                           KMS decrypt
                           Generate password
                           POST via Tailscale SOCKS5 proxy
                             → Registration API
```

**Resources created:**
- Signup Lambda function (Python 3.14, reads `signup.html` from disk)
- Approve Lambda function (container image with Tailscale, Python 3.14-slim)
- ECR repository for the approve Lambda container image
- Lambda Function URL for signup Lambda (public HTTPS endpoint, no API Gateway)
- KMS key (encrypts usernames in approve/deny tokens)
- IAM roles + policies (SES, KMS decrypt, ECR pull, Secrets Manager read, Lambda invoke)
- SES email identities (admin email, must be verified)

**Files:**
- `template.yaml` — CloudFormation stack definition
- `lambda/signup.py` — Signup Lambda handler
- `lambda/signup.html` — signup page (edit this to change the UI)
- `lambda-approve/Dockerfile` — Approve Lambda container image
- `lambda-approve/bootstrap` — Tailscale startup script
- `lambda-approve/fetch_authkey.py` — Secrets Manager auth key fetcher (runs at cold start)
- `lambda-approve/approver.py` — Approve Lambda handler

---

## Cost

| Resource | Free tier | Typical monthly cost |
|----------|-----------|---------------------|
| **CloudFormation** | **Always free** — no charge for stacks | **$0** |
| Lambda Function URL | Free (included with Lambda) | **$0** |
| Lambda | 1 M requests + 400K GB-seconds/month (12 months) | ~$0 after free tier |
| SES | 62K emails/month (from Lambda) | ~$0 |
| KMS | $0.03/10K requests | ~$0 |
| S3 | $0.023 per GB | ~0$ |
| Secrets Manager | $0.40 per Secret + $0.05 per 10000 API Requests | ~1$ |

KMS Key that are customer managed cost 1$/month. AWS managed keys are free however.
Secrets manager resources are also not free,

> **Reminder:** CloudFormation itself is free. You only pay for the resources it creates. All resources here stay within the AWS free tier.

---

# Deployment Pre-requisites

1. **AWS CLI** configured with credentials (see next section)
2. **Tailscale auth key** — generate a ephemeral auth key at https://login.tailscale.com/admin/settings/keys. Make sure to set it as "reusable". Ephemeral keys have the benefits of removing the lambda node once it goes offline. If device approval is enabled, pre-approve the key. You'll set this in Secrets Manager after the stack is deployed.
3. **Docker** with buildx plugin — required to build the approve Lambda container image.

## AWS CLI configuration

To authenticate with aws in the aws-cli do the following:
- authenticate in your aws account as root user with your email and password
- open your terminal and run `aws login --profile admin`
- enter the aws region closest to you (us-east-1, etc.)
- in your browser find the new aws tab opened and select the account you want to authenticate with

If successfull the page will show "Your credentials have been shared successfully and can be used until your session expires. You can now close this tab." 
Note: You might also see a page with the following error "This site can’t be reached. 127.0.0.1 refused to connect."
Your terminal will show "Updated profile default to use arn:aws:iam::<AWS_ACCOUNT_ID>:root credentials."

The region you entered is the region where aws resources will be deployed. **Make sure to set your region in the AWS website to the same one** (click on the arrow down in-between the settings icon and your profile name on the right of the top banner).

Test the connection and save your account ID:
```bash
aws sts get-caller-identity --profile admin
ACCOUNT_ID=$(aws sts get-caller-identity --profile admin --query Account --output text)
```

To log out later simply run
> aws logout --profile admin

---

# Deployments steps

Run this every time
```bash
aws login --profile admin
ACCOUNT_ID=$(aws sts get-caller-identity --profile admin --query Account --output text)
```

## First deploy commands (RUN ONCE)
- create a deployer role
- create an S3 bucket
- create an ECR repo; build a docker image and push it to the ECR

### I. Create a Cloudformation deployer role

It will be assumed by Cloudformation to deploy the stack. Note that this is optional and you can instead deploy using your admin profile which has all permissions in this case skip to ###4. .

**From the project root**, three steps:

#### 1. Create the role with CloudFormation as trusted service
```sh
aws iam create-role \
  --profile admin \
  --role-name home-cloud-deployer-role \
  --assume-role-policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Principal": {
          "Service": "cloudformation.amazonaws.com"
        },
        "Action": "sts:AssumeRole"
      }
    ]
  }'
```

#### 2. Create the managed policy from the file (upload it first, then run this from the same dir)
```sh
aws iam create-policy \
  --profile admin \
  --policy-name home-cloud-deployer-policy \
  --policy-document file://infrastructure/deployer-policy.json
```
For update:
```sh
aws iam create-policy-version \
  --profile admin \
  --policy-arn arn:aws:iam::${ACCOUNT_ID}:policy/home-cloud-deployer-policy \
  --policy-document file://infrastructure/deployer-policy.json \
  --set-as-default
```

#### 3. Attach the policy to the role (replace ACCOUNT_ID with yours)
```sh
aws iam attach-role-policy \
  --profile admin \
  --role-name home-cloud-deployer-role \
  --policy-arn arn:aws:iam::$ACCOUNT_ID:policy/home-cloud-deployer-policy
```

---

### II. Create the S3 bucket
Create an S3 bucket for your deployment.
> `HOME_CLOUD_DEPLOY_BUCKET=home-cloud-bucket`
> `aws s3 mb s3://$HOME_CLOUD_DEPLOY_BUCKET --profile admin`

You can always delete it later without breaking the signup page. If you decide to make an update you can simply re-create it.
> `aws s3 rb s3://$HOME_CLOUD_DEPLOY_BUCKET --profile admin`

---

### III- ECR commands
```bash
# Create an ECR (elastic container) repository
ECR_URI=$(aws ecr create-repository \
  --profile admin \
  --repository-name home-cloud-ecr-repo \
  --query 'repository.repositoryUri' \
  --output text)

# Authenticate Docker to ECR
aws ecr get-login-password --profile admin \
  | docker login --username AWS --password-stdin ${ECR_URI%%.com*}.com

# Build the image (must target linux/amd64 for Lambda)
docker buildx build --provenance=false \
  -t ${ECR_URI}:latest \
  -f infrastructure/lambda-approve/Dockerfile \
  infrastructure/lambda-approve/

# Push to ECR
docker push ${ECR_URI}:latest
```

If you ever need to update your ECR image you can repeat those steps beside the 1st one which becomes:
```bash
AWS_REGION=us-east-1 # replace with your region
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/home-cloud-ecr-repo"
```

You must replace the AWS_REGION= with your own. You can also find the full string on aws at Amazon ECR > Private registry > Repositories
Make sure to remove the older image as well.

---

## Package
This uploads the Lambda code and HTML page to S3. It creates a new yaml template which includes a reference to the files in S3 (search for "S3Key" in file 'infrastructure/packaged.yaml')

```bash
HOME_CLOUD_DEPLOY_BUCKET=home-cloud-bucket
aws cloudformation package \
  --template-file infrastructure/template.yaml \
  --s3-bucket $HOME_CLOUD_DEPLOY_BUCKET \
  --output-template-file infrastructure/packaged.yaml \
  --profile admin
```

## Deploy

```bash
aws cloudformation deploy \
  --profile admin \
  --template-file infrastructure/packaged.yaml \
  --stack-name home-cloud \
  --parameter-overrides \
    FromAdminEmail=admin@test.com \
    ToAdminEmail=admin2@test.com \
    ApproveApiBaseUrl=http://your-server:3000 \
    ApproveApiUsername=admin \
    Architecture=x86_64 \
  --capabilities CAPABILITY_IAM \
  --role-arn arn:aws:iam::$ACCOUNT_ID:role/home-cloud-deployer-role
```
Replace `admin@example.com` with your actual admin email. Architecture defaults to `x86_64` but you **must** set this to arm if you are building on an arm machine.

## Set secrets in Secrets Manager

The stack creates two Secrets Manager secrets with no value. After deploy,
update them with your real values:

```bash
# Tailscale auth key
aws secretsmanager put-secret-value \
  --profile admin \
  --secret-id "home-cloud/tailscale-auth-key" \
  --secret-string "tskey-auth-YOUR-KEY"

# API password for Basic auth on the webdav server admin API
aws secretsmanager put-secret-value \
  --profile admin \
  --secret-id "home-cloud/admin-api-password" \
  --secret-string "your-admin-api-password"
```

The approve Lambda fetches both values from Secrets Manager at cold start — they are never stored in
environment variables or visible via `lambda:GetFunction`.

---

# Delete the stack
> aws cloudformation delete-stack --profile admin --stack-name home-cloud

Run the wait command if you want to re-create the stack
> aws cloudformation wait stack-delete-complete --profile admin --stack-name home-cloud 

This removes all resources created by the stack (Lambda, Function URL, KMS key, IAM role). S3 bucket and content must be deleted separetly. Same for the ECR repo and images.

> aws ecr delete-repository --profile admin --repository-name home-cloud-ecr-repo --force

> aws s3 rb s3://$HOME_CLOUD_DEPLOY_BUCKET --profile admin --force

Finally remove the deployer role and policy (delete all versions if more than one present).
```bash
aws iam detach-role-policy \
  --profile admin \
  --role-name home-cloud-deployer-role \
  --policy-arn arn:aws:iam::$ACCOUNT_ID:policy/home-cloud-deployer-policy
aws iam list-policy-versions --profile admin --policy-arn arn:aws:iam::$ACCOUNT_ID:policy/home-cloud-deployer-policy --output text --query 'Versions[?IsDefaultVersion==`false`].VersionId' | \
  xargs -I {} aws iam delete-policy-version --profile admin --policy-arn arn:aws:iam::$ACCOUNT_ID:policy/home-cloud-deployer-policy --version-id {}
aws iam delete-policy --profile admin --policy-arn arn:aws:iam::$ACCOUNT_ID:policy/home-cloud-deployer-policy
aws iam delete-role --profile admin --role-name home-cloud-deployer-role
```

---

# Infra explained
## How approve/deny tokens work

When a user signs up, the Lambda encrypts their username with the KMS key created by the stack. The encrypted username becomes the `token` parameter in the approve/deny links. On click, the approve Lambda decrypts the token with KMS to recover the username, generates a random password, and calls the signup API over Tailscale.

- Only someone with KMS access can forge a valid token
- No secret needs to be stored or passed as a parameter
- The KMS key is auto-created and auto-rotated by AWS

## How secrets are stored

The Tailscale auth key and API password are stored in AWS Secrets Manager. They are **not**
in any Lambda environment variable or CloudFormation parameter. At cold start:

- **Auth key:** The bootstrap script runs `fetch_authkey.py` which reads the key from Secrets Manager,
  writes it to a temp file, and `tailscale up` reads it from there. The file is deleted
  immediately after.
- **API password:** The Lambda handler fetches it from Secrets Manager on first invocation and caches
  it in memory for the container's lifetime.

## Stack parameters

| Parameter | Description |
|-----------|-------------|
| `FromAdminEmail` | SES sender email (must be verified) |
| `ToAdminEmail` | SES recipient email (optional, defaults to From) |
| `ApproveApiBaseUrl` | URL of the WebDAV signup API on your tailnet (e.g. `http://my-server:3000`) |
| `ApproveApiUsername` | Basic auth username for the API |
| `Architecture` | Lambda architecture: `arm64` or `x86_64` (default `x86_64`) |

**Secrets Manager secrets (set after deploy):**

| Secret name | Description |
|-------------|-------------|
| `<stack-name>/tailscale-auth-key` | Tailscale ephemeral auth key (`tskey-auth-...`) |
| `<stack-name>/admin-api-password` | Basic auth password for the signup API |

---

## Get the signup URL

```bash
aws cloudformation describe-stacks \
  --stack-name home-cloud \
  --query 'Stacks[0].Outputs[?OutputKey==`SignupUrl`].OutputValue' \
  --output text
```

Share this URL with users. Visiting it shows the signup form.

---

## Editing the signup page

Edit `infrastructure/lambda/signup.html`, then re-run the package + deploy commands. The HTML is read from disk at Lambda cold start, so changes take effect on the next deployment.

---

## Updating the stack

Edit `template.yaml` or `lambda/` files, then re-run the package + deploy commands. CloudFormation will update only the changed resources.

**Updating the approve Lambda image:** If you change files in `lambda-approve/`, rebuild and push the Docker image, then update the Lambda function code:

```bash
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/home-cloud-ecr-repo"
docker buildx build --provenance=false \
  -t ${ECR_URI}:latest \
  -f infrastructure/lambda-approve/Dockerfile \
  infrastructure/lambda-approve/
docker push ${ECR_URI}:latest

# Force Lambda to use the new image
aws lambda update-function-code \
  --profile admin \
  --function-name home-cloud-create-user-lambda \
  --image-uri ${ECR_URI}:latest \
  --publish
```

---

---