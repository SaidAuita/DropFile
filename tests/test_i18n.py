"""
Unit tests for DropFile Internationalization (i18n) module.
"""

import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config
from i18n import (
    SUPPORTED_LANGUAGES,
    TRANSLATIONS,
    get_current_language,
    set_current_language,
    t,
)


class TestI18n(unittest.TestCase):
    def setUp(self):
        set_current_language("en")

    def tearDown(self):
        set_current_language("en")

    def test_supported_languages_count(self):
        expected_langs = {"en", "ru", "de", "fr", "es", "it", "pt", "pl", "zh", "ja"}
        self.assertEqual(set(SUPPORTED_LANGUAGES.keys()), expected_langs)
        self.assertEqual(set(TRANSLATIONS.keys()), expected_langs)

    def test_key_coverage_across_all_languages(self):
        en_keys = set(TRANSLATIONS["en"].keys())
        # Ensure en has all critical keys
        critical_keys = {
            "app_name",
            "app_subtitle",
            "tab_conn",
            "tab_folders",
            "tab_settings",
            "tab_log",
            "btn_save_apply",
            "btn_close",
            "status_ready",
            "status_synced",
            "status_syncing",
            "tray_open_folder",
            "tray_copy_link",
            "notify_file_uploaded",
            "notify_cleanup_title",
            "notify_cleanup_msg",
            "notify_conflict_title",
            "notify_conflict_msg",
            "settings_file_ret_label",
            "settings_lang_label",
            "settings_backup_header",
        }
        self.assertTrue(critical_keys.issubset(en_keys))

        for lang, trans_dict in TRANSLATIONS.items():
            lang_keys = set(trans_dict.keys())
            missing = en_keys - lang_keys
            self.assertEqual(
                missing,
                set(),
                f"Language '{lang}' is missing translation keys: {missing}",
            )

    def test_switching_language(self):
        set_current_language("ru")
        self.assertEqual(get_current_language(), "ru")
        self.assertEqual(t("app_name"), "DropFile")
        self.assertIn("Сохранить", t("btn_save_apply"))

        set_current_language("de")
        self.assertEqual(get_current_language(), "de")
        self.assertIn("Speichern", t("btn_save_apply"))

        set_current_language("zh")
        self.assertEqual(get_current_language(), "zh")
        self.assertIn("保存", t("btn_save_apply"))

    def test_fallback_to_english(self):
        set_current_language("de")
        # If a non-existent key is requested, return key itself
        self.assertEqual(t("non_existent_key_xyz"), "non_existent_key_xyz")

        # Unknown language should fall back cleanly
        set_current_language("unknown_lang")
        self.assertEqual(t("status_ready"), "Ready")

    def test_formatting_placeholders(self):
        set_current_language("en")
        msg = t("notify_cleanup_msg", days=30, count=5)
        self.assertIn("30 days", msg)
        self.assertIn("5", msg)

        set_current_language("ru")
        msg_ru = t("notify_cleanup_msg", days=14, count=3)
        self.assertIn("14 дн.", msg_ru)
        self.assertIn("3", msg_ru)

    def test_config_language_property(self):
        temp_dir = Path(tempfile.mkdtemp())
        try:
            config = Config(temp_dir)
            self.assertEqual(config.language, "en")
            self.assertEqual(get_current_language(), "en")

            config.language = "fr"
            self.assertEqual(config.language, "fr")
            self.assertEqual(get_current_language(), "fr")
            self.assertIn("Enregistrer", t("btn_save_apply"))
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_disk_space_keys_across_all_languages(self):
        for lang in SUPPORTED_LANGUAGES:
            tbl = TRANSLATIONS.get(lang, {})
            self.assertIn("disk_space_free", tbl, f"Missing disk_space_free in {lang}")
            self.assertIn("disk_space_short", tbl, f"Missing disk_space_short in {lang}")
            txt = t("disk_space_short", lang=lang, free="142.5 GB", total="500 GB")
            self.assertIn("142.5 GB", txt)
            self.assertIn("500 GB", txt)

    def test_speed_window_geometry_config(self):
        temp_dir = Path(tempfile.mkdtemp())
        try:
            config = Config(temp_dir)
            self.assertEqual(config.speed_window_geometry, "660x580")
            config.speed_window_geometry = "720x600+100+100"
            config.save()

            loaded = Config(temp_dir)
            self.assertEqual(loaded.speed_window_geometry, "720x600+100+100")
        finally:
            import shutil
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
