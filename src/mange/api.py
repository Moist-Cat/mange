"""API"""
import base64
from datetime import datetime
from functools import wraps, lru_cache
from hashlib import sha256
import inspect
import logging
import uuid
import pathlib
import pickle
import time

from sqlalchemy import create_engine
from sqlalchemy.sql import text, select
from sqlalchemy.orm import sessionmaker, scoped_session

from mange.conf import settings
from mange.db import (
    Base,
    Sucursal,
    Area,
    Registro,
    Equipo,
    User,
    Group,
    Token,
    load_backup,
)
from mange.log import logged

log = logging.getLogger("global")

DB = settings.DATABASES["default"]
URL = DB["engine"]


def benchmark(method):
    @wraps(method)
    def wrapper(*args, **kwargs):
        start = time.time()

        result = method(*args, **kwargs)

        end = round(time.time() - start, 3)
        log.info("benchmarked method %s %s", method.__name__, end)
        return result

    return wrapper


def loggedmethod(method):
    """
    Log a CRUD method and confirm its successful execution
    version: 1.0.1
    """

    @wraps(method)
    def wrapper(self, *args, **kwargs):
        method_data = inspect.getfullargspec(method)
        mname = method.__name__.lstrip("_")  # ignore encapsulation
        method_type = mname.split("_")[0].upper()
        # + 1 because of self
        try:
            self.logger.info(
                "_%s_ %s %s",
                method_type,
                [
                    f"{method_data.args[index + 1]}={value}"
                    for index, value in enumerate(args)
                ],
                kwargs,
            )
        except IndexError as exc:
            raise IndexError(
                f"Too many arguments for {mname}. Maybe you used positional arguments intead of key-value arguments?"
            )

        res = method(self, *args, **kwargs)

        self.logger.debug("_%s_ --success--", method_type)
        return res

    return wrapper


@logged
class Client:
    def __init__(self, url=URL, config=None):
        config = config or {}
        self.url = url
        self.config = config
        self.logger.info("Started %s. Engine: %s", self.__class__.__name__, URL)

        db_file = pathlib.Path(url.split("///")[-1])
        assert db_file.exists(), f"DB file doesn't exist! {db_file}"
        assert db_file.stat().st_size > 0, "DB file is just an empty file!"

        self.engine = create_engine(url)

        self.engine = create_engine(url)

        self.session = scoped_session(sessionmaker(bind=self.engine, **config))  # pylint: --disable=C0103

    def __delete__(self, obj):
        self.session.rollback()
        self.session.close()

    def __str__(self):
        return f"[Client] ({self.url=} {self.config=})"

    # low level
    @loggedmethod
    def _get(self, Obj, /, **kwargs):
        """Low level GET implementation"""
        query = self.session.query(Obj)
        for k, v in kwargs.items():
            query = query.filter(getattr(Obj, k) == v)

        return query

    @loggedmethod
    def _create(self, Obj, /, **kwargs):
        """Low level insert implementation"""
        obj = Obj(**kwargs)
        self.session.add(obj)
        self.session.commit()

        return obj

    @loggedmethod
    def update(self, obj, /, **kwargs):
        """Update implementation. Feel free to use this directly"""

        if isinstance(obj, Base):
            for k, v in kwargs.items():
                setattr(obj, k, v)
            # self.session.add(obj)
            # self.session.commit()
        elif getattr(obj, "__name__"):
            # model class
            query = self.session.query(obj)
            obj = query.update(**kwargs).one()
        else:
            raise AssertionError(f"{obj} is not update-able")

        return obj

    def _get_or_create(self, Obj, /, **kwargs):
        """Low level select or insert  implementation"""
        obj = self._get(Obj, **kwargs).all()
        if not obj:
            return self._create(Obj, **kwargs)
        obj = obj[0]
        return obj

    # crud
    def create_sucursal(self, /, **kwargs):
        return self._create(Sucursal, **kwargs)

    def get_sucursal(self, /, **kwargs):
        return self._get(Sucursal, **kwargs)

    def create_area(self, /, **kwargs):
        return self._create(Area, **kwargs)

    def get_area(self, /, **kwargs):
        return self._get(Area, **kwargs)

    def create_registro(self, /, **kwargs):
        return self._create(Registro, **kwargs)

    def get_registro(self, /, **kwargs):
        return self._get(Registro, **kwargs)
        
    def create_equipo(self, /, **kwargs):
        return self._create(Equipo, **kwargs)

    def get_equipo(self, /, **kwargs):
        return self._get(Equipo, **kwargs)

    def get_user(self, /, **kwargs):
        return self._get(User, **kwargs)

    @staticmethod
    def _get_hash(password):
        return sha256(bytes(password, encoding="utf8")).hexdigest()

    def create_user(self, /, **kwargs):
        kwargs["password"] = self._get_hash(kwargs["password"])
        user = self._create(User, **kwargs)
        token = self._create(Token, user=user, value=str(uuid.uuid4()))

        return user

    def get_group(self, /, **kwargs):
        return self._get(Group, **kwargs)

    def create_group(self, /, **kwargs):
        return self._create(Group, **kwargs)

    # mid-level
    def add_user_to_grup(self, user, grup):
        group.users.append(user)
        self.session.commit()

        return group

    def login(self, name, password):
        user = self._get(User, name=name, password=self._get_hash(password)).one()

        return user.token

    def user_from_token(self, token):
        return self._get(Token, value=token).one().user

    def liquidate_bill(self, company, date=None):
        """
        Given a company, liquidate its bill.
        """
        over_limit = company.over_limit
        cost = company.calculate()

        company.last_reading = company.reading
        self.update(company, last_reading=company.reading)
        self.session.commit()

        return self.create_registro(
            sucursal=company,
            fecha=date or datetime.today(),
            lectura=company.reading,
            sobre_limite=over_limit,
            costo=cost,
        )
    
    # high-level
    def total_consumption(self, company, start_date, end_date):
        # select * between start_date and end_date
        start = self._get(Registro, fecha=start_date, id_sucursal=company.id).one()
        end = self._get(Registro, fecha=end_date, id_sucursal=company.id).one()

        return end.lectura - start.lectura

    def average_consumption(self, company, start_date, end_date):
        """
        Monthly consumption.
        """
        months = (end_date - start_date).days // 30
        return self.total_consumption(company, start_date, end_date)/months

    def over_consumption(self, start_date, end_date):
        # select company, over_limit where over_limit > 0
        return self._get(Registro).filter(Registro.sobre_limite > 0).all()

    def predict_consumption(self, company, start_date, end_date):
        # :^)
        return self.average_consumption(company, start_date, end_date)

    def compare_consumption(self, start_date, end_date):
        """
        a frecuencia de uso (>every time one uses an item they must register it manually wtf)
        """
        return self._get(Registro).filter(Registro.fecha >= start_date).filter(Registro.fecha <= end_date).all()

    def list_alerts(self, company):
        # select * where over_limit>1 and company_id = company.id
        return self._get(Registro, company_id=company.id).filter(Registro.sobre_limite > 0).all()
