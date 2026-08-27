#!/usr/bin/env bash

ACCOUNT_ID=$(aws sts get-caller-identity --profile admin --query Account --output text)

aws iam create-role \
  --profile admin \
  --role-name home-cloud-deployer-role \
  --no-cli-pager --output off \
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
echo "Created deployer role: home-cloud-deployer-role"

aws iam create-policy \
  --profile admin \
  --policy-name home-cloud-deployer-policy \
  --no-cli-pager --output off \
  --policy-document file://infrastructure-no-kms-ssm/deployer-policy.json
echo "Created deployer policy: home-cloud-deployer-policy"

aws iam attach-role-policy \
  --profile admin \
  --role-name home-cloud-deployer-role \
  --policy-arn arn:aws:iam::$ACCOUNT_ID:policy/home-cloud-deployer-policy

HOME_CLOUD_DEPLOY_BUCKET=home-cloud-bucket
aws s3 mb s3://$HOME_CLOUD_DEPLOY_BUCKET --profile admin
echo "Created S3 bucket: $HOME_CLOUD_DEPLOY_BUCKET"

# Create an ECR (elastic container) repository
ECR_URI=$(aws ecr create-repository \
  --profile admin \
  --repository-name home-cloud-ecr-repo \
  --query 'repository.repositoryUri' \
  --output text)
echo "Created ECR repository: $ECR_URI"

# Authenticate Docker to ECR
aws ecr get-login-password --profile admin \
  | docker login --username AWS --password-stdin ${ECR_URI%%.com*}.com

# Build the image (must target linux/amd64 for Lambda)
echo "Building Docker image for the CreateUser Lambda function..."
docker buildx build --provenance=false \
  -t ${ECR_URI}:latest \
  -f infrastructure-no-kms-ssm/lambda_create_user/Dockerfile \
  infrastructure-no-kms-ssm/lambda_create_user/

# Push to ECR
echo "Pushing Docker image to ECR..."
docker push ${ECR_URI}:latest

./infrastructure-no-kms-ssm/setup-parameters.sh --profile admin
