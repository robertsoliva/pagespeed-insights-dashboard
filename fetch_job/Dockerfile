FROM python:3.12-slim

WORKDIR /app

COPY fetch_job/requirements.txt ./fetch_job/requirements.txt
RUN pip install --no-cache-dir -r fetch_job/requirements.txt

COPY common ./common
COPY fetch_job ./fetch_job

ENTRYPOINT ["python", "-m", "fetch_job.main"]
