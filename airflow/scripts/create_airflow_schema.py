"""Create Airflow's own PostgreSQL schema before ``airflow db migrate``.

Airflow and the backend share one database. Giving Airflow a dedicated schema
keeps its ``alembic_version`` and tables away from the backend's, so neither
migration chain can overwrite the other.
"""

import os

from sqlalchemy import create_engine, text

dsn = os.environ["AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"].replace("+psycopg2", "")
engine = create_engine(dsn)
with engine.connect() as conn:
    conn.execute(text("CREATE SCHEMA IF NOT EXISTS airflow"))
    conn.commit()

print("ensured airflow schema")
