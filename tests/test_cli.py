"""
tests/test_cli.py — unit tests for frontend.cli
"""

from pathlib import Path
from frontend.cli import _build_parser


def test_cli_parser_defaults():
    parser = _build_parser()
    args = parser.parse_args(["new", "item-1"])
    assert args.command == "new"
    assert args.entity_id == "item-1"
    assert not hasattr(args, "state_file")


def test_cli_parser_flags_before_subcommand():
    parser = _build_parser()
    args = parser.parse_args([
        "--schema", "schemas/simple_task.json",
        "--state-file", "custom.json",
        "new", "item-2",
    ])
    assert args.command == "new"
    assert args.entity_id == "item-2"
    assert args.schema == "schemas/simple_task.json"
    assert args.state_file == "custom.json"


def test_cli_parser_flags_after_subcommand():
    parser = _build_parser()
    args = parser.parse_args([
        "new", "item-3",
        "--schema", "schemas/simple_task.json",
        "--state-file", "custom.json",
    ])
    assert args.command == "new"
    assert args.entity_id == "item-3"
    assert args.schema == "schemas/simple_task.json"
    assert args.state_file == "custom.json"


def test_cli_parser_override_args():
    parser = _build_parser()
    args = parser.parse_args(["override", "item-1", "done", "--reason", "finished"])
    assert args.command == "override"
    assert args.entity_id == "item-1"
    assert args.target_stage == "done"
    assert args.reason == "finished"
