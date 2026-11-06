FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py ted_client.py ted_details.py tax_engine.py tax_v04.py ./
COPY static ./static
RUN addgroup --system tendercore && adduser --system --ingroup tendercore tendercore \
    && mkdir -p /app/data && chown tendercore:tendercore /app/data
USER tendercore
EXPOSE 8766
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8766"]
