"""
Permet à pytest de trouver le dossier src/ depuis n'importe où,
exactement comme app.py le fait pour Streamlit.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))