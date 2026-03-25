from __future__ import annotations

Rect = tuple[float, float, float, float]


class CropStore:
    """페이지별 크롭 rect를 관리한다.

    페이지별 설정이 없으면 default를 반환한다.
    default도 없으면 None을 반환한다.
    """

    def __init__(self) -> None:
        self._default: Rect | None = None
        self._overrides: dict[int, Rect] = {}

    def set_default(self, rect: Rect) -> None:
        self._default = rect

    def set(self, page_number: int, rect: Rect) -> None:
        self._overrides[page_number] = rect

    def get(self, page_number: int) -> Rect | None:
        return self._overrides.get(page_number, self._default)

    def has_override(self, page_number: int) -> bool:
        return page_number in self._overrides

    def all_rects(self, page_count: int) -> dict[int, Rect | None]:
        return {p: self.get(p) for p in range(1, page_count + 1)}
