CREATE TABLE IF NOT EXISTS roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(32) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS request_statuses (
    id SERIAL PRIMARY KEY,
    name VARCHAR(32) NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS portfolio_sites (
    id SERIAL PRIMARY KEY,
    site_url VARCHAR(1024) NOT NULL,
    screenshot_url VARCHAR(1024) NOT NULL DEFAULT '',
    screenshot_s3_key VARCHAR(512),
    display_order INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS website_requests (
    id SERIAL PRIMARY KEY,
    request_number VARCHAR(6) NOT NULL UNIQUE,
    customer_name VARCHAR(255) NOT NULL,
    customer_email VARCHAR(255) NOT NULL,
    customer_phone VARCHAR(64) NOT NULL,
    project_description TEXT NOT NULL,
    target_date VARCHAR(32) NOT NULL,
    budget_range VARCHAR(255) NOT NULL,
    status_id INTEGER NOT NULL REFERENCES request_statuses(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS website_request_comments (
    id SERIAL PRIMARY KEY,
    website_request_id INTEGER NOT NULL REFERENCES website_requests(id),
    author_role_id INTEGER NOT NULL REFERENCES roles(id),
    body TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO roles (name) VALUES ('customer'), ('admin') ON CONFLICT (name) DO NOTHING;
INSERT INTO request_statuses (name) VALUES ('submitted'), ('reviewing'), ('in_progress'), ('delivered') ON CONFLICT (name) DO NOTHING;
