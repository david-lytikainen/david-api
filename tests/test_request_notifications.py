import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import routes
from app.models import Base, REQUEST_STATUS_NAMES, ROLE_NAMES, RequestStatus, Role, WebsiteRequest


class RequestNotificationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        sessions = sessionmaker(bind=self.engine)
        with sessions() as session:
            session.add_all(Role(name=name) for name in ROLE_NAMES)
            statuses = [RequestStatus(name=name) for name in REQUEST_STATUS_NAMES]
            session.add_all(statuses)
            session.flush()
            session.add(WebsiteRequest(request_number="012345", customer_name="Customer", customer_email="customer@example.com", customer_phone="123", project_description="Website", target_date="2027-01-01", budget_range="1000", status_id=statuses[0].id))
            session.commit()
        for target, value in [("SessionLocal", sessions), ("ADMIN_EMAIL", "admin@example.com"), ("PUBLIC_APP_BASE_URL", "https://example.com"), ("JWT_SECRET", "test-secret")]:
            patcher = patch.object(routes, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        mail_patch = patch.object(routes, "send_email")
        self.mail = mail_patch.start()
        self.addCleanup(mail_patch.stop)
        self.addCleanup(self.engine.dispose)
        app = FastAPI()
        app.include_router(routes.router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        self.admin = {"Authorization": "Bearer " + routes.jwt.encode({"sub": "admin"}, "test-secret", algorithm="HS256")}

    def test_messages_notify_the_other_party_after_saving(self):
        for headers, recipient, role in [({}, "admin@example.com", "customer"), (self.admin, "customer@example.com", "admin")]:
            with self.subTest(role=role):
                response = self.client.post("/requests/012345/comments", json={"body": "  Hello there  "}, headers=headers)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["authorRole"], role)
                self.assertEqual(self.mail.call_args.args[0], recipient)
                self.assertIn("Hello there", self.mail.call_args.args[2])
                self.assertIn("https://example.com/request/012345", self.mail.call_args.args[2])
        self.assertEqual(self.mail.call_count, 2)
        self.assertEqual(len(self.client.get("/requests/012345").json()["comments"]), 2)

    def test_only_actual_status_changes_notify_customer(self):
        for status in ["in_progress", "in_progress"]:
            response = self.client.post("/admin/requests/012345/status", json={"status": status}, headers=self.admin)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], status)
        self.mail.assert_called_once()
        self.assertEqual(self.mail.call_args.args[0], "customer@example.com")
        self.assertIn("in progress", self.mail.call_args.args[2])
        self.assertIn("https://example.com/request/012345", self.mail.call_args.args[2])

    def test_rejected_updates_send_no_email(self):
        cases = [("/requests/012345/comments", {"body": " "}, {}, 400), ("/requests/999999/comments", {"body": "Hello"}, {}, 404), ("/admin/requests/012345/status", {"status": "reviewing"}, {}, 401), ("/admin/requests/012345/status", {"status": "invalid"}, self.admin, 400)]
        for path, payload, headers, expected in cases:
            with self.subTest(path=path, payload=payload):
                self.assertEqual(self.client.post(path, json=payload, headers=headers).status_code, expected)
        self.mail.assert_not_called()

    def test_mail_failure_does_not_undo_saved_message(self):
        self.mail.side_effect = RuntimeError("SMTP unavailable")
        with self.assertLogs("app.routes", level="ERROR"):
            response = self.client.post("/requests/012345/comments", json={"body": "Keep this message"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client.get("/requests/012345").json()["comments"][0]["body"], "Keep this message")


if __name__ == "__main__":
    unittest.main()
