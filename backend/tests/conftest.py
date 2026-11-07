"""The older tests check the data contract, not login. Auth is ON by default in the app; they switch it off here.
test_tenancy.py switches it back on."""
import os

os.environ.setdefault("AUTH_ENFORCE", "false")
