FROM python:3.13-slim
WORKDIR /opt/friday
COPY webhooks webhooks
ENV PYTHONPATH=/opt/friday
ENV BIND_HOST=0.0.0.0
ENV PORT=8080
EXPOSE 8080
USER nobody
CMD ["python", "-m", "webhooks"]
