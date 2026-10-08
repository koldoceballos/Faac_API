from fastapi import FastAPI
from pydantic import BaseModel
from fastapi import Header, HTTPException
import tempfile
import subprocess
import json
import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
from fastapi import HTTPException

API_KEY = os.environ["FAAC_API_KEY"]

app = FastAPI()

# ==========================================================
# Logging
# ==========================================================

LOG_DIR = Path("/home/koldo/faac-api/logs")
LOG_DIR.mkdir(exist_ok=True)

handler = RotatingFileHandler(
    LOG_DIR / "faac.log",
    maxBytes=5 * 1024 * 1024,  # 10 MB
    backupCount=10
)

handler.setFormatter(
    logging.Formatter(
        "%(asctime)s | %(levelname)s | %(message)s"
    )
)

logger = logging.getLogger("faac")

logger.setLevel(logging.INFO)

logger.handlers.clear()
logger.addHandler(handler)

logger.propagate = False

logger.info("FAAC API arrancada")

# ==========================================================
# Jobs
# ==========================================================

class Job(BaseModel):
    frame0: str
    frame1: str
    frame2: str
    frame3: str


class DecryptRequest(BaseModel):
    jobs: list[Job]


def check_api_key(x_api_key: str = Header(default="")):

    if x_api_key != API_KEY:
        raise HTTPException(
            status_code=401,
            detail="Unauthorized"
        )

HEX8_RE = re.compile(r"^[0-9A-Fa-f]{8}$")


def validate_job(job: Job):

    frames = [
        job.frame0,
        job.frame1,
        job.frame2,
        job.frame3
    ]

    for idx, frame in enumerate(frames):

        if not HEX8_RE.fullmatch(frame):

            raise HTTPException(
                status_code=400,
                detail=f"frame{idx} debe contener exactamente 8 caracteres hexadecimales"
            )

    if len(set(frames)) != 4:

        raise HTTPException(
            status_code=400,
            detail="Las cuatro tramas deben ser distintas"
        )

@app.get("/health")
def health():

    return {
        "status": "ok",
        "service": "faac-api"
    }


@app.post("/decrypt")
def decrypt(
    request: DecryptRequest,
    x_api_key: str = Header(default="")
):    
    check_api_key(x_api_key)
    for job in request.jobs:
        validate_job(job)
    logger.info(
        "Decrypt request received (%d jobs)",
        len(request.jobs)
    )
    for idx, job in enumerate(request.jobs):

        logger.info(
            "REQUEST job=%d frame0=%s frame1=%s frame2=%s frame3=%s",
            idx,
            job.frame0,
            job.frame1,
            job.frame2,
            job.frame3
        )
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

    logger.info(
        "Temporary jobs file created: %s",
        jobs_file
    )

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
        logger.info(
            "Script finished rc=%d",
            result.returncode
        )

    finally:
        if os.path.exists(jobs_file):    
            os.unlink(jobs_file)
    
    if result.returncode != 0:
        logger.error(
            "Decrypt failed: %s",
            result.stderr.strip()
        )

        return {
            "status": "error",
            "stderr": result.stderr,
            "stdout": result.stdout
        }

    logger.info(
        "Decrypt completed successfully"
    )
    response = json.loads(result.stdout)
    
    total_elapsed = round(time.time() - start_time, 2)

    logger.info(
        "Request completed in %.2fs",
        total_elapsed
    )
    for job in response.get("jobs", []):

        logger.info(
            "RESULT found=%s key=%s elapsed_s=%s status=%s",
            job.get("found"),
            job.get("encrypted_key"),
            job.get("elapsed_s"),
            job.get("status")
        )
    return response

