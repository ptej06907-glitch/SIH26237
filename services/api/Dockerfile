FROM python:3.14-slim
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY services/api /app/services/api
ENV PYTHONPATH=/app/services/api
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "provenance.app:app", "--host", "0.0.0.0", "--port", "8000"]
