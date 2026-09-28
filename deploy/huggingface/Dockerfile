# The Business Reports web app on a free Hugging Face Space (no card needed).
# Copy this file into your Space as "Dockerfile" (see README.md in the project, "Put it online for free").
# It downloads the app from GitHub, so "Factory rebuild" in the Space's settings brings in the latest version.
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates && rm -rf /var/lib/apt/lists/*
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/tmp/app-data PORT=7860 SECURE_COOKIES=1
WORKDIR /home/user/app
ARG REPO=THE-AAV/EXCEL_PROJECT
ARG BRANCH=claude/excel-debtor-creditor-pl-reports-o0o0zm
# changes whenever the branch gets a new commit, so a rebuild always fetches the newest code
ADD https://api.github.com/repos/${REPO}/commits/${BRANCH} /tmp/latest-commit.json
RUN git clone --depth 1 --branch ${BRANCH} https://github.com/${REPO}.git . \
 && pip install --no-cache-dir --user -r requirements-server.txt
EXPOSE 7860
CMD ["sh", "-c", "exec uvicorn server.main:create_app --factory --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
