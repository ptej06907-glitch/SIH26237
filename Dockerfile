FROM node:24-slim AS web
WORKDIR /app/apps/web
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
ENV NEXT_TELEMETRY_DISABLED=1
ENV SOURCEX_WEB_EXPORT=1
ENV NEXT_PUBLIC_API_URL=/api
RUN npm run build

FROM python:3.14-slim
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY services/api ./services/api
COPY --from=web /app/apps/web/out ./apps/web/out
ENV PYTHONPATH=/app/services/api
ENV SOURCEX_HOSTED=1
ENV SIH_DATA_DIR=/app/data
EXPOSE 10000
CMD ["sh", "-c", "exec uvicorn provenance.hosted:app --host 0.0.0.0 --port ${PORT:-10000} --workers 1"]
