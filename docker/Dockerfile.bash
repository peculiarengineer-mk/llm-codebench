# llm-codebench Bash sandbox image.
# Built offline once by bench.sandbox.ensure_images(); runs with --network none.
# A GNU base (debian:12-slim) is chosen over bash:5-alpine/BusyBox so problems can
# rely on standard GNU tool behavior (coreutils/sed/grep are already present; gawk
# is NOT in the slim base and must be added).
FROM debian:12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash gawk \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 runner

USER runner
WORKDIR /tmp
