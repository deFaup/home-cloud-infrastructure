# backlog

code:
- SFTP to send email to the requester

infra:
- passwords shouldn't be stored in the server.
  - i don't think it's needed at all
  - stored in plaintext in the server  `cat /var/www/webdav/.users`
- clean up infra files:
  - one DEPLOY.md for both infra
  - new arch.md with diagrams
- add a script to populate secrets in KMS stack
