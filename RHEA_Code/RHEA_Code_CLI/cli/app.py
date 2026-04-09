# -*- coding: utf-8 -*-
from __future__ import annotations

from .session import RHEACodeCLI


def build_cli() -> RHEACodeCLI:
    return RHEACodeCLI()


def main() -> None:
    cli = build_cli()
    cli.run()


if __name__ == "__main__":
    main()