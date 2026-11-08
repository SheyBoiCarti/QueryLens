"""Test deterministic fixture generation and reproducibility (Contracts C05, C10)."""

import sqlalchemy as sa
from datasets.generator import compute_dataset_hash, generate_dataset_records, seed_dataset


def test_generator_deterministic_hash():
    # 1. Repeated generations of variant A yield identical hashes
    data_a1 = generate_dataset_records(variant="A", seed=42)
    data_a2 = generate_dataset_records(variant="A", seed=42)
    hash_a1 = compute_dataset_hash(data_a1)
    hash_a2 = compute_dataset_hash(data_a2)
    assert hash_a1 == hash_a2
    assert len(hash_a1) == 64

    # 2. Repeated generations of variant B yield identical hashes
    data_b1 = generate_dataset_records(variant="B", seed=42)
    data_b2 = generate_dataset_records(variant="B", seed=42)
    hash_b1 = compute_dataset_hash(data_b1)
    hash_b2 = compute_dataset_hash(data_b2)
    assert hash_b1 == hash_b2

    # 3. Variants A and B differ
    assert hash_a1 != hash_b1
    assert data_a1["orders"] != data_b1["orders"]


def test_seed_dataset_sqlite_in_memory():
    engine = sa.create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    ddl_statements = [
        """CREATE TABLE departments (
            id VARCHAR(36) PRIMARY KEY,
            name VARCHAR(100) NOT NULL UNIQUE,
            budget DECIMAL(15,2) NOT NULL,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE employees (
            id VARCHAR(36) PRIMARY KEY,
            department_id VARCHAR(36) NOT NULL,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(100) NOT NULL UNIQUE,
            hire_date TEXT NOT NULL,
            salary DECIMAL(15,2) NOT NULL
        )""",
        """CREATE TABLE historical_assignments (
            id VARCHAR(36) PRIMARY KEY,
            employee_id VARCHAR(36) NOT NULL,
            department_id VARCHAR(36) NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NULL
        )""",
        """CREATE TABLE customers (
            id VARCHAR(36) PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(100) NOT NULL,
            tier VARCHAR(20) NOT NULL,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE products (
            id VARCHAR(36) PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            category VARCHAR(50) NOT NULL,
            price DECIMAL(15,2) NOT NULL,
            cost DECIMAL(15,2) NOT NULL,
            created_at TEXT NOT NULL
        )""",
        """CREATE TABLE orders (
            id VARCHAR(36) PRIMARY KEY,
            customer_id VARCHAR(36) NOT NULL,
            order_date TEXT NOT NULL,
            status VARCHAR(20) NOT NULL,
            total_amount DECIMAL(15,2) NOT NULL
        )""",
        """CREATE TABLE line_items (
            id VARCHAR(36) PRIMARY KEY,
            order_id VARCHAR(36) NOT NULL,
            product_id VARCHAR(36) NOT NULL,
            quantity INT NOT NULL,
            unit_price DECIMAL(15,2) NOT NULL,
            discount DECIMAL(15,2) NOT NULL DEFAULT 0.00
        )""",
        """CREATE TABLE payments (
            id VARCHAR(36) PRIMARY KEY,
            order_id VARCHAR(36) NOT NULL,
            payment_date TEXT NOT NULL,
            amount DECIMAL(15,2) NOT NULL,
            payment_method VARCHAR(20) NOT NULL,
            status VARCHAR(20) NOT NULL
        )""",
        """CREATE TABLE refunds (
            id VARCHAR(36) PRIMARY KEY,
            payment_id VARCHAR(36) NOT NULL,
            refund_date TEXT NOT NULL,
            amount DECIMAL(15,2) NOT NULL,
            reason VARCHAR(255) NULL
        )""",
        """CREATE TABLE expenses (
            id VARCHAR(36) PRIMARY KEY,
            department_id VARCHAR(36) NOT NULL,
            expense_date TEXT NOT NULL,
            amount DECIMAL(15,2) NOT NULL,
            category VARCHAR(50) NOT NULL
        )""",
    ]
    with engine.begin() as conn:
        for stmt in ddl_statements:
            conn.execute(sa.text(stmt))

        result = seed_dataset(conn, variant="A", seed=42)
        assert result["variant"] == "A"
        assert result["counts"]["departments"] == 4
        assert result["counts"]["employees"] == 5
        assert result["counts"]["orders"] == 4
        assert result["counts"]["line_items"] == 6
