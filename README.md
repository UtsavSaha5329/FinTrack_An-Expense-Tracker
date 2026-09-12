# FinTrack

FinTrack is a command-line expense tracker built with Python and MySQL. It records one-off and recurring expenses, shows a monthly dashboard, and flags subscriptions due within the next seven days.

## Features

- Create password-protected local accounts; passwords are stored as salted PBKDF2 hashes.
- Add, view, edit, and delete personal expenses.
- Track recurring subscriptions with daily, weekly, monthly, or yearly renewal schedules.
- Renew due or overdue subscriptions once for today without adding charges for missed dates.
- Use the date from the device's configured local time zone for new expenses and renewals.
- Pause, cancel, or reactivate subscriptions without deleting history.
- Review current-month spending by category and estimated subscription cost.
- Keep database credentials outside source control.

## Prerequisites

- Python 3.10 or newer
- MySQL 8.0 or newer
- A MySQL database named `fintrack` (or another name you place in `.env`)

## Setup

1. Clone the repository and move into it.
2. Create and activate a virtual environment:

   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```

3. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

4. Create the database and tables. For example, from a MySQL prompt:

   ```sql
   CREATE DATABASE fintrack CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
   USE fintrack;
   SOURCE schema.sql;
   ```

5. Copy `.env.example` to `.env`, then set the database connection values. Do not upload `.env` to GitHub.
6. Start the program:

   ```powershell
   python fintrack.py
   ```

## Project layout

```text
fintrack.py       # interactive application
schema.sql        # MySQL tables and indexes
.env.example      # safe configuration template
requirements.txt  # Python dependencies
```

## Security notes

The original script contained a database password directly in source code. This version removes it and reads secrets from `.env`, which is ignored by Git. If the old password was used on a real server, change it before publishing the old code or its Git history.

This is a learning project, not a production financial system. For a public deployment, use a managed secret store, enforce database least privilege, add automated tests, and use a full authentication service.

## License

Add a license before publishing. [MIT](https://choosealicense.com/licenses/mit/) is a common permissive choice for small open-source projects.
