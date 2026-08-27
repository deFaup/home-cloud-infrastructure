# Define custom function directory
ARG FUNCTION_DIR="/function"

FROM python:3.13.14-alpine AS build

# Include global arg in this stage of the build
ARG FUNCTION_DIR

RUN mkdir -p ${FUNCTION_DIR}
COPY . ${FUNCTION_DIR}/
WORKDIR ${FUNCTION_DIR}

# Use 'uv' python package manager to install dependencies
RUN rm -f Dockerfile && \
    wget -qO- https://astral.sh/uv/install.sh | sh && \
    $HOME/.local/bin/uv pip install --target ${FUNCTION_DIR} -r requirements.txt && \
    rm -rf $HOME/.local

# Copy Tailscale binaries from the official image.
COPY --from=docker.io/tailscale/tailscale:stable \
    /usr/local/bin/tailscaled \
    /usr/local/bin/tailscale \
    ${FUNCTION_DIR}/

# Create symlinks so Tailscale can write state to /tmp (writable in Lambda).
RUN mkdir -p /tmp/tailscale && \
    mkdir -p /var/run && ln -s /tmp/tailscale /var/run/tailscale && \
    mkdir -p /var/cache && ln -s /tmp/tailscale /var/cache/tailscale && \
    mkdir -p /var/lib && ln -s /tmp/tailscale /var/lib/tailscale

RUN chmod +x ${FUNCTION_DIR}/bootstrap

ENTRYPOINT ["/function/bootstrap"]
