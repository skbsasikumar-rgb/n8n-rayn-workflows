FROM golang:1.24.6-bookworm AS build

ARG OPENSERP_REF=v0.7.2

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates git \
  && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY patches/railway-no-sandbox.patch /tmp/railway-no-sandbox.patch
RUN git clone https://github.com/karust/openserp.git . \
  && git checkout "$OPENSERP_REF" \
  && git apply /tmp/railway-no-sandbox.patch \
  && CGO_ENABLED=0 go build -ldflags="-s -w" -o /out/openserp .

FROM chromedp/headless-shell:stable

WORKDIR /usr/src/app

RUN apt-get update \
  && apt-get install -y --no-install-recommends ca-certificates \
  && rm -rf /var/lib/apt/lists/* \
  && getent passwd chrome >/dev/null 2>&1 || useradd --create-home --uid 1001 --shell /bin/bash chrome \
  && chown chrome:chrome /usr/src/app

COPY --from=build /out/openserp /usr/local/bin/openserp
COPY config.yaml /usr/src/app/config.yaml

ENV OPENSERP_APP_BROWSER_PATH=/headless-shell/headless-shell

USER chrome

ENTRYPOINT []
CMD ["sh", "-c", "exec openserp serve -a 0.0.0.0 -p ${PORT:-7000} -c /usr/src/app/config.yaml"]
