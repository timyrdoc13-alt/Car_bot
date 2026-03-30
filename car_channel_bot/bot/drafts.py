from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ManualDraft:
    photo_file_ids: list[str] = field(default_factory=list)
    raw_text: str = ""


class DraftStore:
    def __init__(self) -> None:
        self._by_user: dict[int, ManualDraft] = {}

    def get(self, user_id: int) -> ManualDraft:
        if user_id not in self._by_user:
            self._by_user[user_id] = ManualDraft()
        return self._by_user[user_id]

    def clear(self, user_id: int) -> None:
        self._by_user.pop(user_id, None)
