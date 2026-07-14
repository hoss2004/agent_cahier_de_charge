FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PORT=7860
ENV REQBOT_HOST=0.0.0.0
ENV REQBOT_OUTPUT_DIR=/tmp/reqbot_outputs
ENV REQBOT_UPLOAD_DIR=/tmp/reqbot_uploads
ENV LLM_PROVIDER=local
ENV MOCK_LLM=true
ENV AGENT2_VALIDATION_USE_LLM=false
ENV AGENT3_USE_LLM=false
ENV MAX_TOKENS=2048
ENV OLLAMA_TIMEOUT=45
ENV GEMINI_TIMEOUT=45

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 7860

CMD ["python", "-B", "app.py"]
