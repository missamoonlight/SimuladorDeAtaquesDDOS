"""Module 1: virtual legitimate traffic at the protocol's baseline level."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NormalTraffic:
    users: float
    requests_per_user_second: float = 0.2

    @classmethod
    def from_capacity(cls, capacity_rps: float, requests_per_user_second: float = 0.2) -> "NormalTraffic":
        """The protocol sets baseline users to 20% of estimated capacity."""
        return cls(users=max(0.0, capacity_rps) * 0.20,
                   requests_per_user_second=requests_per_user_second)

    @property
    def demand_rps(self) -> float:
        return self.users * self.requests_per_user_second
