# -*- coding: utf-8 -*-
"""Unit tests for claude_tool. Run: python -m pytest -q"""
import importlib.util, json, os, sys, uuid
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("claude_tool", ROOT / "claude_tool.py")
ct = importlib.util.module_from_spec(spec); spec.loader.exec_module(ct)


# ------------------------------------------------------------- fixtures ----
@pytest.fixture
def env(tmp_path, monkeypatch):
    home   = tmp_path / "home"
    backup = tmp_path / "backups"
    (home / ".claude" / "projects").mkdir(parents=True)
    (home / ".codex" / "sessions").mkdir(parents=True)
    backup.mkdir()
    monkeypatch.setattr(ct, "HOME", home)
    monkeypatch.setattr(ct, "CLAUDE_DIR", home / ".claude")
    monkeypatch.setattr(ct, "CODEX_DIR", home / ".codex")
    monkeypatch.setattr(ct, "BACKUP_ROOT", backup)
    monkeypatch.setattr(ct, "CONFIG_PATH", backup / "cct_config.json")
    return home, backup


def make_claude(home):
    sid = str(uuid.uuid4())
    proj = home / ".claude" / "projects" / "E--proj"
    proj.mkdir(parents=True, exist_ok=True)
    lines = [
        {"type": "user", "cwd": r"E:\proj", "timestamp": "2026-01-01T00:00:00Z",
         "message": {"role": "user", "content": "Hello there"}},
        {"type": "user", "cwd": r"E:\proj", "timestamp": "2026-01-01T00:00:01Z",
         "message": {"role": "user", "content": "<system-reminder>ignore me</system-reminder>"}},
        {"type": "assistant", "cwd": r"E:\proj", "timestamp": "2026-01-01T00:00:02Z",
         "message": {"role": "assistant", "content": [
             {"type": "text", "text": "Hi! Running a tool."},
             {"type": "tool_use", "name": "Bash", "input": {"command": "ls -la"}}]}},
        {"type": "user", "cwd": r"E:\proj", "timestamp": "2026-01-01T00:00:03Z",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "content": [{"type": "text", "text": "file1\nfile2"}]}]}},
        {"type": "assistant", "cwd": r"E:\proj", "timestamp": "2026-01-01T00:00:04Z",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "Done."}]}},
        {"type": "user", "isSidechain": True, "message": {"role": "user", "content": "sidechain skip"}},
    ]
    fp = proj / f"{sid}.jsonl"
    fp.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return fp


def make_codex(home):
    day = home / ".codex" / "sessions" / "2026" / "01" / "01"
    day.mkdir(parents=True, exist_ok=True)
    lines = [
        {"timestamp": "2026-01-01T00:00:00Z", "type": "session_meta",
         "payload": {"cwd": r"E:\proj", "session_id": "x"}},
        {"timestamp": "2026-01-01T00:00:00Z", "type": "event_msg",
         "payload": {"type": "task_started"}},
        {"timestamp": "2026-01-01T00:00:01Z", "type": "response_item",
         "payload": {"type": "message", "role": "user",
                     "content": [{"type": "input_text", "text": "Build me a thing"}]}},
        {"timestamp": "2026-01-01T00:00:02Z", "type": "response_item",
         "payload": {"type": "function_call", "name": "shell",
                     "arguments": "{\"cmd\":\"pytest\"}"}},
        {"timestamp": "2026-01-01T00:00:03Z", "type": "response_item",
         "payload": {"type": "function_call_output", "output": "2 passed"}},
        {"timestamp": "2026-01-01T00:00:04Z", "type": "response_item",
         "payload": {"type": "message", "role": "assistant",
                     "content": [{"type": "output_text", "text": "All tests pass."}]}},
    ]
    fp = day / "rollout-2026-01-01T00-00-00-x.jsonl"
    fp.write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    return fp


# ------------------------------------------------------------- tests -------
def test_uuid7_shape():
    u = ct.uuid7()
    assert uuid.UUID(u).version == 7

def test_claude_extract_and_tools(env):
    home, _ = env
    fp = make_claude(home)
    msgs, meta = ct.claude_extract(fp, include_tools=True)
    texts = [m for m in msgs if m["kind"] == "text"]
    tools = [m for m in msgs if m["kind"] == "tool"]
    assert [m["text"] for m in texts] == ["Hello there", "Hi! Running a tool.", "Done."]
    assert any("tool-use: Bash" in m["text"] for m in tools)
    assert any("tool-result" in m["text"] for m in tools)
    assert meta["cwd"] == r"E:\proj"
    # without tools -> only text messages
    msgs2, _ = ct.claude_extract(fp, include_tools=False)
    assert all(m["kind"] == "text" for m in msgs2)

