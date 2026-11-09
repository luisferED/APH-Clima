FROM python:3.13-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 DB_PATH=/data/tiempo_aph.db HOST=0.0.0.0
WORKDIR /app
RUN groupadd --gid 10001 aph && useradd --uid 10001 --gid aph --no-create-home aph && mkdir -p /data /app/assets/fonts && chown aph:aph /data
COPY server.py graphics.py app.js index.html output.html styles.css graphics.css fonts.css ./
COPY scripts ./scripts
USER 10001:10001
EXPOSE 9010
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9010/healthz',timeout=3).read()"]
CMD ["python", "-u", "server.py"]
