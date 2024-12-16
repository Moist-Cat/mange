from datetime import datetime
import os
from pathlib import Path
import unittest

from mange.db import *
from mange.api import *
from mange.conf import settings

db = settings.DATABASES["default"]
ENGINE = db["engine"]

TEST_DIR = settings.TEST_DIR

def build_test_db(
        name=ENGINE,
    ):
    """
    Create test database and schema.
    """
    engine = create_engine(name)

    # Nuke everything and build it from scratch.
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)

    return engine

class Test_API(unittest.TestCase):
    
    def setUp(self):
        build_test_db()
        self.client = Client()

    def tearDown(self):
        pass

    def test_login(self):
        user = self.client.create_user(name="blob", password="doko")
        self.client.session.commit()

        self.assertEqual(self.client.login(name="blob", password="doko"), user.token)

    def test_liquidate_registro(self):
        sucursal = self.client.create_sucursal(nombre="blobcorp", last_reading=0, reading=0, limite=100)
        self.client.session.commit()

        sucursal.reading = 50

        registro = self.client.liquidate_bill(sucursal)

        self.assertEqual(sucursal.last_reading, sucursal.reading)
        self.assertEqual(registro.sobre_limite, 0)

        sucursal.reading = 150

        registro = self.client.liquidate_bill(sucursal)
        self.assertEqual(registro.sobre_limite, 50)

    def test_total_consumption(self):
        sucursal = self.client.create_sucursal(nombre="blobcorp", last_reading=0, reading=100, limite=9999)
        self.client.session.commit()

        sucursal.reading = 150
        registro = self.client.liquidate_bill(sucursal, date=datetime(2000, 10, 1))

        sucursal.reading = 300
        registro = self.client.liquidate_bill(sucursal, date=datetime(2000, 10, 2))

        sucursal.reading = 500
        registro = self.client.liquidate_bill(sucursal, date=datetime(2000, 10, 3))

        self.assertEqual(
            self.client.total_consumption(
                sucursal,
                start_date=datetime(2000, 10, 1),
                end_date=datetime(2000, 10, 3)
            ),
            350,
        )

    def test_over_consumption(self):
        sucursal = self.client.create_sucursal(nombre="blobcorp", last_reading=0, reading=1, limite=0)
        self.client.session.commit()
        registro = self.client.liquidate_bill(sucursal, date=datetime(2000, 10, 1))

        self.assertEqual(
            self.client.over_consumption(start_date=datetime(2000, 10, 1), end_date=datetime(2000, 10, 1)),
            [registro],
        )



def main_suite() -> unittest.TestSuite:
    s = unittest.TestSuite()
    load_from = unittest.defaultTestLoader.loadTestsFromTestCase
    s.addTests(load_from(Test_API))
    
    return s

def run():
    t = unittest.TextTestRunner()
    t.run(main_suite())
