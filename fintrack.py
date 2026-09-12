"""FinTrack: a small command-line expense tracker backed by MySQL.

Run this module after configuring a .env file (see .env.example):
    python fintrack.py
"""

from __future__ import annotations

import hashlib
import hmac
import os
from calendar import monthrange
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from getpass import getpass
from typing import Any, Iterable

import mysql.connector
from dotenv import load_dotenv


PASSWORD_ITERATIONS = 310_000
RENEWAL_PERIODS = {"daily", "weekly", "monthly", "yearly"}
SUBSCRIPTION_STATUSES = {"active", "paused", "cancelled", "expired"}


@dataclass(frozen=True)
class DatabaseConfig:
    """Database connection values loaded from the environment."""

    host: str
    port: int
    user: str
    password: str
    database: str

    @classmethod
    def from_environment(cls) -> "DatabaseConfig":
        load_dotenv()
        required = ("DB_HOST", "DB_USER", "DB_PASSWORD", "DB_NAME")
        missing = [name for name in required if not os.getenv(name)]
        if missing:
            names = ", ".join(missing)
            raise RuntimeError(f"Missing database settings: {names}. Copy .env.example to .env first.")

        try:
            port = int(os.getenv("DB_PORT", "3306"))
        except ValueError as error:
            raise RuntimeError("DB_PORT must be a number.") from error

        return cls(
            host=os.environ["DB_HOST"],
            port=port,
            user=os.environ["DB_USER"],
            password=os.environ["DB_PASSWORD"],
            database=os.environ["DB_NAME"],
        )


class Database:
    """Thin wrapper around MySQL with parameterised queries and safe cleanup."""

    def __init__(self, config: DatabaseConfig) -> None:
        self.connection = mysql.connector.connect(
            host=config.host,
            port=config.port,
            user=config.user,
            password=config.password,
            database=config.database,
        )

    def execute(self, query: str, params: tuple[Any, ...] = ()) -> int:
        cursor = self.connection.cursor()
        try:
            cursor.execute(query, params)
            self.connection.commit()
            return cursor.lastrowid
        except mysql.connector.Error:
            self.connection.rollback()
            raise
        finally:
            cursor.close()

    def fetch_all(self, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        cursor = self.connection.cursor(dictionary=True)
        try:
            cursor.execute(query, params)
            return cursor.fetchall()
        finally:
            cursor.close()

    def fetch_one(self, query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        rows = self.fetch_all(query, params)
        return rows[0] if rows else None

    def close(self) -> None:
        if self.connection.is_connected():
            self.connection.close()


def hash_password(password: str) -> str:
    """Return a salted PBKDF2 hash suitable for storage in the users table."""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ITERATIONS)
    return f"{PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def password_matches(password: str, stored_value: str) -> bool:
    """Check a password against a value produced by :func:`hash_password`."""
    try:
        iterations_text, salt_hex, digest_hex = stored_value.split("$", maxsplit=2)
        calculated = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(salt_hex), int(iterations_text)
        ).hex()
        return hmac.compare_digest(calculated, digest_hex)
    except (ValueError, TypeError):
        return False


def renewal_date(start: date, period: str) -> date:
    """Calculate the next date for a supported recurring-expense period."""
    period = period.lower()
    if period == "daily":
        return start + timedelta(days=1)
    if period == "weekly":
        return start + timedelta(weeks=1)
    if period == "monthly":
        next_month = 1 if start.month == 12 else start.month + 1
        next_year = start.year + 1 if start.month == 12 else start.year
        return date(next_year, next_month, min(start.day, monthrange(next_year, next_month)[1]))
    if period == "yearly":
        next_year = start.year + 1
        return date(next_year, start.month, min(start.day, monthrange(next_year, start.month)[1]))
    raise ValueError(f"Unsupported renewal period: {period}")


def annual_cost(amount: Decimal, period: str) -> Decimal:
    multipliers = {"daily": 365, "weekly": 52, "monthly": 12, "yearly": 1}
    return amount * multipliers[period.lower()]


def print_table(rows: Iterable[dict[str, Any]], columns: list[tuple[str, str]]) -> None:
    """Print database rows in a small, dependency-free table."""
    rows = list(rows)
    if not rows:
        print("No records found.")
        return

    rendered = [["" if row.get(key) is None else str(row[key]) for key, _ in columns] for row in rows]
    widths = [max(len(label), *(len(row[index]) for row in rendered)) for index, (_, label) in enumerate(columns)]
    header = " | ".join(label.ljust(widths[index]) for index, (_, label) in enumerate(columns))
    print(header)
    print("-+-".join("-" * width for width in widths))
    for row in rendered:
        print(" | ".join(value.ljust(widths[index]) for index, value in enumerate(row)))


def read_nonempty(prompt: str) -> str:
    while not (value := input(prompt).strip()):
        print("This value cannot be empty.")
    return value


def read_amount(prompt: str) -> Decimal:
    while True:
        try:
            amount = Decimal(input(prompt).strip()).quantize(Decimal("0.01"))
            if amount > 0:
                return amount
        except InvalidOperation:
            pass
        print("Enter a positive amount, for example 249.50.")


