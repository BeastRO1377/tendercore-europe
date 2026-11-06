import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

class DesignSystemContract(unittest.TestCase):
    def test_design_system_is_loaded_after_legacy_layout(self):
        html = (ROOT/'static/index.html').read_text()
        self.assertLess(html.index('/static/styles.css'),html.index('/static/design-system.css'))

    def test_single_source_of_truth_for_control_dimensions(self):
        css = (ROOT/'static/design-system.css').read_text()
        for token in ('--ds-control-height: 40px;', '--ds-checkbox-size: 18px;',
                      '--ds-line-height: 20px;', '--ds-unit: 4px;'):
            self.assertIn(token,css)
        self.assertIn('.app .form-grid label > span',css)
        self.assertIn('min-height:40px',css)

    def test_mobile_nav_keyboard_and_backdrop(self):
        html = (ROOT/'static/index.html').read_text()
        js = (ROOT/'static/app.js').read_text()
        for id_ in ('mobile-menu-toggle','mobile-nav-backdrop','primary-sidebar'):
            self.assertIn(f'id="{id_}"',html)
        for snippet in ('setMobileNavigation(false)','e.key===\'Escape\'',
                        "'aria-expanded'", "dataset.page"):
            self.assertIn(snippet,js)

    def test_language_and_theme_modes(self):
        html = (ROOT/'static/index.html').read_text()
        for name in ('system','light','dark','ru','en'):
            self.assertIn(f'value="{name}"',html)
        js=(ROOT/'static/app.js').read_text()
        for tag in ("DICT.ru.open_menu", "DICT.en.open_menu", "DICT.ru.tiles_label", "DICT.en.list_label"):
            self.assertIn(tag,js)

if __name__=='__main__':unittest.main()
