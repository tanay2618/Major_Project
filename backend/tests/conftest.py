import os
import sys

# Make `import auth`, `import models`, `import verification...` work when running pytest from backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# database.py refuses to import without this. The engine is lazy, so no real DB is contacted.
os.environ.setdefault("DATABASE_URL", "postgresql://user:pass@localhost:5432/testdb")
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("OCR_ENGINE", "rapid")  # tests use bundled-model OCR (PaddleOCR models need internet)
