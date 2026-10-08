#!/usr/bin/env bash

set -Eeuo pipefail
trap 'echo "ERR linea=$LINENO rc=$?" >&2' ERR

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

SECRET_FILE="${SCRIPT_DIR}/keeloq_secret.env"

if [ -f "$SECRET_FILE" ]; then
    . "$SECRET_FILE"
fi

: "${KEELOQ_MASTER_KEY_HEX:?No se ha definido KEELOQ_MASTER_KEY_HEX}"

MASTER_KEY_HEX="$KEELOQ_MASTER_KEY_HEX"
INSTANCE_ID="${INSTANCE_ID:?No se ha definido INSTANCE_ID}"
REGION="${AWS_REGION:?No se ha definido AWS_REGION}"
REMOTE_SCRIPT="${REMOTE_SCRIPT:?No se ha definido REMOTE_SCRIPT}"
WORKER_TIMEOUT="${WORKER_TIMEOUT:?No se ha definido WORKER_TIMEOUT}"
STARTUP_TIMEOUT="${STARTUP_TIMEOUT:?No se ha definido STARTUP_TIMEOUT}"
POLL_SECONDS="${POLL_SECONDS:?No se ha definido POLL_SECONDS}"
JOBS_FILE=""
LEAVE_RUNNING=0
FORCE_STOP=0
STARTED_BY_CONTROLLER=0
COMMAND_ID=""
TMP_DIR=""

log() {
    printf '%s\n' "$*" >&2
}

fail() {
    log "ERROR: $*"
    exit 1
}

usage() {
    cat <<'USAGE'
Uso:
  invoke_keeloq_f2.sh --jobs-file jobs.json [opciones]

Opciones:
  --jobs-file RUTA           JSON con entre 1 y 4 trabajos.
  --instance-id ID           Instance ID de EC2.
  --region REGION            Region AWS.
  --remote-script RUTA       Script remoto ejecutado mediante SSM.
  --worker-timeout SEGUNDOS  Timeout de cada trabajo KeeLoq.
  --startup-timeout SEGUNDOS Timeout para arranque de EC2 y SSM.
  --poll-seconds SEGUNDOS    Intervalo de consulta.
  --leave-running            No detener la instancia al finalizar.
  --force-stop               Detener al finalizar aunque ya estuviera encendida.
  -h, --help                 Mostrar esta ayuda.

Formato de jobs.json:
{
  "jobs": [
    {
      "frame0": "A98665A3",
      "frame1": "49A4F8F6",
      "frame2": "D184382D",
      "frame3": "42332318",
      "start":  "18001000",
      "end":    "18001040"
    }
  ]
}

La salida normal es exclusivamente el JSON devuelto por keeloq_worker.
Los mensajes de progreso se escriben en stderr.
USAGE
}

is_positive_integer() {
    [[ "$1" =~ ^[1-9][0-9]*$ ]]
}