def read_date(prompt: str, default: date | None = None) -> date:
    suffix = f" [{default.isoformat()}]" if default else ""
    while True:
        value = input(f"{prompt}{suffix}: ").strip()
        if not value and default:
            return default
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            print("Use YYYY-MM-DD, for example 2026-09-12.")


def read_choice(prompt: str, choices: set[str]) -> str:
    formatted = "/".join(sorted(choices))
    while True:
        value = input(f"{prompt} ({formatted}): ").strip().lower()
        if value in choices:
            return value
        print(f"Choose one of: {formatted}.")


class FinTrackApp:
    """Interactive application and its authenticated user session."""

    def __init__(self, database: Database) -> None:
        self.db = database
        self.user: dict[str, Any] | None = None

    @property
    def user_id(self) -> int:
        if self.user is None:
            raise RuntimeError("No user is signed in.")
        return int(self.user["id"])

    def register(self) -> None:
        print("\nCreate your FinTrack account")
        username = read_nonempty("Username: ")
        if self.db.fetch_one("SELECT id FROM users WHERE username = %s", (username,)):
            print("That username is already in use.")
            return

        name = read_nonempty("Your name: ")
        password = getpass("Password: ")
        if len(password) < 8:
            print("Use a password with at least 8 characters.")
            return

        currency = read_nonempty("Currency code (for example INR): ").upper()
        budget = read_amount("Monthly budget: ")
        user_id = self.db.execute(
            """INSERT INTO users (username, password_hash, display_name, currency, monthly_budget)
               VALUES (%s, %s, %s, %s, %s)""",
            (username, hash_password(password), name, currency, budget),
        )
        self.user = self.db.fetch_one("SELECT * FROM users WHERE id = %s", (user_id,))
        print(f"Account created. Welcome, {name}!")

    def sign_in(self) -> bool:
        username = read_nonempty("Username: ")
        password = getpass("Password: ")
        user = self.db.fetch_one("SELECT * FROM users WHERE username = %s", (username,))
        if user is None or not password_matches(password, user["password_hash"]):
            print("Username or password was not recognised.")
            return False
        self.user = user
        print(f"\nWelcome back, {user['display_name']}!")
        return True

    def start_session(self) -> bool:
        has_users = self.db.fetch_one("SELECT id FROM users LIMIT 1") is not None
        return self.sign_in() if has_users else (self.register() or self.user is not None)

    def show_expenses(self) -> None:
        rows = self.db.fetch_all(
            """SELECT id, expense_date, amount, category, description, expense_type,
                      renewal_date, renewal_period, status
                 FROM expenses WHERE user_id = %s ORDER BY expense_date DESC, id DESC""",
            (self.user_id,),
        )
        print_table(rows, [
            ("id", "ID"), ("expense_date", "Date"), ("amount", "Amount"),
            ("category", "Category"), ("description", "Description"),
            ("expense_type", "Type"), ("renewal_date", "Renews"),
            ("renewal_period", "Period"), ("status", "Status"),
        ])

    def add_expense(self) -> None:
        today = date.today()
        expense_date = read_date("Expense date", today)
        amount = read_amount("Amount: ")
        category = read_nonempty("Category: ")
        description = read_nonempty("Description: ")
        expense_type = read_choice("Expense type", {"variable", "recurring"})
        renewal_period: str | None = None
        next_renewal: date | None = None
        yearly_total: Decimal | None = None

        if expense_type == "recurring":
            renewal_period = read_choice("Renewal period", RENEWAL_PERIODS)
            next_renewal = renewal_date(expense_date, renewal_period)
            yearly_total = annual_cost(amount, renewal_period)

        self.db.execute(
            """INSERT INTO expenses
               (user_id, expense_date, amount, category, description, expense_type,
                renewal_date, renewal_period, status, annual_total)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (self.user_id, expense_date, amount, category, description, expense_type,
             next_renewal, renewal_period, "active" if renewal_period else None, yearly_total),
        )
        print("Expense saved.")

    def get_owned_expense(self) -> dict[str, Any] | None:
        try:
            expense_id = int(input("Expense ID: "))
        except ValueError:
            print("Expense ID must be a number.")
            return None
        expense = self.db.fetch_one(
            "SELECT * FROM expenses WHERE id = %s AND user_id = %s", (expense_id, self.user_id)
        )
        if expense is None:
            print("No matching expense was found.")
        return expense

    def edit_expense(self) -> None:
        self.show_expenses()
        if not (expense := self.get_owned_expense()):
            return
        amount = read_amount(f"New amount [{expense['amount']}]: ")
        expense_date = read_date("New expense date", expense["expense_date"])
        category = read_nonempty(f"New category (current: {expense['category']}): ")
        description = read_nonempty(f"New description (current: {expense['description']}): ")
        values: list[Any] = [amount, expense_date, category, description]
        query = "UPDATE expenses SET amount = %s, expense_date = %s, category = %s, description = %s"
        if expense["expense_type"] == "recurring":
            period = expense["renewal_period"]
            query += ", renewal_date = %s, annual_total = %s"
            values.extend([renewal_date(expense_date, period), annual_cost(amount, period)])
        values.extend([expense["id"], self.user_id])
        self.db.execute(query + " WHERE id = %s AND user_id = %s", tuple(values))
        print("Expense updated.")

    def delete_expense(self) -> None:
        self.show_expenses()
        if not (expense := self.get_owned_expense()):
            return
        if input(f"Delete '{expense['description']}' permanently? [y/N]: ").strip().lower() != "y":
            print("Nothing was deleted.")
            return
        self.db.execute("DELETE FROM expenses WHERE id = %s AND user_id = %s", (expense["id"], self.user_id))
        print("Expense deleted.")

    def edit_subscription(self) -> None:
        rows = self.db.fetch_all(
            """SELECT id, description, amount, renewal_date, renewal_period, status
                 FROM expenses WHERE user_id = %s AND expense_type = 'recurring'
                 ORDER BY renewal_date""",
            (self.user_id,),
        )
        print_table(rows, [
            ("id", "ID"), ("description", "Description"), ("amount", "Amount"),
            ("renewal_date", "Renews"), ("renewal_period", "Period"), ("status", "Status"),
        ])
        if not (expense := self.get_owned_expense()):
            return
        if expense["expense_type"] != "recurring":
            print("That expense is not a subscription.")
            return
        status = read_choice("New subscription status", SUBSCRIPTION_STATUSES)
        self.db.execute(
            "UPDATE expenses SET status = %s WHERE id = %s AND user_id = %s",
            (status, expense["id"], self.user_id),
        )
        print("Subscription updated.")

    def renewal_alerts(self) -> None:
        today = date.today()
        cutoff = today + timedelta(days=7)
        rows = self.db.fetch_all(
            """SELECT id, description, amount, renewal_date, renewal_period
                 FROM expenses
                 WHERE user_id = %s AND expense_type = 'recurring' AND status = 'active'
                   AND renewal_date <= %s
                 ORDER BY renewal_date""",
            (self.user_id, cutoff),
        )
        if not rows:
            print("No renewals are due in the next seven days.")
            return
        for row in rows:
            days = (row["renewal_date"] - today).days
            when = "today" if days == 0 else (f"{abs(days)} day(s) overdue" if days < 0 else f"in {days} day(s)")
            print(f"[{row['id']}] {row['description']}: {row['amount']} due {when} ({row['renewal_date']}).")

    def dashboard(self) -> None:
        today = date.today()
        month_start = today.replace(day=1)
        next_month = renewal_date(month_start, "monthly")
        total_row = self.db.fetch_one(
            """SELECT COALESCE(SUM(amount), 0) AS total FROM expenses
                 WHERE user_id = %s AND expense_date >= %s AND expense_date < %s""",
            (self.user_id, month_start, next_month),
        )
        spent = Decimal(str(total_row["total"]))
        budget = Decimal(str(self.user["monthly_budget"]))
        print(f"\n{today.strftime('%B %Y')} overview")
        print(f"Spent: {spent:.2f} {self.user['currency']}")
        print(f"Budget remaining: {budget - spent:.2f} {self.user['currency']}")

        categories = self.db.fetch_all(
            """SELECT category, SUM(amount) AS total FROM expenses
                 WHERE user_id = %s AND expense_date >= %s AND expense_date < %s
                 GROUP BY category ORDER BY total DESC""",
            (self.user_id, month_start, next_month),
        )
        print("\nSpending by category")
        print_table(categories, [("category", "Category"), ("total", "Amount")])

        projection = self.db.fetch_one(
            """SELECT COALESCE(SUM(annual_total), 0) AS total FROM expenses
                 WHERE user_id = %s AND expense_type = 'recurring' AND status = 'active'""",
            (self.user_id,),
        )
        annual = Decimal(str(projection["total"]))
        print(f"\nActive subscriptions: {annual / Decimal('12'):.2f}/month, {annual:.2f}/year (estimated)")

    def run(self) -> None:
        actions = {
            "1": ("View expenses", self.show_expenses),
            "2": ("Add an expense", self.add_expense),
            "3": ("Edit an expense", self.edit_expense),
            "4": ("Delete an expense", self.delete_expense),
            "5": ("Manage subscriptions", self.edit_subscription),
            "6": ("Check renewal alerts", self.renewal_alerts),
            "7": ("View monthly dashboard", self.dashboard),
        }
        while True:
            print("\nFinTrack")
            for key, (label, _) in actions.items():
                print(f"{key}. {label}")
            print("0. Exit")
            choice = input("\nChoose an option: ").strip()
            if choice == "0":
                print("Thanks for using FinTrack.")
                return
            action = actions.get(choice)
            if action is None:
                print("Choose one of the numbered options.")
                continue
            try:
                action[1]()
            except mysql.connector.Error as error:
                print(f"Database error: {error}")


def main() -> None:
    try:
        database = Database(DatabaseConfig.from_environment())
    except (RuntimeError, mysql.connector.Error) as error:
        print(f"Could not connect to FinTrack: {error}")
        return

    try:
        app = FinTrackApp(database)
        if app.start_session():
            app.run()
    finally:
        database.close()


if __name__ == "__main__":
    main()
