# Offline checks in a clean container: the official Skill checker, the package limits and the offline tests.
#   docker build -t proof-of-loss . && docker run --rm --network none proof-of-loss
FROM node:22-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-pip curl unzip ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN pip3 install --no-cache-dir --break-system-packages piexif pypdf reportlab pillow markdown pytest
RUN curl -sL -o /tmp/kit.zip "https://cdn.shopify.com/s/files/1/0630/9416/1602/files/uliya-skill-kit-0.7.3-en.zip" \
    && unzip -q /tmp/kit.zip -d /work && mv /work/uliya-skill-kit /work/uliya-skill-kit-0.7.3 && rm /tmp/kit.zip
WORKDIR /work/proof-of-loss
COPY . .
CMD ["sh", "-c", "python3 tools/build_package.py && python3 -m pytest -q tests"]
