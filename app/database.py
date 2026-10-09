from pathlib import Path
import sqlite3


DATA_DIR = Path("/app/data")
DB_PATH = DATA_DIR / "jobs.db"


ESTADOS_VALIDOS = (
    "PENDING",
    "RUNNING",
    "DONE",
    "FAILED",
)


def get_connection():
    """
    Abre una conexión a la base SQLite.

    Las filas se devuelven como sqlite3.Row para poder acceder
    a las columnas por nombre.
    """

    DATA_DIR.mkdir(
        parents=True,
        exist_ok=True
    )

    conn = sqlite3.connect(
        str(DB_PATH),
        timeout=30,
        check_same_thread=False
    )

    conn.row_factory = sqlite3.Row

    conn.execute(
        "PRAGMA foreign_keys = ON"
    )

    conn.execute(
        "PRAGMA busy_timeout = 30000"
    )

    return conn


def initialize_database():
    """
    Crea la tabla jobs y sus índices si no existen.
    """

    conn = get_connection()

    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS jobs
            (
                id INTEGER PRIMARY KEY AUTOINCREMENT,

                licencia TEXT NOT NULL,
                peticion INTEGER NOT NULL,

                fichero_peticion TEXT NOT NULL,

                estado TEXT NOT NULL DEFAULT 'PENDING'
                    CHECK (
                        estado IN (
                            'PENDING',
                            'RUNNING',
                            'DONE',
                            'FAILED'
                        )
                    ),

                fecha_creacion TEXT NOT NULL
                    DEFAULT CURRENT_TIMESTAMP,

                fecha_inicio TEXT,

                fecha_fin TEXT,

                intentos INTEGER NOT NULL DEFAULT 0
                    CHECK (intentos >= 0),

                error TEXT,

                worker_id TEXT,

                resultado TEXT,

                fecha_en_cl TEXT

            )
            """
        )

        conn.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                UX_jobs_licencia_peticion
            ON jobs (
                licencia,
                peticion
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS
                IX_jobs_estado_id
            ON jobs (
                estado,
                id
            )
            """
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()
