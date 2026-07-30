FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
# --timeout/--retries: PyPI с раннеров Render периодически отваливается по read timeout
RUN pip install --no-cache-dir --timeout 60 --retries 10 -r requirements.txt

# Копируем ВСЕ модули, а не список поимённо. Список ломался молча: появились
# psyconfig и safety — в образ не попали, деплой падал на ModuleNotFoundError и
# откатывался на старую версию. Лишний bot.py в образе дешевле, чем выкатка,
# которая не доезжает.
COPY *.py ./
# личность психолога: слои, промпты, фильтры, лексикон риска, телефоны
COPY config ./config
COPY webapp ./webapp

# persistent SQLite живёт здесь (Fly volume монтируется в /app/data)
RUN mkdir -p /app/data

ENV PORT=8080
EXPOSE 8080

CMD ["python", "server.py"]
