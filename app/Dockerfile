FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY server.py index.html login.html VERSION manifest.webmanifest icon-192.png icon-512.png apple-touch-icon.png favicon.png poolside-icon.png features.js pool-math.js sw.js ./
RUN mkdir /data && chown 10001:10001 /data
USER 10001:10001
EXPOSE 8080
CMD ["python", "server.py"]
