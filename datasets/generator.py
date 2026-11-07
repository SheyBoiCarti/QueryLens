"""Deterministic tricky dataset generator for benchmark evaluation (Contracts C05, C10)."""

from __future__ import annotations

import datetime
from decimal import Decimal
import hashlib
import json
import random
from typing import Any
import sqlalchemy as sa
from sqlalchemy.engine import Connection


def generate_dataset_records(variant: str = "A", seed: int = 42) -> dict[str, list[dict[str, Any]]]:
    """Generate deterministic tricky benchmark records."""
    rng = random.Random(seed + (1000 if variant == "B" else 0))

    # 1. Departments
    departments = [
        {"id": "dept-01", "name": "Engineering", "budget": "500000.00", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "dept-02", "name": "Sales", "budget": "300000.00", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "dept-03", "name": "Marketing", "budget": "200000.00", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "dept-04", "name": "Research", "budget": "150000.00", "created_at": "2024-01-01T00:00:00Z"},  # No expenses trap
    ]

    # 2. Employees
    employees = [
        {"id": "emp-01", "department_id": "dept-01", "name": "Alice Smith", "email": "alice@company.com", "hire_date": "2024-01-15", "salary": "120000.00"},
        {"id": "emp-02", "department_id": "dept-01", "name": "Bob Jones", "email": "bob@company.com", "hire_date": "2024-02-01", "salary": "110000.00"},
        {"id": "emp-03", "department_id": "dept-02", "name": "Charlie Brown", "email": "charlie@company.com", "hire_date": "2024-03-01", "salary": "95000.00"},
        {"id": "emp-04", "department_id": "dept-02", "name": "Dana White", "email": "dana@company.com", "hire_date": "2024-04-01", "salary": "90000.00"},
        {"id": "emp-05", "department_id": "dept-03", "name": "Eve Davis", "email": "eve@company.com", "hire_date": "2024-05-01", "salary": "85000.00"},
    ]

    # 3. Historical assignments (department transfer trap)
    historical_assignments = [
        {"id": "ha-01", "employee_id": "emp-01", "department_id": "dept-02", "start_date": "2023-01-01", "end_date": "2024-01-14"},
        {"id": "ha-02", "employee_id": "emp-01", "department_id": "dept-01", "start_date": "2024-01-15", "end_date": None},
    ]

    # 4. Customers (duplicate name trap: two distinct customers named John Doe)
    customers = [
        {"id": "cust-01", "name": "John Doe", "email": "johndoe1@example.com", "tier": "gold", "created_at": "2024-01-10T10:00:00Z"},
        {"id": "cust-02", "name": "John Doe", "email": "johndoe2@example.com", "tier": "silver", "created_at": "2024-01-15T12:00:00Z"},
        {"id": "cust-03", "name": "Acme Corp", "email": "contact@acme.com", "tier": "platinum", "created_at": "2024-02-01T09:00:00Z"},
        {"id": "cust-04", "name": "Inactive Customer", "email": "inactive@example.com", "tier": "bronze", "created_at": "2024-03-01T08:00:00Z"},
    ]

    # 5. Products (unsold product trap)
    products = [
        {"id": "prod-01", "name": "Analytics Server", "category": "Hardware", "price": "5000.00", "cost": "3000.00", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "prod-02", "name": "QueryLens Pro License", "category": "Software", "price": "1200.00", "cost": "100.00", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "prod-03", "name": "Enterprise Support", "category": "Services", "price": "800.00", "cost": "400.00", "created_at": "2024-01-01T00:00:00Z"},
        {"id": "prod-04", "name": "Legacy Tape Drive", "category": "Hardware", "price": "350.00", "cost": "200.00", "created_at": "2024-01-01T00:00:00Z"},  # Unsold
    ]

    # 6. Orders (fan-out and cancelled order traps)
    amt_1 = "6250.00" if variant == "B" else "6200.00"
    orders = [
        {"id": "ord-01", "customer_id": "cust-01", "order_date": "2024-02-10", "status": "completed", "total_amount": amt_1},
        {"id": "ord-02", "customer_id": "cust-02", "order_date": "2024-02-15", "status": "completed", "total_amount": "1200.00"},
        {"id": "ord-03", "customer_id": "cust-03", "order_date": "2024-03-01", "status": "completed", "total_amount": "5800.00"},
        {"id": "ord-04", "customer_id": "cust-01", "order_date": "2024-03-10", "status": "cancelled", "total_amount": "800.00"},
    ]

    # 7. Line items (orders with multiple lines)
    line_items = [
        {"id": "li-01", "order_id": "ord-01", "product_id": "prod-01", "quantity": 1, "unit_price": "5000.00", "discount": "0.00"},
        {"id": "li-02", "order_id": "ord-01", "product_id": "prod-02", "quantity": 1, "unit_price": "1200.00", "discount": "0.00"},
        {"id": "li-03", "order_id": "ord-02", "product_id": "prod-02", "quantity": 1, "unit_price": "1200.00", "discount": "0.00"},
        {"id": "li-04", "order_id": "ord-03", "product_id": "prod-01", "quantity": 1, "unit_price": "5000.00", "discount": "0.00"},
        {"id": "li-05", "order_id": "ord-03", "product_id": "prod-03", "quantity": 1, "unit_price": "800.00", "discount": "0.00"},
        {"id": "li-06", "order_id": "ord-04", "product_id": "prod-03", "quantity": 1, "unit_price": "800.00", "discount": "0.00"},
    ]

    # 8. Payments (multiple payments per order)
    payments = [
        {"id": "pay-01", "order_id": "ord-01", "payment_date": "2024-02-10", "amount": "3000.00", "payment_method": "credit_card", "status": "settled"},
        {"id": "pay-02", "order_id": "ord-01", "payment_date": "2024-02-11", "amount": "3200.00", "payment_method": "bank_wire", "status": "settled"},
        {"id": "pay-03", "order_id": "ord-02", "payment_date": "2024-02-15", "amount": "1200.00", "payment_method": "credit_card", "status": "settled"},
        {"id": "pay-04", "order_id": "ord-03", "payment_date": "2024-03-01", "amount": "5800.00", "payment_method": "credit_card", "status": "settled"},
    ]

    # 9. Refunds (refund trap)
    refunds = [
        {"id": "ref-01", "payment_id": "pay-01", "refund_date": "2024-02-15", "amount": "500.00", "reason": "Customer discount adjustment"},
    ]

    # 10. Expenses
    expenses = [
        {"id": "exp-01", "department_id": "dept-01", "expense_date": "2024-02-01", "amount": "15000.00", "category": "Cloud Infrastructure"},
        {"id": "exp-02", "department_id": "dept-02", "expense_date": "2024-02-05", "amount": "8000.00", "category": "Travel"},
        {"id": "exp-03", "department_id": "dept-03", "expense_date": "2024-02-20", "amount": "12000.00", "category": "Advertising"},
    ]

    return {
        "departments": departments,
        "employees": employees,
        "historical_assignments": historical_assignments,
        "customers": customers,
        "products": products,
        "orders": orders,
        "line_items": line_items,
        "payments": payments,
        "refunds": refunds,
        "expenses": expenses,
    }


