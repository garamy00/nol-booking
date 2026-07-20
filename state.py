"""좌석 묶음의 상태 변화를 추적해 신규 항목만 골라낸다."""

from seats import SeatGroup


class SeatState:
    """직전 회차에 살아있던 묶음을 기억해 신규 묶음만 반환한다."""

    def __init__(self) -> None:
        self._alive: set[tuple] = set()

    def new_groups(self, current: list[SeatGroup]) -> list[SeatGroup]:
        """이번 회차에서 직전 대비 새로 나타난 묶음만 반환한다.

        내부 상태를 이번 회차 기준으로 갱신하므로, 사라졌다 다시 나타난
        묶음은 다시 신규로 취급된다.
        """
        current_keys = {group.key() for group in current}
        fresh = [group for group in current if group.key() not in self._alive]
        self._alive = current_keys
        return fresh
