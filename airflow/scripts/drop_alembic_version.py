#!/usr/bin/env python3
"""Drop only the shared ``alembic_version`` table so Airflow's ``db migrate`` starts fresh.

Both the backend and Airflow use the same PostgreSQL database + same ``public`` schema,
which means they share a single ``alembic_version`` table. When the backend runs
``alembic upgrade head`` it writes its revision into this table, which then confuses
Airflow's own ``airflow db migrate`` (which expects an Airflow revision, not a backend
one). This script drops just that table so Airflow can start clean without nuking the
entire schema.
"""

import os

from sqlalchemy import create_engine, text

engine = create_engine(os.environ["AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"])
with engine.connect() as conn:
    conn.execute(text("DROP TABLE IF EXISTS alembic_version CASCADE"))
    conn.commit()

print("dropped alembic_version")
