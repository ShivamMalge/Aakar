"""Page label and page index (2A.6).

**Two separate fields, always. Never conflated, never inferred from one another.**

They diverge the moment a document has front matter, and textbooks always do:

======  ==========  =========================================
index   label       what it is
======  ==========  =========================================
0       ``i``       roman-numbered preface
1       ``ii``      preface
2       ``1``       first body page
3       ``2``       body
======  ==========  =========================================

Chapter reprints make it worse: a chapter extracted from a book may start at label ``247``
while its index is ``0``, and a two-volume set can restart at ``1`` halfway through, so
labels are not even unique within one document.

Which one to use is not a matter of taste:

* **Citations render the LABEL.** D6 requires ``[p. N]``, and the student is holding the
  book. A citation to "page 3" that means the third PDF page is wrong when the book calls
  that page "vii", and wrong in a way the reader cannot detect.
* **Internal addressing uses the INDEX.** It is dense, 0-based, unique and total, which is
  what a chunk pointer needs. A label is none of those.

Inferring one from the other is the specific failure this module exists to prevent. There
is no arithmetic that recovers a label from an index — the mapping is data the publisher
supplied, and guessing "index + 1" is right often enough to look correct and wrong exactly
where it matters.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageRef:
    """One page, in both spaces at once.

    Constructed together so neither can be dropped in passing. A function that takes only
    an ``int`` cannot tell you which space it meant.
    """

    #: 0-based physical position. Dense, unique, total. For addressing.
    index: int
    #: The publisher's own label for this page. For display and citation.
    label: str

    def __post_init__(self) -> None:
        if self.index < 0:
            raise ValueError(f"page index must be non-negative, got {self.index}")
        if not self.label:
            raise ValueError(f"page {self.index} has an empty label")

    @property
    def citation(self) -> str:
        """What D6 renders: ``[p. vii]``, not ``[p. 1]``."""
        return f"[p. {self.label}]"


class PageMap:
    """The label-for-index mapping a document declared, kept whole.

    Not a dict comprehension at the call site: labels repeat across a two-volume PDF, so
    label-to-index is not a function, and code that builds one silently loses pages.
    """

    def __init__(self, labels: tuple[str, ...] | list[str]) -> None:
        if not labels:
            raise ValueError("a document with no pages has no page map")
        self._labels = tuple(labels)

    def __len__(self) -> int:
        return len(self._labels)

    @property
    def labels(self) -> tuple[str, ...]:
        return self._labels

    def ref(self, index: int) -> PageRef:
        if not 0 <= index < len(self._labels):
            raise IndexError(f"page index {index} outside 0..{len(self._labels) - 1}")
        return PageRef(index=index, label=self._labels[index])

    def refs(self) -> tuple[PageRef, ...]:
        return tuple(self.ref(i) for i in range(len(self._labels)))

    def indices_for_label(self, label: str) -> tuple[int, ...]:
        """Every index carrying this label — plural, because labels are not unique.

        Returning a tuple rather than an ``int`` is the point: a caller that wants "the"
        page for a label has to confront the possibility that there is more than one.
        """
        return tuple(i for i, value in enumerate(self._labels) if value == label)

    @property
    def diverges(self) -> bool:
        """True when the labels are anything other than 1, 2, 3, …

        Worth surfacing at ingest: a document where they diverge is one where conflating
        the two spaces produces citations that are quietly wrong.
        """
        return self._labels != tuple(str(i + 1) for i in range(len(self._labels)))
