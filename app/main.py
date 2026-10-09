from fastapi import FastAPI
from pydantic import BaseModel
from fastapi import Header, HTTPException
import tempfile
import time
import subprocess
import json
import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import re
from fastapi import HTTPException

from app.database import (
    initialize_database,
    get_connection
)

from app.schemas import (
    EnqueueRequest,
    EnqueueResponse
)



APP_ROOT = Path(os.environ["FAAC_APP_ROOT"])
SCRIPT_PATH = APP_ROOT / "scripts" / "invoke_keeloq_f2.sh"
LOG_DIR = APP_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

API_KEY = os.environ["FAAC_API_KEY"]

app = FastAPI(
    title="FAAC API",
    version="1.0"
)


# ==========================================================
# Logging
# ==========================================================


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


@app.on_event("startup")
def startup():

    initialize_database()


@app.get("/")
def root():

    return {
        "service": "FAAC API",
        "status": "running"
    }


import sqlite3

@app.post(
    "/enqueue",
    response_model=EnqueueResponse,
    status_code=201
)
def enqueue_job(req: EnqueueRequest):

    licencia = req.licencia.strip().upper()

    conn = get_connection()

    try:

        existente = conn.execute(
            """
            SELECT
                id,
                fichero_peticion,
                estado
            FROM jobs
            WHERE licencia = ?
            AND peticion = ?
            """,
            (
                licencia,
                req.peticion
            )
        ).fetchone()

        #
        # YA EXISTE
        #
        if existente is not None:

            if (
                existente["fichero_peticion"] !=
                req.fichero_peticion
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Existe una peticion con la misma "
                        "licencia y numero de peticion "
                        "pero distinto contenido"
                    )
                )

            return EnqueueResponse(
                success=True,
                id=existente["id"],
                estado=existente["estado"]
            )

        #
        # NUEVO REGISTRO
        #
        cur = conn.execute(
            """
            INSERT INTO jobs
            (
                licencia,
                peticion,
                fichero_peticion,
                estado
            )
            VALUES
            (
                ?, ?, ?, ?
            )
            """,
            (
                licencia,
                req.peticion,
                req.fichero_peticion,
                "PENDING"
            )
        )

        conn.commit()

        return EnqueueResponse(
            success=True,
            id=cur.lastrowid,
            estado="PENDING"
        )

    except HTTPException:

        conn.rollback()
        raise

    except sqlite3.IntegrityError:

        conn.rollback()

        existente = conn.execute(
            """
            SELECT
                id,
                fichero_peticion,
                estado
            FROM jobs
            WHERE licencia = ?
            AND peticion = ?
            """,
            (
                licencia,
                req.peticion
            )
        ).fetchone()

        if (
            existente is not None and
            existente["fichero_peticion"] ==
            req.fichero_peticion
        ):
            return EnqueueResponse(
                success=True,
                id=existente["id"],
                estado=existente["estado"]
            )

        raise HTTPException(
            status_code=409,
            detail="Conflicto de peticion"
        )

    except Exception as ex:

        conn.rollback()

        raise HTTPException(
            status_code=500,
            detail=str(ex)
        )

    finally:

        conn.close()

@app.post("/decrypt")
def decrypt(
    request: DecryptRequest,
    x_api_key: str = Header(default="")
):    
    check_api_key(x_api_key)

    start_time = time.time()

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
                str(SCRIPT_PATH),
                "--jobs-file",
                jobs_file
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

