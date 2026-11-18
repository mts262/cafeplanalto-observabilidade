FROM python:3.12-alpine
# iproute2: o containerlab configura o IP com "ip"; wget/curl e bind-tools: diagnostico
RUN apk add --no-cache iproute2 curl bind-tools
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
