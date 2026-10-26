"""新核心執行設定；帳號偏好仍由既有持久化服務管理。"""
from dataclasses import dataclass


@dataclass(frozen=True)
class ApplicationConfiguration:
    event_capacity: int = 512
    events_per_tick: int = 64

    def __post_init__(self):
        if (type(self.event_capacity) is not int or
                not 1 <= self.event_capacity <= 65536 or
                type(self.events_per_tick) is not int or
                not 1 <= self.events_per_tick <= self.event_capacity):
            raise ValueError('invalid_application_configuration')
