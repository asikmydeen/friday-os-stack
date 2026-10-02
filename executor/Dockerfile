FROM python:3.13-slim
WORKDIR /opt/friday
COPY executor executor
COPY gate gate
COPY backup backup
COPY catalog catalog
COPY memoryd memoryd
COPY runtime runtime
COPY sql/backup.sql sql/backup.sql
COPY sql/approvals.sql sql/approvals.sql
RUN pip install --no-cache-dir "psycopg[binary]==3.2.9"
ENV PYTHONPATH=/opt/friday
ENV BIND_HOST=0.0.0.0
ENV PORT=8080
ENV STORE_PATH=/data/gate.json
RUN mkdir -p /data && chown nobody:nogroup /data
EXPOSE 8080
USER nobody
CMD ["python", "-m", "executor"]
