"""Command line administration interface for QueryLens (Contract C02)."""

from __future__ import annotations

import sys
import click
import sqlalchemy as sa

from querylens.auth.crypto import hash_password
from querylens.auth.service import AuthService
from querylens.persistence.session import create_metadata_tables, get_db_connection
from querylens.persistence.tables import users


@click.group()
def cli() -> None:
    """QueryLens management and administrative commands."""
    pass


@cli.command("bootstrap")
@click.option("--email", prompt="Admin email", help="Admin user email address")
@click.option(
    "--password",
    prompt=True,
    hide_input=True,
    confirmation_prompt=True,
    help="Admin password",
)
def bootstrap_cmd(email: str, password: str) -> None:
    """Create the initial admin user. Refuses if a user already exists (Contract C02)."""
    create_metadata_tables()

    with get_db_connection() as conn:
        count = conn.execute(sa.select(sa.func.count(users.c.id))).scalar()
        if count and count > 0:
            click.echo("Error: Application already bootstrapped. Multiple bootstraps refused.", err=True)
            sys.exit(1)

        hashed = hash_password(password)
        service = AuthService(conn=conn)
        user = service.create_user(email=email, password_hash=hashed, role="admin")
        click.echo(f"Successfully bootstrapped admin user: {user['email']} (ID: {user['id']})")


@cli.command("set-password")
@click.option("--email", prompt="User email", help="Target user email address")
@click.option(
    "--password",
    prompt=True,
    hide_input=True,
    confirmation_prompt=True,
    help="New password",
)
def set_password_cmd(email: str, password: str) -> None:
    """Update a user's password and revoke all active sessions."""
    with get_db_connection() as conn:
        service = AuthService(conn=conn)
        user = service.get_user_by_email(email)
        if not user:
            click.echo(f"Error: User with email '{email}' not found.", err=True)
            sys.exit(1)

        hashed = hash_password(password)
        conn.execute(
            users.update()
            .where(users.c.id == user["id"])
            .values(password_hash=hashed)
        )
        # Revoke all active sessions
        revoked_count = service.revoke_all_user_sessions(user["id"])
        click.echo(f"Updated password for {email}. Revoked {revoked_count} active sessions.")


@cli.command("seed-fixtures")
def seed_fixtures_cmd() -> None:
    """Seed development/testing fixtures."""
    click.echo("Seeding fixtures initialized.")


if __name__ == "__main__":
    cli()
