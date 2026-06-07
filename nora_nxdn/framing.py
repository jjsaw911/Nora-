"""NXDN frame synchronisation.

NXDN bursts begin with a Frame Sync Word (FSW). DSD detects the FSW with a
*sign-only* correlation: each 4FSK symbol is reduced to the sign of its
deviation (positive -> ``'1'``, negative -> ``'3'``) and the resulting 18-symbol
string is compared against the known patterns below.

The four base patterns (and their inverted-polarity twins, for when the receiver
sees the signal upside-down) come straight from DSD's ``include/dsd.h``:

    NXDN_MS_DATA_SYNC      313133113131111333
    NXDN_MS_VOICE_SYNC     313133113131113133
    NXDN_BS_DATA_SYNC      313133113131111313
    NXDN_BS_VOICE_SYNC     313133113131113113

"MS" = mobile/subscriber (inbound), "BS" = base station (outbound). The
inverted strings are produced by swapping ``1`` <-> ``3``.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterator, List, Optional, Sequence

SYNC_LEN = 18  # symbols compared by the sign-only correlator


class SyncType(Enum):
    """Which NXDN sync word matched, including polarity."""

    BS_VOICE = "BS_VOICE"
    BS_DATA = "BS_DATA"
    MS_VOICE = "MS_VOICE"
    MS_DATA = "MS_DATA"


# Canonical (non-inverted) sign patterns, '1' = positive symbol, '3' = negative.
_PATTERNS = {
    SyncType.MS_DATA: "313133113131111333",
    SyncType.MS_VOICE: "313133113131113133",
    SyncType.BS_DATA: "313133113131111313",
    SyncType.BS_VOICE: "313133113131113113",
}


def _invert(pattern: str) -> str:
    return pattern.translate(str.maketrans("13", "31"))


# Pre-compute the {pattern-string: (type, inverted?)} lookup once.
_LOOKUP = {}
for _t, _p in _PATTERNS.items():
    _LOOKUP[_p] = (_t, False)
    _LOOKUP[_invert(_p)] = (_t, True)


@dataclass(frozen=True)
class SyncMatch:
    """A detected frame sync.

    Attributes:
        position: index of the *first* sync symbol within the input sequence.
        sync_type: which sync word matched.
        inverted: ``True`` if the signal polarity was inverted.
        errors: number of mismatched symbols (0 for an exact match).
    """

    position: int
    sync_type: SyncType
    inverted: bool
    errors: int


def symbols_to_sign_string(symbols: Sequence[float]) -> str:
    """Reduce 4FSK symbols to the DSD sign string (``'1'`` / ``'3'``)."""
    return "".join("1" if s > 0 else "3" for s in symbols)


def _match_window(window: str, max_errors: int) -> Optional[SyncMatch]:
    # Exact hit is the common case and cheap to check first.
    hit = _LOOKUP.get(window)
    if hit is not None:
        return SyncMatch(0, hit[0], hit[1], 0)
    if max_errors <= 0:
        return None
    best: Optional[SyncMatch] = None
    for pat, (stype, inv) in _LOOKUP.items():
        errs = sum(1 for a, b in zip(window, pat) if a != b)
        if errs <= max_errors and (best is None or errs < best.errors):
            best = SyncMatch(0, stype, inv, errs)
    return best


def find_sync(
    symbols: Sequence[float], *, max_errors: int = 1, start: int = 0
) -> Optional[SyncMatch]:
    """Find the first frame sync at or after ``start``.

    ``symbols`` is a sequence of soft 4FSK symbol values (sign is all that
    matters). ``max_errors`` allows fuzzy matching to ride out a few bit slips.
    Returns ``None`` if no sync is found.
    """
    signs = symbols_to_sign_string(symbols)
    n = len(signs)
    for i in range(max(start, 0), n - SYNC_LEN + 1):
        m = _match_window(signs[i : i + SYNC_LEN], max_errors)
        if m is not None:
            return SyncMatch(i, m.sync_type, m.inverted, m.errors)
    return None


def iter_sync(
    symbols: Sequence[float], *, max_errors: int = 1
) -> Iterator[SyncMatch]:
    """Yield every non-overlapping frame sync in ``symbols``."""
    pos = 0
    n = len(symbols)
    while pos <= n - SYNC_LEN:
        m = find_sync(symbols, max_errors=max_errors, start=pos)
        if m is None:
            return
        yield m
        pos = m.position + SYNC_LEN


def encode_sync_symbols(
    sync_type: SyncType, *, inverted: bool = False, level: float = 3.0
) -> List[float]:
    """Build the ideal 4FSK symbols for a sync word (useful for tests/tooling).

    ``'1'`` -> ``+level``, ``'3'`` -> ``-level``.
    """
    pat = _PATTERNS[sync_type]
    if inverted:
        pat = _invert(pat)
    return [level if c == "1" else -level for c in pat]
