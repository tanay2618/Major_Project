"""
Verhoeff checksum, the check-digit scheme used for the 12th digit of an Aadhaar number.

It catches every single-digit typo and almost all swaps of adjacent digits, so an
invented or hand-edited number fails it about 90% of the time. It is NOT proof that a
number was issued to anyone: roughly 1 in 10 random numbers passes.
"""

# Multiplication table of the dihedral group D5
_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
# Permutation table
_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
# Inverse table
_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def validate(number: str) -> bool:
    """True if the digit string (including its check digit) passes the Verhoeff test."""
    if not number or not number.isdigit():
        return False
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[i % 8][int(ch)]]
    return c == 0


def generate_check_digit(number: str) -> str:
    """Check digit to append to `number` (without one) so that it validates."""
    if not number.isdigit():
        raise ValueError("digits only")
    c = 0
    for i, ch in enumerate(reversed(number)):
        c = _D[c][_P[(i + 1) % 8][int(ch)]]
    return str(_INV[c])


def is_valid_aadhaar_number(number: str) -> bool:
    """12 digits, first digit 2-9 (UIDAI never issues numbers starting with 0 or 1), valid checksum."""
    digits = "".join(number.split())
    return len(digits) == 12 and digits.isdigit() and digits[0] in "23456789" and validate(digits)
