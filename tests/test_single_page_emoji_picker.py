import unittest
from types import SimpleNamespace
from unittest.mock import patch
import tkinter as tk
from wlre.ui.emoji_picker import EmojiPicker, fitted_columns, preferred_grid
from wlre.ui.chat_ui import ChatPanel


class GridPlanning(unittest.TestCase):
    def test_52_fit_without_hiding_in_small_and_large_rectangles(self):
        for width, height in [(480, 360), (600, 480), (1000, 700)]:
            columns = fitted_columns(52, width, height, 44, 48)
            self.assertIsNotNone(columns)
            self.assertLessEqual(columns * 44, width)
            self.assertLessEqual(((52 + columns - 1) // columns) * 48, height)

    def test_impossible_screen_is_explicit(self):
        self.assertIsNone(fitted_columns(52, 120, 100, 44, 48))
        self.assertIsNone(preferred_grid(52, 44, 48, 120, 100))


class SinglePageEmojiPicker(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.addCleanup(self.root.destroy)
        self.root.geometry('640x480+20+20')

    def images(self, count=52):
        def get(token, size):
            image = tk.PhotoImage(master=self.root, width=size, height=size)
            image.put('#f0c040', to=(0, 0, size, size))
            return image
        return SimpleNamespace(catalog={str(i): {} for i in range(1, count + 1)}, get=get)

    def assert_all_visible(self, picker, count):
        self.root.update()
        self.assertEqual(len(picker.buttons), count)
        for button in picker.buttons:
            self.assertTrue(button.winfo_ismapped())
            self.assertGreaterEqual(button.winfo_x(), 0)
            self.assertGreaterEqual(button.winfo_y(), 0)
            self.assertLessEqual(button.winfo_x() + button.winfo_width(), picker.grid_frame.winfo_width())
            self.assertLessEqual(button.winfo_y() + button.winfo_height(), picker.grid_frame.winfo_height())
            self.assertGreaterEqual(button.winfo_width(), button.winfo_reqwidth())
            self.assertGreaterEqual(button.winfo_height(), button.winfo_reqheight())
        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)
        self.assertFalse(any(isinstance(w, (tk.Canvas, tk.Scrollbar, tk.Label,
                                          ttk.Scrollbar, ttk.Label))
                             for w in descendants(picker)))

    def test_all_52_ids_visible_without_scrollbar_at_each_size(self):
        selected = []
        picker = EmojiPicker(self.root, self.images(), selected.append)
        self.assert_all_visible(picker, 52)
        for geometry in ['480x360', '900x680', '600x480', '280x240']:
            picker.geometry(geometry)
            self.assert_all_visible(picker, 52)
        for button in picker.buttons:
            button.invoke()
        self.assertEqual(selected, [f'[Emoji{i}]' for i in range(1, 53)])
        picker.destroy()

    def test_high_dpi_filter_empty_and_repeated_open(self):
        self.root.tk.call('tk', 'scaling', 2.5)
        images = self.images()
        images.catalog['53'] = {'available': False}
        images.catalog['54'] = {'show_in_list': False}
        picker = EmojiPicker(self.root, images, lambda token: None)
        self.assert_all_visible(picker, 52)
        picker.geometry('480x360')
        self.assert_all_visible(picker, 52)
        picker.destroy()
        empty = EmojiPicker(self.root, self.images(0), lambda token: None)
        self.root.update()
        self.assertFalse(empty.buttons)
        empty.destroy()
        with patch('wlre.ui.chat_ui.EmojiImages') as cls:
            cls.return_value = self.images()
            cls.return_value.close = lambda: None
            panel = ChatPanel(self.root, SimpleNamespace())
            panel.pack()
            panel.show_emoji_picker()
            first = panel.emoji_picker
            panel.show_emoji_picker()
            self.assertIs(panel.emoji_picker, first)
            self.root.update()
            first.buttons[-1].invoke()
            self.assertEqual(panel.text.get(), '[Emoji52]')
            first.destroy()
            panel.show_emoji_picker()
            self.assertIsNot(panel.emoji_picker, first)
            panel.destroy()


from tkinter import ttk
if __name__ == '__main__':
    unittest.main()
