import time
import traceback
import json
import urllib.request
import urllib.error
import os
import xml.etree.ElementTree as ET
from database import get_connection
from faac_jobs import (
    build_jobs_payload,
    build_fichero_claves,
    extraer_trabajos,
)


POLL_INTERVAL_SECONDS = 5
WORKER_ID = "worker-1"
FAAC_DECRYPT_URL = os.environ["FAAC_DECRYPT_URL"]
API_KEY = os.environ["FAAC_API_KEY"]
SERVICE_FAAC_EN_CL_URL = os.environ["SERVICE_FAAC_EN_CL_URL"]
SERVICE_FAAC_NAMESPACE = os.environ["SERVICE_FAAC_NAMESPACE"]
EN_CL_TIMEOUT_SECONDS = int(os.environ.get("EN_CL_TIMEOUT_SECONDS","30",))


def call_en_cl(
    licencia,
    peticion,
    fichero_claves,
):
    soap_namespace = (
        "http://schemas.xmlsoap.org/"
        "soap/envelope/"
    )

    ET.register_namespace(
        "soap",
        soap_namespace,
    )

    envelope = ET.Element(
        f"{{{soap_namespace}}}Envelope"
    )

    body = ET.SubElement(
        envelope,
        f"{{{soap_namespace}}}Body"
    )

    metodo = ET.SubElement(
        body,
        f"{{{SERVICE_FAAC_NAMESPACE}}}EN_CL"
    )

    recibido = ET.SubElement(
        metodo,
        f"{{{SERVICE_FAAC_NAMESPACE}}}recibido"
    )

    recibido.text = (
        f"{licencia}|"
        f"{peticion}|"
        f"{fichero_claves}"
    )

    contenido = ET.tostring(
        envelope,
        encoding="utf-8",
        xml_declaration=True,
    )

    request = urllib.request.Request(
        SERVICE_FAAC_EN_CL_URL,
        data=contenido,
        method="POST",
        headers={
            "Content-Type":
                "text/xml; charset=utf-8",

            "SOAPAction":
                f'"{SERVICE_FAAC_NAMESPACE}/EN_CL"',
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=EN_CL_TIMEOUT_SECONDS,
        ) as response:
            codigo_http = response.status
            respuesta_xml = (
                response
                .read()
                .decode("utf-8")
            )

    except urllib.error.HTTPError as ex:
        try:
            detalle = (
                ex.read()
                .decode("utf-8")
            )
        except Exception:
            detalle = str(ex)

        raise RuntimeError(
            "EN_CL devolvio HTTP "
            f"{ex.code}: {detalle}"
        ) from ex

    except urllib.error.URLError as ex:
        raise RuntimeError(
            "No se pudo conectar con "
            "ServiceFaac EN_CL: "
            + str(ex.reason)
        ) from ex

    except TimeoutError as ex:
        raise RuntimeError(
            "EN_CL supero el tiempo "
            "maximo de espera"
        ) from ex

    if codigo_http < 200 or codigo_http >= 300:
        raise RuntimeError(
            f"EN_CL devolvio HTTP {codigo_http}"
        )

    try:
        root = ET.fromstring(
            respuesta_xml
        )
    except ET.ParseError as ex:
        raise RuntimeError(
            "La respuesta de EN_CL "
            "no es XML valido: "
            + respuesta_xml
        ) from ex

    resultado = None

    for elemento in root.iter():
        if elemento.tag.endswith(
            "EN_CLResult"
        ):
            resultado = (
                elemento.text or ""
            ).strip()

            break

    if resultado is None:
        raise RuntimeError(
            "La respuesta SOAP no contiene "
            "EN_CLResult: "
            + respuesta_xml
        )

    if resultado != "0":
        raise RuntimeError(
            "ServiceFaac rechazo EN_CL. "
            f"Resultado={resultado}"
        )

    return True

def call_decrypt(payload):

    body = json.dumps(
        payload
    ).encode("utf-8")

    request = urllib.request.Request(
        FAAC_DECRYPT_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": API_KEY
        },
        method="POST"
    )

    with urllib.request.urlopen(
        request
    ) as response:

        respuesta = response.read()

        return json.loads(
            respuesta.decode("utf-8")
        )

def procesar_peticion(job):
    print(
        f"[WORKER] Procesando "
        f"id={job['id']} "
        f"licencia={job['licencia']} "
        f"peticion={job['peticion']}"
    )

    fichero_peticion = job[
        "fichero_peticion"
    ]

    trabajos = extraer_trabajos(
        fichero_peticion
    )

    payload = build_jobs_payload(
        fichero_peticion
    )

    print(
        "[WORKER] Numero de botones validos: "
        f"{len(trabajos)}"
    )

    for trabajo in trabajos:
        print(
            f"[WORKER] Button{trabajo['button']} -> "
            f"{trabajo['frame0']}, "
            f"{trabajo['frame1']}, "
            f"{trabajo['frame2']}, "
            f"{trabajo['frame3']}"
        )

    print(
        "[WORKER] Payload /decrypt:"
    )

    print(
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )

    respuesta_faac = call_decrypt(
        payload
    )

    print(
        "[WORKER] Respuesta FAAC:"
    )

    print(
        json.dumps(
            respuesta_faac,
            indent=2,
            ensure_ascii=False,
        )
    )

    if respuesta_faac.get("success") is not True:
        raise RuntimeError(
            "FAAC indico que la peticion "
            "no tuvo exito: "
            + json.dumps(
                respuesta_faac,
                ensure_ascii=False,
            )
        )

    fichero_claves = build_fichero_claves(
        fichero_peticion,
        respuesta_faac,
    )

    print(
        "[WORKER] ficheroClaves generado:"
    )

    print(fichero_claves)

    save_resultado(
        job["id"],
        fichero_claves,
    )

    print(
        "[WORKER] Enviando EN_CL "
        f"para id={job['id']}"
    )

    call_en_cl(
        licencia=job["licencia"],
        peticion=job["peticion"],
        fichero_claves=fichero_claves,
    )

    mark_en_cl_confirmed(
        job["id"]
    )

    print(
        "[WORKER] EN_CL confirmado "
        f"para id={job['id']}"
    )

    return True

