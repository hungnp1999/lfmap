import json

from typer.testing import CliRunner

from lfmap_core.cli import build_app

runner = CliRunner()


def run(registry, *args, input=None):
    return runner.invoke(build_app(registry), list(args), input=input)


def test_plugins_list(registry):
    result = run(registry, "plugins", "list", "--json")
    assert result.exit_code == 0
    assert json.loads(result.output) == [{"id": "fake-plugin", "version": "1.2.3", "operations": ["greet", "write"]}]


def test_generated_command(registry):
    result = run(registry, "fake-plugin", "greet", "--name", "Hùng", "--times", "2", "--shout")
    assert result.exit_code == 0
    assert result.output.strip() == "message: HELLO HÙNG HELLO HÙNG"


def test_json_output(registry):
    result = run(registry, "fake-plugin", "greet", "--name", "A", "--json")
    assert json.loads(result.output) == {"message": "Hello A"}


def test_missing_required_option(registry):
    assert run(registry, "fake-plugin", "greet").exit_code == 2


def test_tool_error_propagates(registry):
    result = run(registry, "fake-plugin", "greet", "--name", "error")
    assert result.exception.code == "not_found"


def test_nested_input_uses_json_and_confirms(registry):
    payload = json.dumps({"names": ["a", "b"]})
    aborted = run(registry, "fake-plugin", "write", "--input-json", payload, input="n\n")
    assert aborted.exit_code == 1
    confirmed = run(registry, "fake-plugin", "write", "--input-json", payload, "--yes")
    assert confirmed.output.strip() == "message: a,b"
