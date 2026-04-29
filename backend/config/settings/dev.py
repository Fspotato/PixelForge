# ruff: noqa: F403,F405

from .base import *

DEBUG = env.bool("DJANGO_DEBUG", default=True)
