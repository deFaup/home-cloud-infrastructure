#!/usr/bin/env bash

ACCOUNT_ID=$(aws sts get-caller-identity --profile admin --query Account --output text)
HOME_CLOUD_DEPLOY_BUCKET=home-cloud-bucket

# Delete the cloudformation stack and wait for it to complete
# This removes all resources defined in the template.yaml (Lambda, Function URL, IAM roles, etc.).
echo "Deleting CloudFormation stack 'home-cloud'... Takes around 2 minutes to complete."
aws cloudformation delete-stack --profile admin --stack-name home-cloud
aws cloudformation wait stack-delete-complete --profile admin --stack-name home-cloud
echo "CloudFormation stack 'home-cloud' deleted successfully."

# Delete the ECR repo and images as well as the S3 bucket and its content.
echo "Deleting ECR repository 'home-cloud-ecr-repo'..."
aws ecr delete-repository --profile admin --repository-name home-cloud-ecr-repo --force --no-cli-pager --output off
echo "ECR repository 'home-cloud-ecr-repo' deleted successfully."

echo "Deleting S3 bucket 'home-cloud-bucket'..."
aws s3 rb s3://$HOME_CLOUD_DEPLOY_BUCKET --profile admin --force
echo "S3 bucket 'home-cloud-bucket' deleted successfully."

# Delete SSM parameters:
echo "Deleting SSM parameters..."
aws ssm delete-parameter --profile admin --name /home-cloud/fernet-key
aws ssm delete-parameter --profile admin --name /home-cloud/tailscale-auth-key
aws ssm delete-parameter --profile admin --name /home-cloud/admin-api-password
echo "SSM parameters deleted successfully."

# Finally remove the deployer role and policy (delete all versions if more than one present).
echo "Deleting deployer role and policy..."
aws iam detach-role-policy \
  --profile admin \
  --role-name home-cloud-deployer-role \
  --policy-arn arn:aws:iam::$ACCOUNT_ID:policy/home-cloud-deployer-policy
aws iam list-policy-versions --profile admin --policy-arn arn:aws:iam::$ACCOUNT_ID:policy/home-cloud-deployer-policy --output text --query 'Versions[?IsDefaultVersion==`false`].VersionId' | \
  xargs -I {} aws iam delete-policy-version --profile admin --policy-arn arn:aws:iam::$ACCOUNT_ID:policy/home-cloud-deployer-policy --version-id {}
aws iam delete-policy --profile admin --policy-arn arn:aws:iam::$ACCOUNT_ID:policy/home-cloud-deployer-policy

aws iam delete-role --profile admin --role-name home-cloud-deployer-role
echo "Deployer role and policy deleted successfully."
