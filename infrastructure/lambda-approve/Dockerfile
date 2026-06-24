# Define custom function directory
ARG FUNCTION_DIR="/function"

FROM python:3.13-slim AS build

# Include global arg in this stage of the build
ARG FUNCTION_DIR

RUN mkdir -p ${FUNCTION_DIR}
COPY . ${FUNCTION_DIR}/
WORKDIR ${FUNCTION_DIR}
RUN rm Dockerfile
RUN pip install uv
RUN uv pip install --target ${FUNCTION_DIR} -r requirements.txt


# Use an even slimer version of the base Python image to reduce the final image size
FROM python:3.13.14-alpine3.23

# Include global arg in this stage of the build
ARG FUNCTION_DIR
WORKDIR ${FUNCTION_DIR}

# Copy in the built dependencies
COPY --from=build ${FUNCTION_DIR} ${FUNCTION_DIR}

# Copy Tailscale binaries from the official image.
COPY --from=docker.io/tailscale/tailscale:stable /usr/local/bin/tailscaled ${FUNCTION_DIR}/tailscaled
COPY --from=docker.io/tailscale/tailscale:stable /usr/local/bin/tailscale ${FUNCTION_DIR}/tailscale

# Create symlinks so Tailscale can write state to /tmp (writable in Lambda).
RUN mkdir -p /var/run && ln -s /tmp/tailscale /var/run/tailscale && \
    mkdir -p /var/cache && ln -s /tmp/tailscale /var/cache/tailscale && \
    mkdir -p /var/lib && ln -s /tmp/tailscale /var/lib/tailscale

RUN chmod +x ${FUNCTION_DIR}/bootstrap

ENTRYPOINT ["/function/bootstrap"]
