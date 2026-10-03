import unittest

from dual_spark.language import msg, resolve_language, set_language


class LanguageTests(unittest.TestCase):
    def test_explicit_choice_overrides_locale(self):
        env = {"LANG": "ru_RU.UTF-8"}
        self.assertEqual(resolve_language("en", env), "en")
        self.assertEqual(resolve_language("ru", {"LANG": "en_US.UTF-8"}), "ru")

    def test_auto_uses_locale_or_environment_override(self):
        self.assertEqual(resolve_language("auto", {"LANG": "ru_RU.UTF-8"}), "ru")
        self.assertEqual(resolve_language("auto", {"LANG": "en_US.UTF-8"}), "en")
        self.assertEqual(resolve_language("auto", {"CONNECT_DUAL_SPARK_LANG": "ru", "LANG": "en_US.UTF-8"}), "ru")

    def test_message_switches_without_changing_other_state(self):
        try:
            set_language("ru")
            self.assertEqual(msg("Ready", "Готово"), "Готово")
            set_language("en")
            self.assertEqual(msg("Ready", "Готово"), "Ready")
        finally:
            set_language("en")


if __name__ == "__main__":
    unittest.main()
