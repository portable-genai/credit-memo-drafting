# B2 Credit-Memo / Underwriting Assistant — API service image.
#
# Builds the FastAPI service with the managed-stack extra ([gcp]) installed, so the
# deployed container talks to Document AI / Gemini / Model Armor / DLP / BigQuery / Cloud
# Logging in asia-southeast1. The image is region-agnostic at build time; residency is
# enforced at runtime via config/settings.yaml (region pinned) and the deploy environment.

# --------------------------------------------------------------------------- #
# Builder — install dependencies into a venv we can copy into a slim runtime.
# --------------------------------------------------------------------------- #
FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4 AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential git \
 && rm -rf /var/lib/apt/lists/*

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY pyproject.toml README.md ./
COPY requirements-gcp.lock ./
COPY src ./src
COPY config ./config

RUN pip install --upgrade pip \
 && pip install -r requirements-gcp.lock && pip install --no-deps .

# --------------------------------------------------------------------------- #
# Runtime — slim, non-root, venv copied from builder.
# --------------------------------------------------------------------------- #
FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    CREDIT_MEMO_PROFILE=gcp \
    CREDIT_MEMO_SETTINGS=/app/config/settings.yaml \
    PORT=8093

WORKDIR /app

# A digest pin freezes the base image, which means it also freezes its unpatched packages.
# Reproducible and vulnerable are not opposites, and the pin quietly guarantees the second while
# being cited as evidence of the first. Without this line the promotion scan reports 30 fixable
# HIGH from the Debian base alone, most of them the util-linux family plus openssl. This image was
# pushed on 2026-09-05 outside the promotion path and was never scanned, and this is why a rebuild
# is owed rather than optional. Its sibling `compliance-advisory` adopted the same two blocks on
# 2026-09-12 and went from thirty-two findings to zero; `cdd-sow-research` has upgraded in its
# runtime stage all along, which is why its images pass the same blocking scan.
RUN apt-get update \
 && apt-get upgrade -y --no-install-recommends \
 && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 appuser

COPY --from=builder /opt/venv /opt/venv
COPY src ./src
COPY config ./config

# Remove pip from the RUNTIME image, in both the system prefix and the venv.
#
# A serving container installs nothing, so shipping a package manager in it adds an install
# capability an attacker can use and the application never can. pip also VENDORS its dependencies,
# so a scanner reports pip's bundled copies as installed packages: that is where the last two
# findings came from in the sibling, and neither was a dependency of the application nor reachable
# by any lock move, because they were never resolved. They arrived inside pip itself.
RUN rm -rf /usr/local/lib/python3.14/site-packages/pip \
           /usr/local/lib/python3.14/site-packages/pip-*.dist-info \
           /opt/venv/lib/python3.14/site-packages/pip \
           /opt/venv/lib/python3.14/site-packages/pip-*.dist-info \
           /usr/local/bin/pip /usr/local/bin/pip3 /opt/venv/bin/pip /opt/venv/bin/pip3

USER appuser
EXPOSE 8093

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8093')+'/healthz')" || exit 1

CMD exec uvicorn credit_memo.api.app:app --host 0.0.0.0 --port ${PORT}