def compute_dataset_hash(data: dict[str, list[dict[str, Any]]]) -> str:
    """Calculate canonical SHA-256 hash of dataset in stable key order."""
    canonical_repr = json.dumps(data, sort_keys=True)
    return hashlib.sha256(canonical_repr.encode("utf-8")).hexdigest()


def seed_dataset(
    conn: Connection,
    variant: str = "A",
    seed: int = 42,
) -> dict[str, Any]:
    """Seed dataset records into a database connection and return counts and hash."""
    data = generate_dataset_records(variant=variant, seed=seed)
    counts: dict[str, int] = {}

    order_of_insertion = [
        "departments",
        "employees",
        "historical_assignments",
        "customers",
        "products",
        "orders",
        "line_items",
        "payments",
        "refunds",
        "expenses",
    ]

    for table_name in order_of_insertion:
        rows = data[table_name]
        counts[table_name] = len(rows)
        for row in rows:
            # Build insert statement
            cols = ", ".join(row.keys())
            placeholders = ", ".join([f":{k}" for k in row.keys()])
            stmt = sa.text(f"INSERT INTO {table_name} ({cols}) VALUES ({placeholders})")
            conn.execute(stmt, row)

    dataset_hash = compute_dataset_hash(data)
    return {
        "counts": counts,
        "dataset_hash": dataset_hash,
        "variant": variant,
    }
