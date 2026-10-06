from fastapi import FastAPI
from pydantic import BaseModel
import tempfile
import subprocess
import json
import os

app = FastAPI()


class Job(BaseModel):
    frame0: str
    frame1: str
    frame2: str
    frame3: str


class DecryptRequest(BaseModel):
    jobs: list[Job]


@app.get("/health")
def health():

    return {
        "status": "ok",
        "service": "faac-api"
    }


@app.post("/decrypt")
def decrypt(request: DecryptRequest):

    payload = {
        "jobs": [
            {
                **job.model_dump(),
            	"start": "00000000",
            	"end": "FFFFFFFF"
            }
            for job in request.jobs
    	]
    }

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        delete=False
    ) as f:

        json.dump(payload, f)

        jobs_file = f.name

    try:
        result = subprocess.run(
            [
                "/home/koldo/faac-api/scripts/invoke_keeloq_f2.sh",
                "--jobs-file",
                jobs_file,
                "--leave-running"
            ],
            capture_output=True,
            text=True
        )
    finally:
        if os.path.exists(jobs_file):    
            os.unlink(jobs_file)
    
    if result.returncode != 0:

        return {
            "status": "error",
            "stderr": result.stderr,
            "stdout": result.stdout
        }

    return json.loads(result.stdout)

