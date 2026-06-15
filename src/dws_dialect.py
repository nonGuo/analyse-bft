from sqlglot import Dialect
from sqlglot.dialects.postgres import Postgres
from sqlglot import exp


class DWS(Postgres):
    class Parser(Postgres.Parser):
        FUNCTIONS = {
            **Postgres.Parser.FUNCTIONS,
            "NVL": lambda args: exp.Coalesce(this=args[0], expressions=args[1:] if len(args) > 1 else []),
            "DECODE": lambda args: exp.Case(
                this=None,
                ifs=[exp.If(this=args[i], true=args[i + 1]) for i in range(0, len(args) - 1, 2)],
                default=args[-1] if len(args) % 2 == 1 else None
            ) if len(args) >= 2 else None,
            "TO_DATE": lambda args: exp.TsOrDsToDate(this=args[0]),
            "TO_CHAR": lambda args: exp.ToChar(this=args[0], format=args[1] if len(args) > 1 else None),
            "NVL2": lambda args: exp.If(
                this=exp.Not(this=args[0]) if len(args) > 0 else None,
                true=args[2] if len(args) > 2 else None,
                false=args[1] if len(args) > 1 else None
            ),
        }

    class Generator(Postgres.Generator):
        pass

