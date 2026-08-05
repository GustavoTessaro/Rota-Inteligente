import os
import sys
from alembic.config import Config
from alembic import command

# ensure project root is current working dir
ROOT = os.path.dirname(os.path.dirname(__file__))
os.chdir(ROOT)

# point settings to sqlite file inside backend-api
os.environ["DATABASE_URL"] = "sqlite:///./migrated.db"
print('Using DATABASE_URL=', os.environ['DATABASE_URL'])

cfg = Config('alembic.ini')
# run upgrade
command.upgrade(cfg, 'head')
print('Alembic upgrade completed')
