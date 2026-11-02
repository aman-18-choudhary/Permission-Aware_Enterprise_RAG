FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /srv
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
ENV FASTEMBED_CACHE_PATH=/models
RUN useradd -m app && mkdir /models && chown -R app /srv /models
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
