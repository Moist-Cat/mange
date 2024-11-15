"""
ORM layer for the DB
"""
import os
from enum import Enum
import logging
import shutil
import random
import re
import pathlib
from warnings import warn
import pickle
import base64

from sqlalchemy import Column, create_engine, func
from sqlalchemy import (
    Integer,
    Float,
    String,
    Text,
    Boolean,
    ForeignKey,
    DateTime,
)
from sqlalchemy.sql import text
from sqlalchemy.ext.declarative import declared_attr
from sqlalchemy.orm import relationship, as_declarative, validates
from sqlalchemy.schema import UniqueConstraint, CheckConstraint

from mange.conf import settings
from mange.log import logged

logger = logging.getLogger("user_info." + __name__)


@as_declarative()
class Base:
    """Automated table name, surrogate pk, and serializing"""

    @declared_attr
    def __tablename__(cls):  # pylint: --disable=no-self-argument
        cls_name = cls.__name__
        table_name = list(cls_name)
        for index, match in enumerate(re.finditer("[A-Z]", cls_name[1:])):
            table_name.insert(match.end() + index, "_")
        table_name = "".join(table_name).lower()
        return table_name

    def as_dict(self):
        """
        I won't recursively serialialize all related fields because it will cause trouble
        with circular dependencies (for example, in Location, Paths can lead eventually to the same Location)
        """
        return {
            column: getattr(self, column) for column in self.__table__.columns.keys()
        }

    def __str__(self):
        return f"[ {self.__class__.__name__} ] ({self.as_dict()})"

    def __repr__(self):
        return self.__str__()

    id = Column(Integer, primary_key=True, nullable=False)

class Company(Base):
    """
    Metadata corresponding to a given company.

    :last_reading: Last reading for the company (kWh)
    :reading: Current reading for the company (kWh)
    :extra_percent: and :extra: are used to calculate the final cost
    :limit: 
    """
    name = Column(String, unique=True, nullable=False)

    last_reading = Column(Integer, nullable=False)
    reading = Column(Integer, nullable=False)
    extra_percent = Column(Integer, default=15)
    extra = Column(Integer, default=20)
    limit = Column(Integer, nullable=False)

    def calculate(self):
        return (self.reading - self.last_reading)*(100 + self.extra_percent)//100 + self.extra

    @property
    def over_limit(self):
        return max(0, self.calculate() - self.limit)

class Item(Base):
    """
    Item corresponding to a company
    """

    company_id = Column(None, ForeignKey("company.id"), nullable=False)
    company = relationship(Company, backref="items")
    # metadata

class Bill(Base):
    """
    """
    # company
    company_id = Column(None, ForeignKey("company.id"), nullable=False)
    company = relationship(Company, backref="bills")

    date = Column(DateTime, nullable=False)
    reading = Column(Integer, nullable=False)
    over_limit = Column(Integer, default=0)


def create_db(name=settings.DATABASES["default"]["engine"]):
    """
    Create database and schema if and only if the schema was modified
    """
    file = name.split("/")[-1]
    master = "master_" + file
    master_name = name.replace(file, master)

    path = name.split("///")[-1].replace("(", "")
    master_path = pathlib.Path(path.replace(file, master))
    child_path = pathlib.Path(path)

    # Nuke everything and build it from scratch.
    if db_schema_modified("db.py") or not master_path.exists():
        master_engine = create_engine(master_name)
        Base.metadata.drop_all(master_engine)
        Base.metadata.create_all(master_engine)

    shutil.copy(master_path, child_path)

    engine = create_engine(name)

    return str(engine.url)


def drop_db(name=settings.DATABASES["default"]["engine"]):
    engine = create_engine(name)
    Base.metadata.drop_all(engine)


def db_schema_modified(filename):
    """
    Utility tool to know if a file was modified.
    :param file: Path object, file to watch
    """
    ts_file = (
        settings.BASE_DIR
        / f"_last_mod_{filename if isinstance(filename, str) else filename.name}.timestamp"
    )
    if not (settings.BASE_DIR / filename).exists():
        warn(f"{filename} does not exist")
        return
    _last_schema_mod = os.stat(settings.BASE_DIR / filename).st_mtime
    try:
        with open(ts_file, encoding="utf-8") as file:
            _lst_reg_schema_mod = file.read()
    except FileNotFoundError as exc:
        _, error = exc.args
        warn(error)
        with open(ts_file, "w", encoding="utf-8") as file:
            file.write(str(_last_schema_mod))
            _lst_reg_schema_mod = 0

    SCHEMA_MODIFIED = float(_lst_reg_schema_mod) != _last_schema_mod
    if SCHEMA_MODIFIED:
        logger.info("Detected change in %s ... db will be rebuilt", filename)
        with open(ts_file, "w", encoding="utf-8") as file:
            file.write(str(_last_schema_mod))

    return SCHEMA_MODIFIED


def load_backup(source: "Engine", dest: "Engine"):
    if isinstance(dest, str):
        dest = create_engine(dest)

    raw_src = source.raw_connection()
    raw_dst = dest.raw_connection()
    raw_src.driver_connection.backup(raw_dst.driver_connection)
    raw_src.close()
