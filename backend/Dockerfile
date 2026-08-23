FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends netcat-openbsd fonts-dejavu-core poppler-utils \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# ponytail: 777 so TrueNAS non-root (e.g. uid 568) can write; collectstatic at build so runtime need not create the tree
RUN mkdir -p /app/staticfiles /app/media \
    && chmod 777 /app/staticfiles /app/media \
    && chmod +x entrypoint.sh \
    && DJANGO_DB_ENGINE=sqlite DJANGO_SECRET_KEY=build python manage.py collectstatic --noinput

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
