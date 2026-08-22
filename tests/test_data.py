from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]

ORDERS_FILE = ROOT / "data" / "orders.csv"
MACHINES_FILE = ROOT / "data" / "machines.csv"
OPERATIONS_FILE = ROOT / "data" / "operations.csv"


def test_orders():
    df = pd.read_csv(ORDERS_FILE)

    assert df.shape[1] == 4  # 4 colonnes attendues
    assert len(df) > 0
    assert df["order_id"].is_unique
    assert df["quantity"].gt(0).all()
    assert df["deadline"].gt(0).all()
    assert df["product_id"].isin(["P1", "P2", "P3"]).all()


def test_machines():
    df = pd.read_csv(MACHINES_FILE)

    assert df.shape[1] == 3  # 3 colonnes attendues, peu importe le nombre de machines
    assert len(df) > 0
    assert df["machine_id"].is_unique
    assert df["capacity_hours_per_day"].gt(0).all()


def test_operations():
    df = pd.read_csv(OPERATIONS_FILE)

    assert df.shape[1] == 5  # 5 colonnes attendues
    assert len(df) > 0
    assert df["operation_id"].is_unique
    assert df["duration"].gt(0).all()
    assert df["compatible_machines"].notna().all()


def test_operation_products():
    orders = pd.read_csv(ORDERS_FILE)
    operations = pd.read_csv(OPERATIONS_FILE)

    valid_products = set(orders["product_id"])
    operation_products = set(operations["product_id"])

    assert operation_products.issubset(valid_products)