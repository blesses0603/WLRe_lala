import unittest
from types import SimpleNamespace
from unittest.mock import patch
import tkinter as tk

from wlre.ui.emoji_picker import EmojiPicker
from wlre.ui.chat_ui import ChatPanel


class SinglePageEmojiPicker(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as error:
            self.skipTest(str(error))
        self.addCleanup(self.root.destroy)
        self.root.geometry('640x480+20+20')

    def images(self, count=64):
        image = tk.PhotoImage(master=self.root, width=40, height=40)
        image.put('#f0c040', to=(0, 0, 40, 40))
        return SimpleNamespace(catalog={str(i): {} for i in range(1, count + 1)},
                               get=lambda token, size: image)

    def test_all_ids_visible_or_scrollable_and_insert_only(self):
        selected = []
        picker = EmojiPicker(self.root, self.images(), selected.append)
        self.root.update()
        self.assertEqual([b.emoji_token for b in picker.buttons],
                         [f'[Emoji{i}]' for i in range(1, 65)])
        for button in picker.buttons:
            self.assertTrue(button.winfo_ismapped())
            button.invoke()
        self.assertEqual(selected, [f'[Emoji{i}]' for i in range(1, 65)])
        # Resize to a small viewport: every item remains in the same list.
        picker.geometry('280x240')
        self.root.update()
        self.assertLess(picker._columns, 8)
        self.assertEqual(len(picker.buttons), 64)
        self.assertGreater(picker.grid_frame.winfo_height(), picker.canvas.winfo_height())
        picker.canvas.yview_moveto(1)
        self.root.update()
        last = picker.buttons[-1]
        self.assertLess(last.winfo_y(), picker.canvas.canvasy(picker.canvas.winfo_height()))
        self.assertGreaterEqual(last.winfo_x(), 0)
        self.assertLessEqual(last.winfo_x() + last.winfo_width(), picker.canvas.winfo_width())
        picker._show_focused(SimpleNamespace(widget=picker.buttons[0]))
        self.assertLessEqual(picker.canvas.canvasy(0), picker.buttons[0].winfo_y())
        picker.destroy()

    def test_high_dpi_filter_empty_and_repeated_open(self):
        self.root.tk.call('tk', 'scaling', 2.5)
        images = self.images(50)
        images.catalog['51'] = {'available': False}
        images.catalog['52'] = {'show_in_list': False}
        picker = EmojiPicker(self.root, images, lambda token: None)
        self.root.update()
        self.assertEqual(len(picker.buttons), 50)
        self.assertGreater(picker._columns, 0)
        for button in picker.buttons:
            self.assertLessEqual(button.winfo_x() + button.winfo_width(),
                                 picker.canvas.winfo_width())
        picker.destroy()
        empty = EmojiPicker(self.root, self.images(0), lambda token: None)
        self.root.update()
        self.assertFalse(empty.buttons)
        empty.destroy()
        # Use the real panel entry; selecting never invokes the send action.
        with patch('wlre.ui.chat_ui.EmojiImages') as cls:
            cls.return_value = self.images(50)
            cls.return_value.close = lambda: None
            panel = ChatPanel(self.root, SimpleNamespace())
            panel.pack()
            panel.show_emoji_picker()
            first = panel.emoji_picker
            panel.show_emoji_picker()
            self.assertIs(panel.emoji_picker, first)
            self.root.update()
            first.buttons[-1].invoke()
            self.assertEqual(panel.text.get(), '[Emoji50]')
            first.destroy()
            panel.show_emoji_picker()
            self.assertIsNot(panel.emoji_picker, first)
            panel.destroy()


if __name__ == '__main__':
    unittest.main()
