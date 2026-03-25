import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from crop_store import CropStore

Rect = tuple[float, float, float, float]

class CropStoreTests(unittest.TestCase):
    def test_returns_none_when_no_default_set(self):
        store = CropStore()
        self.assertIsNone(store.get(1))

    def test_returns_default_when_set(self):
        store = CropStore()
        store.set_default((0, 0, 100, 200))
        self.assertEqual(store.get(5), (0, 0, 100, 200))

    def test_per_page_overrides_default(self):
        store = CropStore()
        store.set_default((0, 0, 100, 200))
        store.set(3, (10, 20, 90, 180))
        self.assertEqual(store.get(3), (10, 20, 90, 180))
        self.assertEqual(store.get(4), (0, 0, 100, 200))

    def test_has_override_returns_correct(self):
        store = CropStore()
        store.set(3, (10, 20, 90, 180))
        self.assertTrue(store.has_override(3))
        self.assertFalse(store.has_override(4))

    def test_all_rects_returns_per_page_or_default(self):
        store = CropStore()
        store.set_default((0, 0, 100, 200))
        store.set(2, (5, 5, 95, 195))
        result = store.all_rects(page_count=3)
        self.assertEqual(result[1], (0, 0, 100, 200))
        self.assertEqual(result[2], (5, 5, 95, 195))
        self.assertEqual(result[3], (0, 0, 100, 200))
