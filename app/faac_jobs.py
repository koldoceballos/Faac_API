import json
import re
from typing import Any


TRAMA_VACIA = "FFFFFFFFFFFFFFFF"
SEPARADOR = "-" * 89
NEWLINE = "\r\n"


class FaacJobsError(ValueError):
    """Error al validar o transformar una peticion FAAC."""


def tokenizar_fichero_peticion(fichero_peticion: str) -> list[str]:
    """Separa la peticion por espacios, saltos de linea o tabuladores."""
    if fichero_peticion is None or not fichero_peticion.strip():
        raise FaacJobsError("La peticion recibida esta vacia")

    return re.split(r"\s+", fichero_peticion.strip())


def extraer_cabecera(fichero_peticion: str) -> str:
    """Devuelve 'Licencia:... Peticion:...' usando los dos primeros tokens."""
    tokens = tokenizar_fichero_peticion(fichero_peticion)

    if len(tokens) < 2:
        raise FaacJobsError("La peticion no contiene una cabecera valida")

    return f"{tokens[0]} {tokens[1]}"


def extraer_numero_boton(token: str) -> int:
    """Extrae N de un token ButtonN."""
    coincidencia = re.fullmatch(r"Button([0-9]+)", token, re.IGNORECASE)

    if coincidencia is None:
        raise FaacJobsError(f"Numero de boton incorrecto: {token}")

    return int(coincidencia.group(1))


def validar_trama(trama: str, numero_boton: int, numero_trama: int) -> str:
    """Valida una trama de 16 digitos hexadecimales y la normaliza a mayusculas."""
    trama = trama.strip().upper()

    if re.fullmatch(r"[0-9A-F]{16}", trama) is None:
        raise FaacJobsError(
            f"Button{numero_boton}: la trama {numero_trama} "
            "no contiene 16 digitos hexadecimales"
        )

    return trama


def extraer_trabajos(fichero_peticion: str) -> list[dict[str, Any]]:
    """
    Replica la validacion funcional de TEST_FICHERO_CLAVES y la conversion
    de TEST_JOBS.

    Los botones con cuatro tramas FFFFFFFFFFFFFFFF se ignoran. Una mezcla
    de tramas reales y vacias provoca error. Los cuatro frames hopping de
    un boton valido deben ser distintos.
    """
    tokens = tokenizar_fichero_peticion(fichero_peticion)
    trabajos: list[dict[str, Any]] = []

    for indice, token in enumerate(tokens):
        if not token.lower().startswith("button"):
            continue

        if indice + 4 >= len(tokens):
            raise FaacJobsError(f"{token} no contiene cuatro tramas")

        numero_boton = extraer_numero_boton(token)
        tramas = [
            validar_trama(tokens[indice + desplazamiento], numero_boton, desplazamiento)
            for desplazamiento in range(1, 5)
        ]

        numero_tramas_vacias = sum(trama == TRAMA_VACIA for trama in tramas)

        if numero_tramas_vacias == 4:
            continue

        if numero_tramas_vacias > 0:
            raise FaacJobsError(
                f"Button{numero_boton} mezcla tramas reales y {TRAMA_VACIA}"
            )

        frames = [trama[8:16] for trama in tramas]

        if len(set(frames)) != 4:
            raise FaacJobsError(
                f"Button{numero_boton}: las cuatro tramas deben ser distintas"
            )

        trabajos.append(
            {
                "button": numero_boton,
                "tramas_originales": tramas,
                "trama_original": tramas[0],
                "frame0": frames[0],
                "frame1": frames[1],
                "frame2": frames[2],
                "frame3": frames[3],
            }
        )

    if not trabajos:
        raise FaacJobsError("La peticion no contiene botones con tramas validas")

    return trabajos


def build_jobs_payload(fichero_peticion: str) -> dict[str, list[dict[str, str]]]:
    """Genera el objeto Python equivalente al JSON producido por TEST_JOBS."""
    trabajos = extraer_trabajos(fichero_peticion)

    return {
        "jobs": [
            {
                "frame0": trabajo["frame0"],
                "frame1": trabajo["frame1"],
                "frame2": trabajo["frame2"],
                "frame3": trabajo["frame3"],
            }
            for trabajo in trabajos
        ]
    }


def build_jobs_json(fichero_peticion: str) -> str:
    """Genera el JSON compacto equivalente a TEST_JOBS."""
    return json.dumps(
        build_jobs_payload(fichero_peticion),
        ensure_ascii=False,
        separators=(",", ":"),
    )


