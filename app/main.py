from fastapi import FastAPI
from pydantic import BaseModel
import subprocess

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

    return {
        "status": "accepted",
        "jobs_received": len(request.jobs)
    }


@app.get("/test-script")
def test_script():

    result = subprocess.run(
        [
            "/home/koldo/faac-api/scripts/invoke_keeloq_f2.sh",
            "--help"
        ],
        capture_output=True,
        text=True
    )

    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr
    }