while (($# > 0)); do
    case "$1" in
        --jobs-file)
            (($# >= 2)) || fail "Falta la ruta despues de --jobs-file."
            JOBS_FILE="$2"
            shift 2
            ;;
        --instance-id)
            (($# >= 2)) || fail "Falta el valor despues de --instance-id."
            INSTANCE_ID="$2"
            shift 2
            ;;
        --region)
            (($# >= 2)) || fail "Falta el valor despues de --region."
            REGION="$2"
            shift 2
            ;;
        --remote-script)
            (($# >= 2)) || fail "Falta el valor despues de --remote-script."
            REMOTE_SCRIPT="$2"
            shift 2
            ;;
        --worker-timeout)
            (($# >= 2)) || fail "Falta el valor despues de --worker-timeout."
            is_positive_integer "$2" || fail "worker-timeout debe ser un entero positivo."
            WORKER_TIMEOUT="$2"
            shift 2
            ;;
        --startup-timeout)
            (($# >= 2)) || fail "Falta el valor despues de --startup-timeout."
            is_positive_integer "$2" || fail "startup-timeout debe ser un entero positivo."
            STARTUP_TIMEOUT="$2"
            shift 2
            ;;
        --poll-seconds)
            (($# >= 2)) || fail "Falta el valor despues de --poll-seconds."
            is_positive_integer "$2" || fail "poll-seconds debe ser un entero positivo."
            POLL_SECONDS="$2"
            shift 2
            ;;
        --leave-running)
            LEAVE_RUNNING=1
            shift
            ;;
        --force-stop)
            FORCE_STOP=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            fail "Argumento desconocido: $1"
            ;;
    esac
done

command -v aws >/dev/null 2>&1 || fail "AWS CLI no esta instalado o no esta en PATH."
command -v jq >/dev/null 2>&1 || fail "jq no esta instalado o no esta en PATH."
[[ -n "$JOBS_FILE" ]] || fail "Debes indicar --jobs-file."
[[ -r "$JOBS_FILE" ]] || fail "No se puede leer el fichero: $JOBS_FILE"
((LEAVE_RUNNING == 0 || FORCE_STOP == 0)) || fail "No combines --leave-running y --force-stop."

JQ_JOB_FILTER='def hex8: type == "string" and test("^[0-9A-Fa-f]{8}$");
.jobs | type == "array" and length >= 1 and length <= 4 and
all(.[];
    (.frame0 | hex8) and
    (.frame1 | hex8) and
    (.frame2 | hex8) and
    (.frame3 | hex8) and
    (.start  | hex8) and
    (.end    | hex8)
)'

jq -e "$JQ_JOB_FILTER" "$JOBS_FILE" >/dev/null \
    || fail "jobs.json debe contener entre 1 y 4 trabajos con seis campos hexadecimales de 8 digitos."

while IFS= read -r worker_job; do

    worker_job="$(printf "%s" "$worker_job" | tr -d '\r')"

    REMOTE_COMMAND+=" --job '$worker_job'"

done < <(
jq -r '
.jobs[] |
[
.frame0,
.frame1,
.frame2,
.frame3,
.start,
.end
] |
map(ascii_upcase) |
join(",")
' "$JOBS_FILE" | tr -d '\r'
)

TMP_DIR="$(mktemp -d -t keeloq-controller.XXXXXX)"

cleanup() {
    local exit_code=$?
    local should_stop=0

    if ((FORCE_STOP == 1)); then
        should_stop=1
    elif ((STARTED_BY_CONTROLLER == 1 && LEAVE_RUNNING == 0)); then
        should_stop=1
    fi

    if ((should_stop == 1)); then
        log "Deteniendo instancia $INSTANCE_ID..."
        if aws ec2 stop-instances \
            --region "$REGION" \
            --instance-ids "$INSTANCE_ID" \
            --output json >/dev/null; then
            log "Orden de parada enviada."
        else
            log "WARNING: no se pudo enviar la orden de parada."
        fi
    elif ((LEAVE_RUNNING == 1)); then
        log "La instancia queda encendida por --leave-running."
    elif ((STARTED_BY_CONTROLLER == 0)); then
        log "La instancia ya estaba encendida; no se detiene automaticamente."
    fi

    [[ -z "$TMP_DIR" ]] || rm -rf "$TMP_DIR"
    exit "$exit_code"
}
trap 'echo "ERROR EN LINEA $LINENO" >&2' ERR
trap cleanup EXIT

get_instance_state() {
    aws ec2 describe-instances \
        --region "$REGION" \
        --instance-ids "$INSTANCE_ID" \
        --query 'Reservations[0].Instances[0].State.Name' \
        --output text
}

ssm_is_online() {
    local ping_status

    ping_status="$(aws ssm describe-instance-information \
        --region "$REGION" \
        --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
        --query 'InstanceInformationList[0].PingStatus' \
        --output text 2>/dev/null || true)"

    log "DEBUG PingStatus='$ping_status'"

    [[ "$ping_status" == "Online" ]]
}

wait_until() {
    local description="$1"
    local timeout="$2"
    local condition_function="$3"
    local deadline=$((SECONDS + timeout))

    until "$condition_function"; do
        ((SECONDS < deadline)) || fail "Timeout esperando: $description"
        sleep "$POLL_SECONDS"
    done
}

instance_is_running() {
    [[ "$(get_instance_state)" == "running" ]]
}

state="$(get_instance_state)"
log "Instancia: $INSTANCE_ID"
log "Region:    $REGION"
log "Trabajos:  $(jq '.jobs | length' "$JOBS_FILE")"
log "Estado inicial: $state"

case "$state" in

    stopped)

        log "Arrancando instancia..."

        aws ec2 start-instances \
            --region "$REGION" \
            --instance-ids "$INSTANCE_ID" \
            --output json >/dev/null

        STARTED_BY_CONTROLLER=1
        ;;

    stopping)

        log "Instancia deteniéndose. Esperando estado stopped..."

        aws ec2 wait instance-stopped \
            --region "$REGION" \
            --instance-ids "$INSTANCE_ID"

        log "Instancia detenida. Arrancando..."

        aws ec2 start-instances \
            --region "$REGION" \
            --instance-ids "$INSTANCE_ID" \
            --output json >/dev/null

        STARTED_BY_CONTROLLER=1
        ;;

    pending)

        log "Instancia arrancando..."
        ;;

    running)

        log "Instancia ya arrancada."
        ;;

    *)

        fail "Estado EC2 no soportado: $state"
        ;;

esac

wait_until "EC2 running" \
    "$STARTUP_TIMEOUT" \
    instance_is_running

log "EC2 esta running."

log "Esperando SSM Online..."

wait_until "SSM Online" \
    "$STARTUP_TIMEOUT" \
    ssm_is_online

log "SSM esta Online."


REMOTE_COMMAND="$REMOTE_SCRIPT --timeout $WORKER_TIMEOUT"
while IFS= read -r worker_job; do
    REMOTE_COMMAND+=" --job '$worker_job'"
done < <(
    jq -r '.jobs[] |
        [ .frame0, .frame1, .frame2, .frame3, .start, .end ] |
        map(ascii_upcase) | join(",")' "$JOBS_FILE"
)

PARAMS_JSON="$(jq -nc \
    --arg command "$REMOTE_COMMAND" \
    '{commands: [$command]}')"

log "Enviando trabajos KeeLoq..."


COMMAND_ID="$(
aws ssm send-command \
    --region "$REGION" \
    --instance-ids "$INSTANCE_ID" \
    --document-name AWS-RunShellScript \
    --parameters "$PARAMS_JSON" \
    --timeout-seconds "$((WORKER_TIMEOUT + 60))" \
    --query 'Command.CommandId' \
    --output text
)"


