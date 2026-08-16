import unittest
from unittest import mock

import calc_overlay


class NormalizeClipboardNumberTests(unittest.TestCase):
    def test_accepts_plain_number(self):
        self.assertEqual("123.45", calc_overlay._normalize_clipboard_number(" 123.45\r\n"))

    def test_removes_valid_thousands_separators(self):
        self.assertEqual("-1234567.8", calc_overlay._normalize_clipboard_number("-1,234,567.8"))

    def test_accepts_exponent_notation(self):
        self.assertEqual("1.2e-3", calc_overlay._normalize_clipboard_number("1.2e-3"))

    def test_rejects_non_numeric_text(self):
        self.assertIsNone(calc_overlay._normalize_clipboard_number("12 + 3"))

    def test_rejects_invalid_thousands_separators(self):
        self.assertIsNone(calc_overlay._normalize_clipboard_number("12,34"))

    def test_rejects_non_ascii_digits_that_python_cannot_evaluate(self):
        self.assertIsNone(calc_overlay._normalize_clipboard_number("１２３"))


class PasteClipboardNumberTests(unittest.TestCase):
    def setUp(self):
        calc_overlay._frame_hwnd = None

    def test_inserts_at_caret_in_expression(self):
        calc_overlay._text = "10+"
        calc_overlay._caret = 3

        with mock.patch.object(calc_overlay, "_read_clipboard_text", return_value="25"):
            calc_overlay._paste_clipboard_number(None)

        self.assertEqual("10+25", calc_overlay._text)
        self.assertEqual(5, calc_overlay._caret)

    def test_inserts_before_equals_after_calculation(self):
        calc_overlay._text = "10+5 = 15"
        calc_overlay._caret = len(calc_overlay._text)

        with mock.patch.object(calc_overlay, "_read_clipboard_text", return_value="25"):
            calc_overlay._paste_clipboard_number(None)

        self.assertEqual("10+525", calc_overlay._text)
        self.assertEqual(len(calc_overlay._text), calc_overlay._caret)

    def test_ignores_non_numeric_clipboard_without_changing_expression(self):
        calc_overlay._text = "10+5 = 15"
        calc_overlay._caret = len(calc_overlay._text)

        with mock.patch.object(calc_overlay, "_read_clipboard_text", return_value="hello"):
            calc_overlay._paste_clipboard_number(None)

        self.assertEqual("10+5 = 15", calc_overlay._text)
        self.assertEqual(len(calc_overlay._text), calc_overlay._caret)


class CopyDisplayedResultTests(unittest.TestCase):
    def test_extracts_only_result(self):
        self.assertEqual("15", calc_overlay._get_displayed_result("10+5 = 15"))

    def test_does_not_extract_uncomputed_expression(self):
        self.assertIsNone(calc_overlay._get_displayed_result("10+5"))

    def test_does_not_extract_error(self):
        self.assertIsNone(calc_overlay._get_displayed_result("10/0 = エラー"))

    def test_copies_result_text(self):
        calc_overlay._text = "10/4 = 2.5"

        with mock.patch.object(calc_overlay, "_write_clipboard_text", return_value=True) as write:
            calc_overlay._copy_displayed_result(None)

        write.assert_called_once_with(None, "2.5")

    def test_does_not_overwrite_clipboard_without_result(self):
        calc_overlay._text = "10/4"

        with mock.patch.object(calc_overlay, "_write_clipboard_text") as write:
            calc_overlay._copy_displayed_result(None)

        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
