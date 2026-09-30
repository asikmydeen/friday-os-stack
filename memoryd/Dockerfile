FROM python:3.13-slim
WORKDIR /opt/friday
COPY memoryd memoryd
COPY runtime runtime
ENV PYTHONPATH=/opt/friday
ENV BIND_HOST=0.0.0.0
ENV PORT=8080
ENV NOTES_PATH=/data/notes.json
RUN mkdir -p /data && chown nobody:nogroup /data
EXPOSE 8080
USER nobody
CMD ["python", "-m", "memoryd"]
