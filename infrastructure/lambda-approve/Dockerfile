FROM python:3.13-slim AS build

ARG FUNCTION_DIR="/function"
RUN mkdir -p ${FUNCTION_DIR}
COPY requirements.txt ${FUNCTION_DIR}/
WORKDIR ${FUNCTION_DIR}
RUN pip install uv
RUN uv pip install --target ${FUNCTION_DIR} -r requirements.txt


FROM python:3.13.14-alpine3.23

ARG FUNCTION_DIR="/function"
WORKDIR ${FUNCTION_DIR}

COPY --from=build ${FUNCTION_DIR} ${FUNCTION_DIR}

# Copy Tailscale binaries from the official image.
COPY --from=docker.io/tailscale/tailscale:stable /usr/local/bin/tailscaled ${FUNCTION_DIR}/tailscaled
COPY --from=docker.io/tailscale/tailscale:stable /usr/local/bin/tailscale ${FUNCTION_DIR}/tailscale

# Create symlinks so Tailscale can write state to /tmp (writable in Lambda).
RUN mkdir -p /var/run && ln -s /tmp/tailscale /var/run/tailscale && \
    mkdir -p /var/cache && ln -s /tmp/tailscale /var/cache/tailscale && \
    mkdir -p /var/lib && ln -s /tmp/tailscale /var/lib/tailscale

COPY bootstrap ${FUNCTION_DIR}/bootstrap
COPY fetch_authkey.py ${FUNCTION_DIR}/fetch_authkey.py
COPY approver.py ${FUNCTION_DIR}/approver.py
RUN chmod +x ${FUNCTION_DIR}/bootstrap

ENTRYPOINT ["/function/bootstrap"]