def test_codex_extract_and_tools(env):
    home, _ = env
    fp = make_codex(home)
    msgs, meta = ct.codex_extract(fp, include_tools=True)
    assert [m["text"] for m in msgs if m["kind"] == "text"] == ["Build me a thing", "All tests pass."]
    assert any("shell" in m["text"] for m in msgs if m["kind"] == "tool")
    assert meta["cwd"] == r"E:\proj"

def test_convert_claude_to_codex(env):
    home, _ = env
    fp = make_claude(home)
    assert ct.convert_file("claude", "codex", fp, include_tools=False)
    outs = list((home / ".codex" / "sessions").rglob("rollout-*.jsonl"))
    assert outs
    parsed = [json.loads(l) for l in outs[0].read_text(encoding="utf-8").splitlines()]
    assert parsed[0]["type"] == "session_meta"
    assert any(p["type"] == "response_item" and p["payload"].get("role") == "user" for p in parsed)
    idx = (home / ".codex" / "session_index.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert json.loads(idx[-1])["thread_name"].startswith("[Claude]")

def test_convert_codex_to_claude_chain(env):
    home, _ = env
    fp = make_codex(home)
    assert ct.convert_file("codex", "claude", fp, include_tools=True)
    outs = list((home / ".claude" / "projects").glob("*/*.jsonl"))
    assert outs
    parsed = [json.loads(l) for l in outs[0].read_text(encoding="utf-8").splitlines()]
    assert parsed[0]["parentUuid"] is None
    assert all(parsed[i]["parentUuid"] == parsed[i - 1]["uuid"] for i in range(1, len(parsed)))
    assert parsed[0]["message"]["content"].startswith("[Codex]")

def test_backup_manifest_and_verify(env):
    home, backup = env
    (home / ".claude.json").write_text('{"account":"me"}', encoding="utf-8")
    make_claude(home); make_codex(home)
    dest = ct.do_backup({"compress": False, "keep_last": 0, "encrypt": False,
                         "cloud_remote": "", "include_tools": True})
    assert (dest / ct.MANIFEST).exists()
    assert ct.verify_manifest(dest) is True
    # tamper -> verify fails
    victim = next((dest / ".claude" / "projects").glob("*/*.jsonl"))
    victim.write_text("tampered", encoding="utf-8")
    assert ct.verify_manifest(dest) is False

def test_backup_compress_and_restore_zip(env):
    home, backup = env
    make_claude(home)
    dest = ct.do_backup({"compress": True, "keep_last": 0, "encrypt": False,
                         "cloud_remote": "", "include_tools": True})
    assert dest.suffix == ".zip" and dest.exists()
    snaps = ct.list_snapshots()
    assert any(s.suffix == ".zip" for s in snaps)

def test_retention(env):
    home, backup = env
    make_claude(home)
    for _ in range(3):
        ct.do_backup({"compress": False, "keep_last": 2, "encrypt": False,
                      "cloud_remote": "", "include_tools": True})
    snaps = [p for p in backup.iterdir() if p.name.startswith("backup_")]
    assert len(snaps) <= 2

def test_export_md_and_html(env):
    home, backup = env
    fp = make_claude(home)
    md = ct.export_file("claude", fp, "md")
    hp = ct.export_file("claude", fp, "html")
    assert md.exists() and md.suffix == ".md"
    assert hp.exists() and "<section" in hp.read_text(encoding="utf-8")

def test_search(env, capsys):
    home, _ = env
    make_claude(home); make_codex(home)
    ct.search_all("tests pass")
    out = capsys.readouterr().out
    assert "matched" in out and "1 session" in out

@pytest.mark.skipif(ct._load_cryptography() is None, reason="cryptography not installed")
def test_encryption_roundtrip(env):
    home, backup = env
    (home / ".claude.json").write_text('{"secret":"token"}', encoding="utf-8")
    make_claude(home)
    dest = backup / "backup_enc"; dest.mkdir()
    ct.copytree(home / ".claude", dest / ".claude")
    (dest / ".claude.json").write_text('{"secret":"token"}', encoding="utf-8")
    assert ct.encrypt_creds(dest, "pw123") is True
    assert not (dest / ".claude.json").exists()
    assert (dest / ".claude.json.enc").exists()
    assert ct.decrypt_creds(dest, "pw123") is True
    assert json.loads((dest / ".claude.json").read_text(encoding="utf-8"))["secret"] == "token"
