# Build from app/ after placing the frontend build in app/static/:
# docker build -t rag-chat-bot .
FROM m.daocloud.io/docker.io/python:3.10-slim-bookworm AS dependencies
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /opt/venv
COPY requirements.txt /tmp/requirements.txt
RUN /opt/venv/bin/python -m pip install --no-cache-dir \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    -r /tmp/requirements.txt

FROM m.daocloud.io/docker.io/python:3.10-slim-bookworm AS runtime
ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TZ=Asia/Shanghai
WORKDIR /app
RUN sed -i \
    -e 's|http://deb.debian.org|https://mirrors.tuna.tsinghua.edu.cn|g' \
    -e 's|https://deb.debian.org|https://mirrors.tuna.tsinghua.edu.cn|g' \
    /etc/apt/sources.list.d/debian.sources \
    && apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends tzdata \
    && ln -snf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime \
    && echo "Asia/Shanghai" > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*
COPY --from=dependencies /opt/venv /opt/venv
COPY main.py requirements.txt ./
COPY .env ./.env
COPY backend/ ./backend/
COPY skills/ ./skills/
COPY static/ ./static/
# Fail early if only static/.gitkeep was uploaded without the frontend build.
RUN test -s static/index.html && mkdir -p /app/workspace
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--timeout-graceful-shutdown", "30"]
