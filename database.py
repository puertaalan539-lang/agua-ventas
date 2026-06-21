"""
database.py
Gestión de la base de datos PostgreSQL (Supabase) para el sistema de
ventas de agua purificada.

Requiere: pip install psycopg2-binary
La cadena de conexión se lee de:
  1) variable de entorno DATABASE_URL, o
  2) st.secrets["DATABASE_URL"] cuando corre en Streamlit Cloud
"""

import os
import psycopg2
import psycopg2.extras
from datetime import date

# ──────────────────────────────────────────────
# CONEXIÓN
# ──────────────────────────────────────────────
def _get_database_url() -> str:
    # 1) Variable de entorno local
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    # 2) Streamlit Secrets (cuando corre en Streamlit Cloud)
    try:
        import streamlit as st
        return st.secrets["DATABASE_URL"]
    except Exception:
        raise RuntimeError(
            "No se encontró DATABASE_URL. Configúrala como variable de entorno "
            "o en .streamlit/secrets.toml"
        )


def get_conn():
    url = _get_database_url()
    conn = psycopg2.connect(url, cursor_factory=psycopg2.extras.RealDictCursor)
    return conn


# ──────────────────────────────────────────────
# INICIALIZACIÓN DE TABLAS
# ──────────────────────────────────────────────
def init_db():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS locales (
                id        SERIAL PRIMARY KEY,
                nombre    TEXT NOT NULL UNIQUE,
                direccion TEXT DEFAULT '',
                activo    BOOLEAN DEFAULT TRUE
            );

            CREATE TABLE IF NOT EXISTS ventas_locales (
                id              SERIAL PRIMARY KEY,
                local_id        INTEGER NOT NULL REFERENCES locales(id),
                fecha           DATE    NOT NULL,
                garrafon        INTEGER DEFAULT 0,
                medio_garrafon  INTEGER DEFAULT 0,
                galon           INTEGER DEFAULT 0,
                precio_garrafon REAL DEFAULT 0,
                precio_medio    REAL DEFAULT 0,
                precio_galon    REAL DEFAULT 0,
                total_bruto     REAL DEFAULT 0,
                fuente          TEXT DEFAULT 'manual',
                notas           TEXT DEFAULT '',
                UNIQUE (local_id, fecha)
            );

            CREATE TABLE IF NOT EXISTS ventas_individuales (
                id          SERIAL PRIMARY KEY,
                fecha       DATE NOT NULL,
                producto    TEXT NOT NULL,
                cantidad    INTEGER DEFAULT 1,
                precio_unit REAL DEFAULT 0,
                total       REAL GENERATED ALWAYS AS (cantidad * precio_unit) STORED,
                notas       TEXT DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS gastos (
                id            SERIAL PRIMARY KEY,
                fecha         DATE NOT NULL,
                descripcion   TEXT NOT NULL,
                monto_total   REAL NOT NULL,
                porc_garrafon REAL DEFAULT 0.60,
                porc_medio    REAL DEFAULT 0.25,
                porc_galon    REAL DEFAULT 0.15
            );

            CREATE TABLE IF NOT EXISTS reportes (
                id           SERIAL PRIMARY KEY,
                fecha_gen    TEXT NOT NULL,
                tipo         TEXT NOT NULL,
                ruta_archivo TEXT DEFAULT ''
            );
            """)
        conn.commit()
    finally:
        conn.close()
    _seed_locales()


def _seed_locales():
    """Inserta los 7 locales por defecto si no existen."""
    locales = [f"Local {i}" for i in range(1, 8)]
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for nombre in locales:
                cur.execute(
                    "INSERT INTO locales (nombre) VALUES (%s) "
                    "ON CONFLICT (nombre) DO NOTHING",
                    (nombre,)
                )
        conn.commit()
    finally:
        conn.close()


# ──────────────────────────────────────────────
# LOCALES
# ──────────────────────────────────────────────
def get_locales(solo_activos=True):
    q = "SELECT * FROM locales"
    if solo_activos:
        q += " WHERE activo = TRUE"
    q += " ORDER BY nombre"
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(q)
            return cur.fetchall()
    finally:
        conn.close()


def update_nombre_local(local_id: int, nuevo_nombre: str):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE locales SET nombre = %s WHERE id = %s",
                (nuevo_nombre, local_id)
            )
        conn.commit()
    finally:
        conn.close()


# ──────────────────────────────────────────────
# VENTAS DE LOCALES
# ──────────────────────────────────────────────
def upsert_venta_local(
    local_id: int, fecha: date,
    garrafon: int, medio_garrafon: int, galon: int,
    precio_garrafon: float, precio_medio: float, precio_galon: float,
    fuente: str = "manual", notas: str = ""
):
    total = (garrafon * precio_garrafon +
             medio_garrafon * precio_medio +
             galon * precio_galon)

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ventas_locales
                (local_id, fecha, garrafon, medio_garrafon, galon,
                 precio_garrafon, precio_medio, precio_galon,
                 total_bruto, fuente, notas)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (local_id, fecha) DO UPDATE SET
                    garrafon = EXCLUDED.garrafon,
                    medio_garrafon = EXCLUDED.medio_garrafon,
                    galon = EXCLUDED.galon,
                    precio_garrafon = EXCLUDED.precio_garrafon,
                    precio_medio = EXCLUDED.precio_medio,
                    precio_galon = EXCLUDED.precio_galon,
                    total_bruto = EXCLUDED.total_bruto,
                    fuente = EXCLUDED.fuente,
                    notas = EXCLUDED.notas
            """, (local_id, fecha, garrafon, medio_garrafon, galon,
                  precio_garrafon, precio_medio, precio_galon,
                  total, fuente, notas))
        conn.commit()
    finally:
        conn.close()


