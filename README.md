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