[[ -n "$COMMAND_ID" && "$COMMAND_ID" != "None" ]] \
    || fail "SSM no devolvio CommandId."
log "CommandId: $COMMAND_ID"

deadline=$((SECONDS + WORKER_TIMEOUT + 120))
status="Pending"

while :; do
    sleep "$POLL_SECONDS"

    if ! aws ssm get-command-invocation \
        --region "$REGION" \
        --command-id "$COMMAND_ID" \
        --instance-id "$INSTANCE_ID" \
        --output json > "$TMP_DIR/invocation.json" 2> "$TMP_DIR/invocation.err"; then
        ((SECONDS < deadline)) || fail "No se pudo consultar el comando SSM."
        continue
    fi

    status="$(jq -r '.Status' "$TMP_DIR/invocation.json")"
    log "Estado SSM: $status"
	log "ResponseCode: $(jq -r '.ResponseCode // "null"' "$TMP_DIR/invocation.json")"
    case "$status" in
        Success|Failed|Cancelled|TimedOut|Cancelling)
            break
            ;;
    esac

    ((SECONDS < deadline)) || fail "Timeout esperando la finalizacion del comando SSM."
done

RESPONSE_CODE="$(jq -r '.ResponseCode // empty' "$TMP_DIR/invocation.json")"

