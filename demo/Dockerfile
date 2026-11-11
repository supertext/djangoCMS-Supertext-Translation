# Supertext django CMS demo: django CMS 5 + djangocms-text + this package, on PostgreSQL.
# Build context is the repository root:
#   docker build -f demo/Dockerfile -t supertext-djangocms-demo .
FROM python:3.15-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY demo/requirements.txt demo/requirements.txt
RUN pip install -r demo/requirements.txt

# The package itself, from this repository
COPY pyproject.toml README.md LICENSE ./
COPY djangocms_supertext djangocms_supertext
RUN pip install .

COPY demo demo
RUN cd demo && rm -f db.sqlite3 && DJANGO_SECRET_KEY=build python manage.py collectstatic --noinput -v 0 \
 && chmod +x entrypoint.sh

EXPOSE 8000
CMD ["/app/demo/entrypoint.sh"]
