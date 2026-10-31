import re
from pathlib import Path
import string
import unittest
from spark_link.translations import MESSAGES, translate

class TranslationTests(unittest.TestCase):
    def test_supported_languages_have_real_translations(self):
        self.assertEqual(translate('Обзор','en'),'Overview')
        self.assertEqual(translate('Обзор','de'),'Übersicht')
        self.assertEqual(translate('Обзор','es'),'Resumen')
        self.assertEqual(translate('Обзор','ru'),'Обзор')

    def test_all_qml_russian_source_text_is_in_catalog(self):
        root=Path(__file__).parents[1]/'spark_link/qml'
        sources=set()
        for file in root.glob('*.qml'):
            for literal in re.findall(r'"((?:\\.|[^"\\])*)"',file.read_text()):
                if re.search('[А-Яа-яЁё]',literal): sources.add(literal)
        self.assertEqual(sources-set(MESSAGES),set(),'Missing visible UI translations')

    def test_all_languages_preserve_format_fields(self):
        formatter=string.Formatter()
        for source,translations in MESSAGES.items():
            expected={field for _,field,_,_ in formatter.parse(source) if field}
            self.assertEqual(len(translations),3)
            for translated in translations:
                self.assertTrue(translated.strip(),source)
                self.assertEqual({field for _,field,_,_ in formatter.parse(translated) if field},expected,source)