def get_ventas_por_fecha(fecha: date):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT vl.*, l.nombre as local_nombre
                FROM ventas_locales vl
                JOIN locales l ON l.id = vl.local_id
                WHERE vl.fecha = %s
                ORDER BY l.nombre
            """, (fecha,))
            return cur.fetchall()
    finally:
        conn.close()


def get_ventas_rango(fecha_ini: date, fecha_fin: date):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT vl.*, l.nombre as local_nombre
                FROM ventas_locales vl
                JOIN locales l ON l.id = vl.local_id
                WHERE vl.fecha BETWEEN %s AND %s
                ORDER BY vl.fecha, l.nombre
            """, (fecha_ini, fecha_fin))
            return cur.fetchall()
    finally:
        conn.close()


# ──────────────────────────────────────────────
# VENTAS INDIVIDUALES
# ──────────────────────────────────────────────
def insert_venta_individual(
    fecha: date, producto: str,
    cantidad: int, precio_unit: float, notas: str = ""
):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO ventas_individuales (fecha, producto, cantidad, precio_unit, notas)
                VALUES (%s,%s,%s,%s,%s)
            """, (fecha, producto, cantidad, precio_unit, notas))
        conn.commit()
    finally:
        conn.close()


def get_ventas_individuales_fecha(fecha: date):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM ventas_individuales WHERE fecha = %s ORDER BY id DESC",
                (fecha,)
            )
            return cur.fetchall()
    finally:
        conn.close()


def delete_venta_individual(venta_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM ventas_individuales WHERE id = %s", (venta_id,))
        conn.commit()
    finally:
        conn.close()


# ──────────────────────────────────────────────
# GASTOS
# ──────────────────────────────────────────────
def insert_gasto(
    fecha: date, descripcion: str, monto: float,
    porc_garrafon: float = 0.60,
    porc_medio: float    = 0.25,
    porc_galon: float    = 0.15
):
    assert abs(porc_garrafon + porc_medio + porc_galon - 1.0) < 1e-9, \
        "Los porcentajes de gasto deben sumar 100%"
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO gastos (fecha, descripcion, monto_total,
                                    porc_garrafon, porc_medio, porc_galon)
                VALUES (%s,%s,%s,%s,%s,%s)
            """, (fecha, descripcion, monto, porc_garrafon, porc_medio, porc_galon))
        conn.commit()
    finally:
        conn.close()


def get_gastos_fecha(fecha: date):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM gastos WHERE fecha = %s ORDER BY id",
                (fecha,)
            )
            return cur.fetchall()
    finally:
        conn.close()


def delete_gasto(gasto_id: int):
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM gastos WHERE id = %s", (gasto_id,))
        conn.commit()
    finally:
        conn.close()


# ──────────────────────────────────────────────
# REPORTES (registro de archivos generados)
# ──────────────────────────────────────────────
def registrar_reporte(tipo: str, ruta: str):
    from datetime import datetime
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO reportes (fecha_gen, tipo, ruta_archivo) VALUES (%s,%s,%s)",
                (datetime.now().isoformat(), tipo, ruta)
            )
        conn.commit()
    finally:
        conn.close()