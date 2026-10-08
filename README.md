# David API

Run `psql "$DATABASE_URL" -f sql/001_startup.sql`, then install dependencies with `python3 -m pip install -r requirements.txt` and start with `python3 -m app.main`.

```env
DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/david
CORS_ORIGINS=http://localhost:3000
JWT_SECRET=replace-me
ADMIN_EMAIL=you@example.com
ADMIN_PASSWORD=replace-me
ADMIN_NAME=David
AWS_REGION=us-east-1
S3_BUCKET=your-shared-bucket
PUBLIC_APP_BASE_URL=http://localhost:3000
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=you@example.com
MAIL_PASSWORD=app-password
```

Request comments email the other party, and status changes email the customer, with the message/status and request link. Notifications use the existing mail settings and run after saving; failures are logged without undoing the update.

To run notification tests, install `httpx` alongside the requirements and run `python -m unittest discover -s tests -v`. Tests use an isolated in-memory database and mocked email delivery.
