FROM python:3.13-slim
WORKDIR /opt/friday
COPY browser browser
COPY netpolicy netpolicy
COPY runtime runtime
ENV PYTHONPATH=/opt/friday
ENV BIND_HOST=0.0.0.0
ENV PORT=8080
ENV BROWSER_ENABLED=no
EXPOSE 8080
USER nobody
CMD ["python", "-m", "browser"]
