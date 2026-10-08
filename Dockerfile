FROM python:3.12-slim

WORKDIR /app

ENV AWS_PAGER=""

COPY requirements.txt .

RUN apt-get update && \
    apt-get install -y \
        curl \
        unzip \
        jq && \
    rm -rf /var/lib/apt/lists/*

RUN curl "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" \
    -o "/tmp/awscliv2.zip" && \
    unzip /tmp/awscliv2.zip -d /tmp && \
    /tmp/aws/install && \
    rm -rf /tmp/aws /tmp/awscliv2.zip

RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY scripts ./scripts
COPY deployment ./deployment

RUN chmod +x ./scripts/invoke_keeloq_f2.sh

EXPOSE 8010

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8010"]
