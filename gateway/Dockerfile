FROM python:3.13-slim
WORKDIR /opt/friday
COPY gateway gateway
COPY netpolicy netpolicy
ENV PYTHONPATH=/opt/friday
ENV BIND_HOST=0.0.0.0
ENV PORT=8090
ENV WIRES_DIR=/wires
EXPOSE 8090
USER nobody
CMD ["python", "-m", "gateway"]
