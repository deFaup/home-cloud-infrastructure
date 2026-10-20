# backlog

code:
- SFTP to send email to the requester
- implement a time limit for approval requests

infra:
- passwords shouldn't be stored in the server.
  - i don't think it's needed at all
  - stored in plaintext in the server  `cat /var/www/webdav/.users`
- add a script to populate secrets in KMS stack
- server regenerate nginx config for each user when adding/removing one; should simply edit the one