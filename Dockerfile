FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install system python + PyQt5 + matplotlib + requests (all matching)
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pyqt5 \
    python3-matplotlib \
    python3-requests \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY stocks.py /app/stocks.py

CMD ["/usr/bin/python3", "/app/stocks.py"]
