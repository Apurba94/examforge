"""Start the app: python -m examforge [data.db] [--port 8021]"""
import sys

from .fieldkit import main_cli
from .web import create_app

sys.exit(main_cli(create_app, "examforge.db", 8021, sys.argv))
