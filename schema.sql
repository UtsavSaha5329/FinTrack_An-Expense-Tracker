-- Run this once as a MySQL user allowed to create tables in the fintrack database.
-- The application database user should have only the privileges it needs on this database.

CREATE TABLE IF NOT EXISTS users (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    currency CHAR(3) NOT NULL DEFAULT 'INR',
    monthly_budget DECIMAL(12, 2) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT users_budget_positive CHECK (monthly_budget > 0)
);

CREATE TABLE IF NOT EXISTS expenses (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    user_id BIGINT UNSIGNED NOT NULL,
    expense_date DATE NOT NULL,
    amount DECIMAL(12, 2) NOT NULL,
    category VARCHAR(100) NOT NULL,
    description VARCHAR(255) NOT NULL,
    expense_type ENUM('variable', 'recurring') NOT NULL,
    renewal_date DATE NULL,
    renewal_period ENUM('daily', 'weekly', 'monthly', 'yearly') NULL,
    status ENUM('active', 'paused', 'cancelled', 'expired') NULL,
    annual_total DECIMAL(12, 2) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT expenses_amount_positive CHECK (amount > 0),
    CONSTRAINT expenses_user_fk FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX expenses_by_user_date (user_id, expense_date),
    INDEX expenses_renewals (user_id, status, renewal_date)
);
