FROM python:3.13-slim
WORKDIR /opt/friday
COPY friday friday
COPY memoryd memoryd
COPY runtime runtime
COPY gate gate
COPY image image
COPY charters /soul/agents
COPY soul/SOUL.example.md /soul/SOUL.md
ENV PYTHONPATH=/opt/friday
ENV CHARTERS_DIR=/soul/agents
ENV SOUL_PATH=/soul/SOUL.md
ENV BIND_HOST=0.0.0.0
ENV PORT=8080
EXPOSE 8080
USER nobody
CMD ["python", "-m", "friday"]
