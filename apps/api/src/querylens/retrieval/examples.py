"""Few-shot verified examples and concept-diversity retrieval (Contracts C06, C10)."""

from __future__ import annotations

from typing import NamedTuple


class FewShotExample(NamedTuple):
    dialect: str
    question: str
    sql: str
    assumptions: list[str]
    category: str


# Dialect-verified few-shot examples
VERIFIED_EXAMPLES: list[FewShotExample] = [
    # PostgreSQL examples
    FewShotExample(
        dialect="postgresql",
        question="What is the total revenue by customer status?",
        sql="SELECT c.status, SUM(o.amount) AS total_revenue FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.status ORDER BY total_revenue DESC;",
        assumptions=["Filters out customers with no orders"],
        category="aggregates",
    ),
    FewShotExample(
        dialect="postgresql",
        question="Show top 3 products by sales volume using window functions",
        sql="WITH ranked_products AS (SELECT p.name, COUNT(i.id) AS sales_count, DENSE_RANK() OVER (ORDER BY COUNT(i.id) DESC) AS rnk FROM products p JOIN items i ON p.id = i.product_id GROUP BY p.name) SELECT name, sales_count FROM ranked_products WHERE rnk <= 3;",
        assumptions=["Ties are included via DENSE_RANK"],
        category="window",
    ),
    FewShotExample(
        dialect="postgresql",
        question="How many orders were placed in 2024 per month?",
        sql="SELECT EXTRACT(MONTH FROM o.order_date) AS order_month, COUNT(*) AS order_count FROM orders o WHERE EXTRACT(YEAR FROM o.order_date) = 2024 GROUP BY EXTRACT(MONTH FROM o.order_date) ORDER BY order_month ASC;",
        assumptions=["order_date is normalized to UTC"],
        category="temporal",
    ),

    # MySQL examples
    FewShotExample(
        dialect="mysql",
        question="What is the total revenue by customer status?",
        sql="SELECT c.status, SUM(o.amount) AS total_revenue FROM customers c JOIN orders o ON c.id = o.customer_id GROUP BY c.status ORDER BY total_revenue DESC;",
        assumptions=["Filters out customers with no orders"],
        category="aggregates",
    ),
    FewShotExample(
        dialect="mysql",
        question="Show top 3 products by sales volume using window functions",
        sql="WITH ranked_products AS (SELECT p.name, COUNT(i.id) AS sales_count, DENSE_RANK() OVER (ORDER BY COUNT(i.id) DESC) AS rnk FROM products p JOIN items i ON p.id = i.product_id GROUP BY p.name) SELECT name, sales_count FROM ranked_products WHERE rnk <= 3;",
        assumptions=["Ties are included via DENSE_RANK"],
        category="window",
    ),
    FewShotExample(
        dialect="mysql",
        question="How many orders were placed in 2024 per month?",
        sql="SELECT MONTH(o.order_date) AS order_month, COUNT(*) AS order_count FROM orders o WHERE YEAR(o.order_date) = 2024 GROUP BY MONTH(o.order_date) ORDER BY order_month ASC;",
        assumptions=["order_date is normalized to UTC"],
        category="temporal",
    ),
]


class ExampleRetriever:
    """Selects 2-3 concept-diverse few-shot examples for target dialect."""

    @staticmethod
    def get_examples(dialect: str, limit: int = 3) -> list[FewShotExample]:
        d_lower = dialect.lower()
        matching = [e for e in VERIFIED_EXAMPLES if e.dialect == d_lower]

        # Select diverse categories
        seen_categories: set[str] = set()
        chosen: list[FewShotExample] = []

        for e in matching:
            if e.category not in seen_categories:
                chosen.append(e)
                seen_categories.add(e.category)
            if len(chosen) >= limit:
                break

        return chosen
