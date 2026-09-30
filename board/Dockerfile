FROM node:24-alpine
WORKDIR /opt/board
COPY board/server.js server.js
ENV BIND_HOST=0.0.0.0
ENV PORT=8080
EXPOSE 8080
USER node
CMD ["node", "server.js"]
