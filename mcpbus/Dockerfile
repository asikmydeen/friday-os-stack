FROM python:3.13-slim
WORKDIR /opt/friday
COPY mcpbus mcpbus
COPY netpolicy netpolicy
COPY runtime runtime
ENV PYTHONPATH=/opt/friday
ENV BIND_HOST=0.0.0.0
ENV PORT=8080
ENV MCP_ENABLED=no
ENV OUTBOUND_ENABLED=no
EXPOSE 8080
USER nobody
CMD ["python", "-m", "mcpbus"]
