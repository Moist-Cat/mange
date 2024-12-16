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

class Sucursal(Base):
    nombre = Column(String, unique=True, nullable=False)
    tipo = Column(String)
    direccion = Column(String)
    limite = Column(Integer, nullable=False)
    porciento_extra = Column(Integer, default=15, nullable=False)
    aumento = Column(Integer, default=20, nullable=False)
    # areas = relationship("Area",back_populates="sucursal",uselist=True)
    # registros = relationship("Registro",back_populates="sucursal",uselist=True)

    def calculate(self):
        return (self.reading - self.last_reading)*(100 + self.extra_percent)//100 + self.extra

    @property
    def over_limit(self):
        return max(0, self.reading - self.limit)

class Area(Base):
    nombre = Column(String,nullable=False)
    responsable = Column(String,nullable=False)
    id_sucursal = Column(Integer,ForeignKey("sucursal.id"),nullable=False)
    # equipo = relationship("Equipo",back_populates="area",uselist=True)
    # sucursal = relationship("Sucursal",back_populates="area")
    
class Registro(Base):
    lectura = Column(Integer, nullable=False)
    costo = Column(Integer, nullable=False)
    sobre_limite = Column(Integer, nullable=False)
    fecha = Column(DateTime,nullable=False)
    id_sucursal = Column(Integer,ForeignKey("sucursal.id"),nullable=False)
    # sucursal = relationship("Sucursal",back_populates="registro")
    
class Equipo(Base):
    modelo = Column(String)
    consumo_diario_promedio = Column(Integer)
    estado_de_mantenimiento = Column(String)
    eficiencia_energetica = Column(String)
    capacidad_nominal = Column(Integer)
    vida_util_estimada = Column(Integer)
    fecha_instalacion = Column(DateTime)
    frecuencia_de_uso = Column(String)
    tipo = Column(String)
    marca = Column(String)
    sistema_energia_critica = Column(Boolean)
    # area = relationship("Area",back_populates="equipo")

class Group(Base):
    name = Column(String, unique=True)

class User(Base):
    name = Column(String, unique=True)
    password = Column(String, nullable=False)
    group_id = Column(None, ForeignKey("group.id"))
    group = relationship(Group, backref="users")
    token = relationship("Token", uselist=False, back_populates="user")

class Token(Base):
    value = Column(String, nullable=False)
    user_id = Column(
        None,
        ForeignKey("user.id"),
    )
    user = relationship(
        User,
        back_populates="token",
        single_parent=True
        )


def create_db(name=settings.DATABASES["default"]["engine"]):
    """
    Create database and schema if and only if the schema was modified
    """
    file = name.split(os.sep)[-1]
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
