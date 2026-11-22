import sqlite3
import unittest
from qt_open_component import resolve_part

class Tests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.execute('CREATE TABLE components(id INTEGER PRIMARY KEY, part_number TEXT)')
        self.db.execute('INSERT INTO components (id,part_number) VALUES (123, "TPS65150")')
    def tearDown(self):
        self.db.close()
    def test_exact_case_insensitive(self):
        self.assertEqual(resolve_part(self.db,' tps65150 '), (123,'TPS65150'))
    def test_no_partial(self):
        with self.assertRaises(LookupError): resolve_part(self.db, 'TPS6515')
    def test_missing(self):
        with self.assertRaises(LookupError): resolve_part(self.db, 'NOTEXIST')
    def test_ambiguous(self):
        self.db.execute('INSERT INTO components (id,part_number) VALUES (124, "tps65150")')
        with self.assertRaises(ValueError): resolve_part(self.db, 'TPS65150')

if __name__ == '__main__': unittest.main()
