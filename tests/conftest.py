import os
import tempfile

_test_dir = tempfile.mkdtemp(prefix="workshop-os-tests-")
os.environ["INVENTORY_DATABASE_URL"] = f"sqlite:///{_test_dir}/test.db"
os.environ["INVENTORY_SECRET_KEY"] = "test-secret-with-sufficient-entropy"
os.environ["INVENTORY_COOKIE_SECURE"] = "false"
os.environ["INVENTORY_DEV_RETURN_OTP"] = "true"
os.environ["INVENTORY_EMAIL_PROVIDER"] = "console"

