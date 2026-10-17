# David API

Run `psql "$DATABASE_URL" -f sql/001_startup.sql`, then install dependencies with `python3 -m pip install -r requirements.txt` and start with `python3 -m app.main`.

```env
DATABASE_URL=postgresql://USER:PASSWORD@localhost:5432/david
CORS_ORIGINS=http://localhost:3000
JWT_SECRET=replace-me
ADMIN_EMAIL=you@example.com
ADMIN_PASSWORD=replace-me
ADMIN_NAME=David
IMAGE_FOLDER=/absolute/path/to/portfolio-images
PUBLIC_APP_BASE_URL=http://localhost:3000
MAIL_SERVER=smtp.gmail.com
MAIL_PORT=587
MAIL_USERNAME=you@example.com
MAIL_PASSWORD=app-password
```

Portfolio screenshots are converted to AVIF with balanced quality and encoding speed when possible, stored in `IMAGE_FOLDER` as `image-<database id>`, and served by the API. If conversion fails, the original image is stored under the same filename. The API process must have read/write access to that folder; use a persistent mounted folder when deploying in a container.

Request comments email the other party, and status changes email the customer, with the message/status and request link. Notifications use the existing mail settings and run after saving; failures are logged without undoing the update.