def recover_running_jobs():

    conn = get_connection()

    try:

        updated = conn.execute(
            """
            UPDATE jobs
            SET estado='PENDING',
                fecha_inicio=NULL,
                worker_id=NULL
            WHERE estado='RUNNING'
            """
        )

        conn.commit()

        print(
            f"[WORKER] Recuperados "
            f"{updated.rowcount} "
            f"trabajos RUNNING"
        )

    finally:

        conn.close()


def claim_next_job():

    conn = get_connection()

    try:

        row = conn.execute(
            """
            SELECT *
            FROM jobs
            WHERE estado='PENDING'
            ORDER BY id
            LIMIT 1
            """
        ).fetchone()

        if row is None:
            return None

        updated = conn.execute(
            """
            UPDATE jobs
            SET estado='RUNNING',
                fecha_inicio=CURRENT_TIMESTAMP,
                intentos=intentos + 1,
                worker_id=?
            WHERE id=?
              AND estado='PENDING'
            """,
            (
                WORKER_ID,
                row["id"]
            )
        )

        conn.commit()

        if updated.rowcount != 1:
            return None

        job = conn.execute(
            """
            SELECT *
            FROM jobs
            WHERE id=?
            """,
            (
                row["id"],
            )
        ).fetchone()

        return job

    finally:

        conn.close()


def mark_done(job_id):

    conn = get_connection()

    try:

        conn.execute(
            """
            UPDATE jobs
            SET estado='DONE',
                fecha_fin=CURRENT_TIMESTAMP
            WHERE id=?
            """,
            (
                job_id,
            )
        )

        conn.commit()

    finally:

        conn.close()


def mark_failed(job_id, error):

    conn = get_connection()

    try:

        conn.execute(
            """
            UPDATE jobs
            SET estado='FAILED',
                fecha_fin=CURRENT_TIMESTAMP,
                error=?
            WHERE id=?
            """,
            (
                error,
                job_id
            )
        )

        conn.commit()

    finally:

        conn.close()

def mark_en_cl_confirmed(
    job_id,
):
    conn = get_connection()

    try:
        updated = conn.execute(
            """
            UPDATE jobs
            SET fecha_en_cl=CURRENT_TIMESTAMP,
                error=NULL
            WHERE id=?
              AND estado='RUNNING'
              AND resultado IS NOT NULL
            """,
            (
                job_id,
            )
        )

        conn.commit()

        if updated.rowcount != 1:
            raise RuntimeError(
                "No se pudo registrar la "
                "confirmacion EN_CL para "
                f"id={job_id}"
            )

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

def save_resultado(
    job_id,
    resultado,
):
    conn = get_connection()

    try:
        updated = conn.execute(
            """
            UPDATE jobs
            SET resultado=?,
                error=NULL
            WHERE id=?
              AND estado='RUNNING'
            """,
            (
                resultado,
                job_id,
            )
        )

        conn.commit()

        if updated.rowcount != 1:
            raise RuntimeError(
                "No se pudo guardar el resultado "
                f"del trabajo id={job_id}"
            )

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

def process_job(job):

    try:

        resultado = procesar_peticion(job)

        if resultado:

            mark_done(job["id"])

            print(
                f"[WORKER] DONE "
                f"id={job['id']}"
            )

        else:

            mark_failed(
                job["id"],
                "procesar_peticion devolvio False"
            )

            print(
                f"[WORKER] FAILED "
                f"id={job['id']}"
            )

    except Exception as ex:

        mark_failed(
            job["id"],
            str(ex)
        )

        print(
            f"[WORKER] EXCEPTION "
            f"id={job['id']}"
        )

        traceback.print_exc()


def worker_loop():

    print(
        f"[WORKER] Iniciado "
        f"(poll={POLL_INTERVAL_SECONDS}s)"
    )

    recover_running_jobs()

    while True:

        try:

            job = claim_next_job()

            if job is None:

                print(
                    "[WORKER] Esperando trabajos..."
                )

                time.sleep(
                    POLL_INTERVAL_SECONDS
                )

                continue

            process_job(job)

        except Exception:

            print(
                "[WORKER] ERROR GENERAL"
            )

            traceback.print_exc()

            time.sleep(
                POLL_INTERVAL_SECONDS
            )


if __name__ == "__main__":

    worker_loop()
