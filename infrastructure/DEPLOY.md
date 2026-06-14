# Infrastructure — Deployment Guide

## Architecture

```
User browser  ──GET /──►  Lambda Function URL (public HTTPS)
               POST /        │
                             ▼
                    Lambda (Python 3.12)
                       │          │
                       ▼          ▼
                  Serve HTML    SES → admin email
                  (from file)   (with KMS-encrypted approve/deny links)
```

**Resources created:**
- Lambda function (Python 3.12, reads `register.html` from disk)
- Lambda Function URL (public HTTPS endpoint, no API Gateway)
- KMS key (encrypts email addresses in approve/deny tokens)
- IAM role + policy (Lambda can call SES `SendEmail` and KMS encrypt/decrypt)
- SES email identity (admin email, must be verified)

**Files:**
- `template.yaml` — CloudFormation stack definition
- `lambda/index.py` — Lambda handler
- `lambda/register.html` — registration page (edit this to change the UI)

---

## Cost

| Resource | Free tier | Typical monthly cost |
|----------|-----------|---------------------|
| **CloudFormation** | **Always free** — no charge for stacks | **$0** |
| Lambda Function URL | Free (included with Lambda) | **$0** |
| Lambda | 1 M requests + 400K GB-seconds/month (12 months) | ~$0 after free tier |
| SES | 62K emails/month (from Lambda) | ~$0 |
| KMS | 20K free requests/month | ~$0 |

> **Reminder:** CloudFormation itself is free. You only pay for the resources it creates. All resources here stay within the AWS free tier.

---

## Prerequisites

1. **AWS CLI** configured with credentials:
   ```bash
   aws configure
   ```
2. **SES admin email verified** — if your SES account is still in sandbox mode (the default), the `AdminEmail` address must be verified:
   ```bash
   aws ses verify-email-identity --email-address admin@example.com
   ```
   Then click the verification link in the email AWS sends you.

---

## Authenticate in AWS

To authenticate with aws in the aws-cli do the following:
- authenticate in your aws account as root user with your email and password
- open your terminal and run `aws login --profile admin`
- enter the aws region closest to you (us-east-1, etc.)
- in your browser find the new aws tab opened and select the account you want to authenticate with

If successfull the page will show "Your credentials have been shared successfully and can be used until your session expires. You can now close this tab." and in your terminal will show "Updated profile default to use arn:aws:iam::<AWS_ACCOUNT_ID>:root credentials."

The region you entered is the region where aws resources will be deployed. **Make sure to set your region in the AWS website to the same one** (click on the arrow down in-between the settings icon and your profile name on the right of the top banner).

Test the connection and save your account ID:
> aws sts get-caller-identity --profile admin
> ACCOUNT_ID=$(aws sts get-caller-identity --profile admin --query Account --output text)

To log out later simply run
> aws logout --profile admin

## Create a Cloudformation deployer role

It will be assumed by Cloudformation to deploy the stack. Note that this is optional and you can instead deploy using your admin profile which has all permissions in this case skip to ###4. .

**From the project root**, three steps:

### 1. Create the role with CloudFormation as trusted service
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

### 2. Create the managed policy from the file (upload it first, then run this from the same dir)
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

### 3. Attach the policy to the role (replace ACCOUNT_ID with yours)
```sh
aws iam attach-role-policy \
  --profile admin \
  --role-name home-cloud-deployer-role \
  --policy-arn arn:aws:iam::$ACCOUNT_ID:policy/home-cloud-deployer-policy
```

## Package and Deploy

## Pre-req (run once)
Create an S3 bucket for your deployment.
> `YOUR_DEPLOY_BUCKET=home-cloud-bucket`
> `aws s3 mb s3://$YOUR_DEPLOY_BUCKET --profile admin`

You can always delete it later without breaking the page. If you decide to make an update you can simply re-create it.
> `aws s3 rb s3://$YOUR_DEPLOY_BUCKET --profile admin`

### Package
This uploads the Lambda code and HTML page to S3. It creates a new yaml template which includes a reference to the files in S3 (search for "S3Key" in file 'infrastructure/packaged.yaml')

```bash
aws cloudformation package \
  --template-file infrastructure/template.yaml \
  --s3-bucket $YOUR_DEPLOY_BUCKET \
  --output-template-file infrastructure/packaged.yaml \
  --profile admin
```

### Deploy

Replace the admin email with your email.

```sh
aws cloudformation deploy \
  --profile admin \
  --template-file infrastructure/packaged.yaml \
  --stack-name home-cloud-registration \
  --parameter-overrides FromAdminEmail=admin@test.com ToAdminEmail=admin2@test.com \
  --capabilities CAPABILITY_IAM \
  --role-arn arn:aws:iam::$ACCOUNT_ID:role/home-cloud-deployer-role
```

### Delete the stack
> aws cloudformation delete-stack --profile admin --stack-name home-cloud-registration
Run the wait command first if you want to re-create the stack
> aws cloudformation wait stack-delete-complete --profile admin --stack-name home-cloud-registration 

### 2. Deploy

```bash
aws cloudformation deploy \
  --template-file infrastructure/packaged.yaml \
  --stack-name home-cloud-registration \
  --parameter-overrides \
    AdminEmail=admin@example.com \
  --capabilities CAPABILITY_IAM
```

Replace `admin@example.com` with your actual admin email.

---

## How approve/deny tokens work

When a user registers, the Lambda encrypts their email address with the KMS key created by the stack. The encrypted email becomes the `token` parameter in the approve/deny links. On click, the Lambda decrypts the token with KMS to recover the email.

- Only someone with KMS access can forge a valid token
- No secret needs to be stored or passed as a parameter
- The KMS key is auto-created and auto-rotated by AWS

---

## Get the registration URL

```bash
aws cloudformation describe-stacks \
  --stack-name home-cloud-registration \
  --query 'Stacks[0].Outputs[?OutputKey==`RegistrationUrl`].OutputValue' \
  --output text
```

Share this URL with users. Visiting it shows the registration form.

---

## Editing the registration page

Edit `infrastructure/lambda/register.html`, then re-run the package + deploy commands. The HTML is read from disk at Lambda cold start, so changes take effect on the next deployment.

---

## Updating the stack

Edit `template.yaml` or `lambda/` files, then re-run the package + deploy commands. CloudFormation will update only the changed resources.

---

## Deleting the stack

```bash
aws cloudformation delete-stack --stack-name home-cloud-registration
```

This removes all resources created by the stack (Lambda, Function URL, KMS key, IAM role). SES email identity must be removed separately if no longer needed.

---

## Next steps

- Wire up `/approve` and `/deny` to actually create WebDAV accounts.
- Move SES out of sandbox mode to send to unverified email addresses.
- Optionally add a custom domain via CloudFront or API Gateway if needed later.
