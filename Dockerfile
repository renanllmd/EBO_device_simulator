FROM python:3.11-slim

WORKDIR /app

COPY . /app

RUN pip install --no-cache-dir \
    pymodbus==2.5.3 \
    flask \
    PyYAML \
    openpyxl\
    reportlab\
    requests
    

EXPOSE 502
EXPOSE 5502

CMD ["python", "server.py"]