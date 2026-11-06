FROM python:3.12-slim
WORKDIR /sim
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY simulate.py .
CMD ["python", "-u", "simulate.py"]
