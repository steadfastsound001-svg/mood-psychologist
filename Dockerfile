FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py store.py onboarding.py llm.py agent_core.py stt.py ./
COPY webapp ./webapp

# persistent SQLite живёт здесь (Fly volume монтируется в /app/data)
RUN mkdir -p /app/data

ENV PORT=8080
EXPOSE 8080

CMD ["python", "server.py"]
