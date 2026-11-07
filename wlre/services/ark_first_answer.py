"""Conservative first-encounter arithmetic, never a server answer key.

Only complete, unambiguous integer arithmetic templates are accepted. No eval,
network requests, approximate matching, general knowledge or language-model guesses.
"""
from fractions import Fraction
import re

_NUMBER = r'(?:0|[1-9][0-9]{0,8})'
_QUESTION = re.compile(r'(?:請問)?(?P<expression>.+?)(?:等於多少|是等於多少|等於|=)[？?]')
_SUM = re.compile(_NUMBER + r'(?:[+-]' + _NUMBER + r'){1,15}')
_PRODUCT = re.compile(r'(' + _NUMBER + r')(乘上|乘以|×|\*|除以|÷)(' + _NUMBER + r')(?:再除以(' + _NUMBER + r'))?')
_ADD = re.compile(r'(' + _NUMBER + r')(?:加上|加)(' + _NUMBER + r')(?:的話)?')
_LABEL = re.compile(r'-?(?:0|[1-9][0-9]{0,12})')


def solve(question):
    """Return the unique matching text ID, or None. Caller verifies provenance."""
    text = question.get('text')
    labels = question.get('labels'); options = question.get('options')
    if (not isinstance(text, str) or len(text) > 256
            or not isinstance(labels, list) or len(labels) != 4
            or not isinstance(options, list) or len(options) != 4
            or any(type(i) is not int or i <= 0 for i in options)
            or len(set(options)) != 4):
        return None
    match = _QUESTION.fullmatch(text)
    if not match:
        return None
    expr = match['expression']
    if _SUM.fullmatch(expr):
        result = Fraction(sum(int(term) for term in re.findall(r'[+-]?[0-9]+', expr)))
    elif (parts := _ADD.fullmatch(expr)):
        result = Fraction(int(parts[1]) + int(parts[2]))
    elif (parts := _PRODUCT.fullmatch(expr)):
        a, operation, b, divisor = parts.groups()
        a, b = int(a), int(b)
        if operation in ('除以', '÷'):
            if not b:
                return None
            result = Fraction(a, b)
        else:
            result = Fraction(a * b)
        if divisor is not None:
            if not int(divisor):
                return None
            result /= int(divisor)
    else:
        return None
    # Avoid rounding, units, alternate notations and duplicate numeric answers.
    if result.denominator != 1:
        return None
    if any(not isinstance(label, str) or not _LABEL.fullmatch(label.strip())
           for label in labels):
        return None
    matches = [option for option, label in zip(options, labels)
               if int(label.strip()) == result]
    return matches[0] if len(matches) == 1 else None
