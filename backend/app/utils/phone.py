"""Phone normalization per spec section 5.6.

input  -> strip everything except digits
          drop leading "0" if 11 digits
          if 10 digits -> prepend "91"
          if 12 digits and starts with "91" -> keep
          else -> reject
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_DIGITS = re.compile(r"\D+")


@dataclass(frozen=True)
class PhoneResult:
    ok: bool
    phone: str | None
    reason: str | None = None


def normalize_phone(raw: object) -> PhoneResult:
    if raw is None:
        return PhoneResult(False, None, "empty")
    # Excel may hand us a float like 9167861236.0
    if isinstance(raw, float) and raw.is_integer():
        raw = str(int(raw))
    text = str(raw).strip()
    if not text:
        return PhoneResult(False, None, "empty")
    digits = _DIGITS.sub("", text)
    if not digits:
        return PhoneResult(False, None, "no digits")
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        return PhoneResult(True, "91" + digits)
    if len(digits) == 12 and digits.startswith("91"):
        return PhoneResult(True, digits)
    return PhoneResult(False, None, f"invalid length {len(digits)} after cleanup ({digits})")
