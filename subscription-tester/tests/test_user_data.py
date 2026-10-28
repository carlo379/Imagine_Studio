"""Fresh installs and migration use synthetic temporary data only."""
import os
from pathlib import Path
import runpy
import tempfile
import unittest
from unittest.mock import patch
import user_data
from studio_server import Studio

ROOT = Path(__file__).resolve().parents[2]


class UserDataTests(unittest.TestCase):
    def test_default_is_outside_checkout_and_custom_location_is_supported(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertNotIn(ROOT, user_data.data_home().parents)
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'IMAGINE_STUDIO_DATA_DIR': folder}):
            self.assertEqual(user_data.data_home(), Path(folder).resolve())
        with self.assertRaisesRegex(ValueError, 'outside'):
            user_data.outside_source(ROOT / 'private-data')

    def test_fresh_workspace_has_no_projects_assets_or_media(self):
        with tempfile.TemporaryDirectory() as folder:
            app = Studio(mock=True, storage=Path(folder) / 'studio')
            self.assertEqual(app.productions.all('production'), [])
            self.assertEqual(app.productions.all('shot'), [])
            self.assertEqual(app.assets, [])
            self.assertEqual(app.references, [])
            self.assertEqual(app.history, [])
            app.productions.sql.close()

    def test_migration_preserves_bytes_and_refuses_overwrite(self):
        migrate = runpy.run_path(str(ROOT / 'scripts/migrate_user_data.py'))['migrate']
        with tempfile.TemporaryDirectory() as folder:
            source, dest = Path(folder) / 'old', Path(folder) / 'new'
            source.mkdir(); (source / 'fixture.bin').write_bytes(b'synthetic private data')
            self.assertTrue(migrate(source, dest))
            self.assertEqual((dest / 'fixture.bin').read_bytes(), b'synthetic private data')
            self.assertFalse(source.exists())
            source.mkdir()
            with self.assertRaises(ValueError): migrate(source, dest)

    def test_privacy_gate_scans_source_guides_and_bundles_without_printing_values(self):
        scan = runpy.run_path(str(ROOT / 'scripts/check_public_privacy.py'))['findings']
        with tempfile.TemporaryDirectory() as folder:
            for name in ['test.py', 'guide.md', 'bundle.js']:
                Path(folder, name).write_text('PrivateExample person')
            found = list(scan(folder, ['PrivateExample']))
            self.assertEqual(len(found), 3)
            self.assertNotIn('PrivateExample', str(found))

    def test_optional_model_paths_follow_migrated_storage(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'IMAGINE_STUDIO_DATA_DIR': folder}):
            legacy = ROOT / 'subscription-tester' / '.state' / 'studio' / 'model'
            self.assertEqual(user_data.relocated_path(legacy), (Path(folder) / 'studio' / 'model').resolve())
            self.assertEqual(user_data.relocated_path((Path(folder) / 'other').resolve()), (Path(folder) / 'other').resolve())
