import json
from pathlib import Path

from openstudio.protocol_gen import build


def test_committed_protocol_schema_is_up_to_date():
    """Nếu thất bại: chạy `pnpm protocol:gen` rồi commit packages/protocol."""
    committed = Path(__file__).resolve().parents[3] / "packages" / "protocol" / "schema.json"
    assert json.loads(committed.read_text(encoding="utf-8")) == build()
