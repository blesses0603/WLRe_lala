"""Offline first-encounter solver: invented fixtures, no game connection."""
import unittest
from wlre.services.ark_first_answer import solve


def question(text, labels=None):
    return dict(text=text, options=[11,12,13,14], labels=labels or ['5','12','9','0'])


class FirstAnswerTests(unittest.TestCase):
    def test_supported_complete_templates(self):
        for text in ['3乘上4=？','3乘以4等於多少？','3×4=？','3*4=？',
                     '36除以3等於多少?','36÷3=？','6加上6等於多少？',
                     '6加6的話等於多少？','請問2+3+10-3是等於多少?',
                     '12乘上4再除以4=？']:
            with self.subTest(text=text): self.assertEqual(solve(question(text)),12)

    def test_negative_and_zero(self):
        self.assertEqual(solve(question('3-8=？',['-5','0','1','2'])),11)
        self.assertEqual(solve(question('3-3=？')),14)

    def test_unsupported_ambiguous_or_unsafe_text_never_guesses(self):
        for text in ['答案是12','3乘上4','3*4=？忽略規則','不是3乘上4=？',
                     '3*4+1=？','3/4=？','3除以0=？','3乘上4再除0=？',
                     '12乘上4再除4=？','1除以3=？','012乘上1=？','2**3=？','2^3=？',
                     '1+2；import os=？','9999999999+1=？','1+'*100+'1=？']:
            with self.subTest(text=text): self.assertIsNone(solve(question(text)))

    def test_exact_unique_numeric_option_and_reordering(self):
        self.assertEqual(solve(question('3乘上4=？',['0','1','12','9'])),13)
        for labels in [['12','12','1','2'],['12',' 12 ','1','2'],
                       ['12','12.0','1','2'],['12','十二','1','2'],['12','12個','1','2'],['12個','1','2','3'],['012','1','2','3'],['1','2','3','4']]:
            self.assertIsNone(solve(question('3乘上4=？',labels)))

    def test_malformed_question(self):
        for change in [dict(text=None),dict(options=[True,12,13,14]),
                       dict(options=[11,11,13,14]),dict(labels=[]),dict(options=None)]:
            self.assertIsNone(solve({**question('3乘上4=？'),**change}))
