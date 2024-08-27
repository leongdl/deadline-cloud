import click
import json
import typing as t


class ClickLogger:

    def __init__(self, is_json: bool):
        self._is_json = is_json

    def echo(
        self,
        message: t.Optional[t.Any] = None,
        file: t.Optional[t.IO[t.Any]] = None,
        nl: bool = True,
        err: bool = False,
        color: t.Optional[bool] = None,
    ):
        if not self._is_json:
            click.echo(message, file, nl, err, color)

    def json(
        self,
        message: t.Optional[dict] = None,
        file: t.Optional[t.IO[t.Any]] = None,
        nl: bool = True,
        err: bool = False,
        color: t.Optional[bool] = None,
    ):
        if self._is_json:
            click.echo(json.dumps(message), file, nl, err, color)
