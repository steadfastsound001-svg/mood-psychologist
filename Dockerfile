FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
# --timeout/--retries: PyPI с раннеров Render периодически отваливается по read timeout
RUN pip install --no-cache-dir --timeout 60 --retries 10 -r requirements.txt

COPY server.py store.py onboarding.py llm.py agent_core.py agent_config.py stt.py ./
COPY SOUL.md ./
COPY webapp ./webapp

# persistent SQLite живёт здесь (Fly volume монтируется в /app/data)
RUN mkdir -p /app/data

ENV PORT=8080
EXPOSE 8080

CMD ["python", "server.py"]
