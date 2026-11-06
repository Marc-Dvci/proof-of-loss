# The offline checks in a clean container, with no model and no key: the official Skill checker, the package limits,
# the tests, and every recorded rehearsal case replayed through the real harness.
#   docker build -t proof-of-loss . && docker run --rm --network none proof-of-loss
FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv curl unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# The UGREEN Skill Developer Package, next to the project as the tools expect it.
RUN curl -sL -o /tmp/kit.zip "https://cdn.shopify.com/s/files/1/0630/9416/1602/files/uliya-skill-kit-0.7.3-en.zip" \
    && unzip -q /tmp/kit.zip -d /work && mv /work/uliya-skill-kit /work/uliya-skill-kit-0.7.3 && rm /tmp/kit.zip

WORKDIR /work/proof-of-loss
COPY requirements.txt requirements-dev.txt ./
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r requirements-dev.txt

COPY . .
RUN useradd --create-home checker && chown -R checker /work
USER checker

ENV PATH=/opt/venv/bin:$PATH
CMD ["sh", "-c", "python tools/build_package.py && python -m pytest -q && python tools/replay.py all --quiet --out /tmp/replay"]
