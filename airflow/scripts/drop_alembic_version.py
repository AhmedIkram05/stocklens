#!/usr/bin/env python3
"""Drop all Airflow tables with CASCADE so ``airflow db migrate`` starts fresh.

Airflow 3.x migration from a partially-migrated 2.x database fails with
FK dependency conflicts. This drops every table in the public schema
with CASCADE, then ``airflow db migrate`` recreates everything clean.

Dev-only — destroys ALL Airflow metadata.
"""

import os

from sqlalchemy import create_engine, text

engine = create_engine(os.environ["AIRFLOW__DATABASE__SQL_ALCHEMY_CONN"])
with engine.connect() as conn:
    conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
    conn.execute(text("CREATE SCHEMA public"))
    conn.commit()
