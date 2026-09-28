# The Business Reports web app on a free Hugging Face Space (no card needed).
# Copy this file into your Space as "Dockerfile" (see README.md in the project, "Put it online for free").
# It downloads the app from GitHub, so "Factory rebuild" in the Space's settings brings in the latest version.
FROM python:3.12-slim
RUN useradd -m -u 1000 user
USER user
ENV HOME=/home/user PATH=/home/user/.local/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/tmp/app-data PORT=7860 SECURE_COOKIES=1
WORKDIR /home/user/app
ARG REPO=THE-AAV/EXCEL_PROJECT
ARG BRANCH=claude/excel-debtor-creditor-pl-reports-o0o0zm
RUN python - <<'PY'
import io, os, tarfile, urllib.request
url = f"https://codeload.github.com/{os.environ['REPO']}/tar.gz/refs/heads/{os.environ['BRANCH']}"
with tarfile.open(fileobj=io.BytesIO(urllib.request.urlopen(url, timeout=120).read())) as t:
    for m in t.getmembers():
        m.name = m.name.split("/", 1)[1] if "/" in m.name else ""
        if m.name and (m.isfile() or m.isdir()):
            t.extract(m, ".", filter="data")
PY
RUN pip install --no-cache-dir --user -r requirements-server.txt
EXPOSE 7860
CMD ["sh", "-c", "exec uvicorn server.main:create_app --factory --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
