from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Product:
    id: str
    name: str


@dataclass(frozen=True)
class Machine:
    id: str
    name: str


@dataclass(frozen=True)
class Order:
    id: str
    product_id: str
    quantity: int
    deadline: float


@dataclass(frozen=True)
class Operation:
    id: str
    order_id: str
    product_id: str
    operation_type: str
    duration: float
    compatible_machines: tuple[str, ...]