def normalizar_respuesta_faac(respuesta_faac: str | dict[str, Any]) -> dict[str, Any]:
    """Convierte la respuesta de FAAC en un diccionario validado."""
    if isinstance(respuesta_faac, str):
        try:
            respuesta = json.loads(respuesta_faac)
        except json.JSONDecodeError as exc:
            raise FaacJobsError(f"La respuesta FAAC no es JSON valido: {exc}") from exc
    elif isinstance(respuesta_faac, dict):
        respuesta = respuesta_faac
    else:
        raise FaacJobsError("La respuesta FAAC debe ser un texto JSON o un diccionario")

    if respuesta.get("success") is not True:
        raise FaacJobsError("FAAC indico que la peticion no tuvo exito")

    return respuesta


def extraer_resultados_faac(
    respuesta_faac: str | dict[str, Any],
    numero_trabajos: int,
) -> list[dict[str, Any]]:
    """
    Extrae y valida los resultados de FAAC conservando el orden de los jobs.

    Acepta como lista principal las claves 'jobs' o 'results'. Si solo hay
    un resultado y viene directamente en la raiz, tambien se admite.
    """
    respuesta = normalizar_respuesta_faac(respuesta_faac)

    resultados = respuesta.get("jobs")
    if resultados is None:
        resultados = respuesta.get("results")

    if resultados is None and "found" in respuesta:
        resultados = [respuesta]

    if not isinstance(resultados, list):
        raise FaacJobsError("FAAC no devolvio una lista de resultados")

    if len(resultados) != numero_trabajos:
        raise FaacJobsError("FAAC no devolvio un resultado para todos los botones")

    resultados_validados: list[dict[str, Any]] = []

    for posicion, resultado in enumerate(resultados, start=1):
        if not isinstance(resultado, dict):
            raise FaacJobsError(f"El resultado FAAC {posicion} no es un objeto")

        if resultado.get("found") is not True:
            raise FaacJobsError("FAAC no encontro una clave para todos los botones")

        clave = resultado.get("encrypted_key")
        if not isinstance(clave, str):
            raise FaacJobsError("FAAC no devolvio una clave cifrada para todos los botones")

        coincidencia = re.fullmatch(r"0x([0-9A-Fa-f]{8})", clave)
        if coincidencia is None:
            raise FaacJobsError(
                f"Clave cifrada incorrecta en el resultado {posicion}: {clave!r}"
            )

        resultado_copia = dict(resultado)
        resultado_copia["encrypted_key_normalized"] = coincidencia.group(1).upper()
        resultados_validados.append(resultado_copia)

    return resultados_validados


def build_fichero_claves(
    fichero_peticion: str,
    respuesta_faac: str | dict[str, Any],
) -> str:
    """
    Genera el texto equivalente a TEST_FICHERO_CLAVES a partir de la
    peticion original y de la respuesta JSON de FAAC.
    """
    cabecera = extraer_cabecera(fichero_peticion)
    trabajos = extraer_trabajos(fichero_peticion)
    resultados = extraer_resultados_faac(respuesta_faac, len(trabajos))

    lineas: list[str] = [cabecera]

    for trabajo, resultado in zip(trabajos, resultados):
        trama_original = trabajo["trama_original"]
        serial_fijo = trama_original[0:2]
        serial = int(trama_original[2:6], 16)
        semilla = resultado["encrypted_key_normalized"]

        lineas.extend(
            [
                SEPARADOR,
                f"Boton {trabajo['button']}",
                f"Trama original: {trama_original}",
                f"Serial Fijo: {serial_fijo}",
                (
                    f"Serial: {serial} "
                    "(Sume o reste varios numeros para no hacer un clon)"
                ),
                "Personalizacion: 35860",
                "Contador: 0 (Puede introducir otro valor si lo desea)",
                f"Semilla: {semilla}",
            ]
        )

    return NEWLINE.join(lineas) + NEWLINE


def mostrar_resumen(fichero_peticion: str) -> None:
    """Muestra los botones y el JSON generado. Se usa solo para pruebas."""
    trabajos = extraer_trabajos(fichero_peticion)
    print(f"[FAAC_JOBS] Trabajos validos: {len(trabajos)}")

    for trabajo in trabajos:
        print(
            f"[FAAC_JOBS] Button{trabajo['button']} -> "
            f"{trabajo['frame0']}, {trabajo['frame1']}, "
            f"{trabajo['frame2']}, {trabajo['frame3']}"
        )

    print(f"[FAAC_JOBS] JSON: {build_jobs_json(fichero_peticion)}")
