# backlog

- SFTP to send email to the requester
- make a container image lighter. either switch back to alpine and add missing libs, or maybe just one single stage

- passwords shouldn't be stored in the server.
  - i don't think it's needed at all
  - stored in plaintext in the server  `cat /var/www/webdav/.users`
- registration page should let users create their password
  - include this in the whole encryption/decryption flow.
- register page should check that username is only alphanumerical characters.
- passwords can have alpha & special characters
- clean up infra files:
  - one DEPLOY.md for both infra
  - new arch.md with diagrams
- add a script to populate secrets in KMS stack
- rename the lambda directories with better names
   - lambda -> lambda-registration
  - lambda-approve -> lambda-create-user