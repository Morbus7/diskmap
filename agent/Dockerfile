# Diskmap-agent: bare Python-standardbiblioteket
FROM python:3.12-alpine
RUN apk add --no-cache tzdata
WORKDIR /app
COPY app.py .
ENV PYTHONDONTWRITEBYTECODE=1 PORT=8787 DATA_DIR=/data
EXPOSE 8787
VOLUME /data
HEALTHCHECK --interval=60s --timeout=5s CMD python -c "import urllib.request,os; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/healthz', timeout=4)"
CMD ["python", "-u", "/app/app.py"]
