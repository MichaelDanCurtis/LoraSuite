"""Small, non-secret preferences shared by clients of the same vault."""
from pathlib import Path
from contextlib import contextmanager
import json
import sqlite3
import time
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

Theme = Literal['aurora', 'ocean', 'solar', 'graphite', 'nebula', 'rose', 'ember', 'arctic', 'midnight', 'copper', 'acid', 'synthwave']


class ThemeSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    theme: Theme
    only_if_unset: bool = False


class WorkspaceSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    active_project_id: str | None = Field(default=None, max_length=256)
    target: Literal['image', 'video', 'voice', 'id_lora'] | None = None
    stage: Literal['create', 'sources', 'prepare', 'verify', 'build', 'evaluate'] | None = None
    experience: Literal['guided', 'studio'] | None = None
    only_if_unset: bool = False


class PreparationSelection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    checkpoint: dict[str, Any]
    only_if_unset: bool = False



class Preferences:
    def __init__(self, root: Path):
        self.path = root / 'ui_preferences.sqlite3'

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('CREATE TABLE IF NOT EXISTS theme (id INTEGER PRIMARY KEY CHECK(id=1), name TEXT NOT NULL, updated INTEGER NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS workspace (id INTEGER PRIMARY KEY CHECK(id=1), data TEXT NOT NULL, updated INTEGER NOT NULL)')
        db.execute('CREATE TABLE IF NOT EXISTS preparation (project TEXT NOT NULL, target TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(project, target))')
        try:
            with db:
                yield db
        finally:
            db.close()

    def read(self):
        with self.connect() as db:
            row = db.execute('SELECT name, updated FROM theme WHERE id=1').fetchone()
        return {'theme': row[0] if row else None, 'updated_at': row[1] if row else 0}

    def select(self, selection: ThemeSelection):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT name, updated FROM theme WHERE id=1').fetchone()
            if not row or not selection.only_if_unset:
                updated = max(time.time_ns() // 1_000_000, (row[1] + 1) if row else 0)
                db.execute('INSERT OR REPLACE INTO theme VALUES (1, ?, ?)', (selection.theme, updated))
                row = (selection.theme, updated)
        return {'theme': row[0], 'updated_at': row[1]}

    def read_workspace(self):
        with self.connect() as db:
            row = db.execute('SELECT data, updated FROM workspace WHERE id=1').fetchone()
        return {'workspace': json.loads(row[0]) if row else None, 'updated_at': row[1] if row else 0}

    def select_workspace(self, selection: WorkspaceSelection):
        # Patch only explicit selections; a stale client cannot replace unrelated fields.
        patch = selection.model_dump(exclude_none=True, exclude={'only_if_unset'})
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data, updated FROM workspace WHERE id=1').fetchone()
            if not row or not selection.only_if_unset:
                value = json.loads(row[0]) if row else {
                    'active_project_id': '', 'target': 'image', 'stage': 'create', 'experience': 'guided',
                }
                value.update(patch)
                updated = max(time.time_ns() // 1_000_000, (row[1] + 1) if row else 0)
                db.execute('INSERT OR REPLACE INTO workspace VALUES (1, ?, ?)', (json.dumps(value), updated))
                row = (json.dumps(value), updated)
        return {'workspace': json.loads(row[0]), 'updated_at': row[1]}

    def read_preparation(self, project_id: str, target: str):
        with self.connect() as db:
            row = db.execute('SELECT data FROM preparation WHERE project=? AND target=?', (project_id, target)).fetchone()
        return {'checkpoint': json.loads(row[0]) if row else None}

    def save_preparation(self, project_id: str, target: str, selection: PreparationSelection):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT data FROM preparation WHERE project=? AND target=?', (project_id, target)).fetchone()
            if not row or not selection.only_if_unset:
                data = json.dumps(selection.checkpoint)
                db.execute('INSERT OR REPLACE INTO preparation VALUES (?, ?, ?)', (project_id, target, data))
                row = (data,)
        return {'checkpoint': json.loads(row[0])}


def preferences_router(root: Path):
    router = APIRouter()
    preferences = Preferences(root)

    @router.get('/preferences/theme')
    def read_theme():
        return preferences.read()

    @router.post('/preferences/theme')
    def select_theme(selection: ThemeSelection):
        return preferences.select(selection)

    @router.get('/preferences/workspace')
    def read_workspace():
        return preferences.read_workspace()

    @router.post('/preferences/workspace')
    def select_workspace(selection: WorkspaceSelection):
        return preferences.select_workspace(selection)

    @router.get('/preferences/preparation/{project_id}/{target}')
    def read_preparation(project_id: str, target: Literal['image', 'video', 'voice', 'id_lora']):
        return preferences.read_preparation(project_id, target)

    @router.post('/preferences/preparation/{project_id}/{target}')
    def save_preparation(project_id: str, target: Literal['image', 'video', 'voice', 'id_lora'], selection: PreparationSelection):
        return preferences.save_preparation(project_id, target, selection)

    # A theme is public display data, not a project or credential. Extensions
    # get only this read-only projection through the existing bridge CORS.
    @router.get('/library/theme')
    def companion_theme():
        return preferences.read()

    return router