log "ResponseCode: ${RESPONSE_CODE:-<vacío>}"

if [[ "$status" != "Success" ]]; then
    error_text="$(jq -r '.StandardErrorContent // ""' "$TMP_DIR/invocation.json")"
    fail "El worker fallo. Estado=$status. Error=$error_text"
fi

jq -r '.StandardOutputContent' \
    "$TMP_DIR/invocation.json" \
    > "$TMP_DIR/worker-output.txt"

sed -n '/^{/,$p' \
    "$TMP_DIR/worker-output.txt" \
    > "$TMP_DIR/worker-result.json"

jq -e . "$TMP_DIR/worker-result.json" >/dev/null || \
    fail "La salida del worker no es JSON valido."

python3 - \
    "$TMP_DIR/worker-result.json" \
    "$MASTER_KEY_HEX" <<'PY'
import json
import re
import sys

NLF = 0x3A5C742E


def keeloq_encrypt(plaintext, key):
    value = plaintext & 0xFFFFFFFF
    key = key & 0xFFFFFFFFFFFFFFFF

    for round_index in range(528):
        nlf_index = (
            ((value >> 1) & 1)
            | (((value >> 9) & 1) << 1)
            | (((value >> 20) & 1) << 2)
            | (((value >> 26) & 1) << 3)
            | (((value >> 31) & 1) << 4)
        )

        feedback = (
            ((value >> 0) & 1)
            ^ ((value >> 16) & 1)
            ^ ((key >> (round_index & 63)) & 1)
            ^ ((NLF >> nlf_index) & 1)
        )

        value = ((value >> 1) | (feedback << 31)) & 0xFFFFFFFF

    return value


def parse_master_key(text):
    normalized = text.strip()

    if normalized.lower().startswith("0x"):
        normalized = normalized[2:]

    if not re.fullmatch(r"[0-9a-fA-F]{16}", normalized):
        raise ValueError(
            "La clave master debe contener exactamente "
            "16 digitos hexadecimales"
        )

    return int(normalized, 16)


def parse_found_key(text):
    if not isinstance(text, str):
        raise ValueError("La clave encontrada no es una cadena")

    normalized = text.strip()

    if normalized.lower().startswith("0x"):
        normalized = normalized[2:]

    if not re.fullmatch(r"[0-9a-fA-F]{8}", normalized):
        raise ValueError(
            "La clave encontrada debe contener exactamente "
            "8 digitos hexadecimales"
        )

    return int(normalized, 16)


if len(sys.argv) != 3:
    raise SystemExit(
        "Uso: encrypt_results.py RESULT_JSON MASTER_KEY_HEX"
    )

result_path = sys.argv[1]
master_key = parse_master_key(sys.argv[2])

with open(result_path, "r", encoding="utf-8") as input_file:
    result = json.load(input_file)

for job in result.get("jobs", []):
    found = bool(job.get("found", False))
    plain_key = job.get("key")

    if found:
        try:
            plain_value = parse_found_key(plain_key)
            encrypted_value = keeloq_encrypt(
                plain_value,
                master_key
            )

            job["encrypted_key"] = (
                f"0x{encrypted_value:08X}"
            )
            job["encryption_status"] = "encrypted"
            job["encryption_error"] = None

        except Exception as error:
            job["encrypted_key"] = None
            job["encryption_status"] = "error"
            job["encryption_error"] = str(error)
            result["success"] = False

    else:
        job["encrypted_key"] = None
        job["encryption_status"] = "not_found"
        job["encryption_error"] = None

    # No devolver la clave encontrada en claro.
    job.pop("key", None)

result["key_encryption"] = {
    "algorithm": "KeeLoq",
    "block_bits": 32,
    "master_key_bits": 64,
    "byte_order": "listed-bytes-as-big-endian"
}

json.dump(
    result,
    sys.stdout,
    indent=2,
    ensure_ascii=True
)

sys.stdout.write("\n")
PY
