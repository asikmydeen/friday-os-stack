FROM python:3.13-slim
WORKDIR /opt/friday
COPY doors doors
COPY runtime runtime
ENV PYTHONPATH=/opt/friday
ENV BIND_HOST=0.0.0.0
ENV PORT=8080
ENV DOOR_ENABLED=no
EXPOSE 8080
USER nobody
CMD ["python", "-m", "doors"]
