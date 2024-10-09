ARG BUILD_ARCH="aarch64"
FROM ghcr.io/home-assistant/${BUILD_ARCH}-base-python:3.12-alpine3.19
# WARNING: Do not update python past 3.12.* if telnetlib is still being used.

ENV DEBUG=false

ARG JPP_VERSION="f3d7b1f0944f068045d53bdcb6a963e0ca5fee0d"
RUN apk --no-cache add patch \
    && curl -J -L -o /tmp/jpp.tar.gz \
      "https://github.com/JuiceRescue/juicepassproxy/archive/${JPP_VERSION}.tar.gz" \
    && mkdir /tmp/jpp \
    && tar zxvf \
      /tmp/jpp.tar.gz \
      --strip 1 -C /tmp/jpp \
    && curl -L -o /tmp/69.patch "https://github.com/JuiceRescue/juicepassproxy/compare/f3d7b1f0944f068045d53bdcb6a963e0ca5fee0d...ivanfmartinez:juicepassproxy:juicebox_commands.diff" \
    && cd /tmp/jpp && patch < /tmp/69.patch && cd /tmp \
    && mv /tmp/jpp /juicepassproxy \
  && pip install --root-user-action=ignore --no-cache-dir -r /juicepassproxy/requirements.txt && \
  chmod -f +x /juicepassproxy/*.sh && \
  mkdir -p /log

COPY run.sh /run.sh
ENTRYPOINT /run.sh
