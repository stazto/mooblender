from __future__ import annotations

import unittest

from mooblender.model.expressions import evaluate_expression


class ExpressionTests(unittest.TestCase):
    def test_arithmetic_and_variables(self):
        self.assertEqual(
            evaluate_expression("$PW$-$W$-18", {"PW": 950, "W": 400}),
            532.0,
        )

    def test_observed_ternary_syntax(self):
        expression = "@($I$?-($D$/2):$D$/2)"
        self.assertEqual(evaluate_expression(expression, {"I": False, "D": 20}), 10.0)
        self.assertEqual(evaluate_expression(expression, {"I": True, "D": 20}), -10.0)

    def test_never_executes_names_or_calls(self):
        self.assertEqual(evaluate_expression("open('/tmp/no')", default=7), 7)


if __name__ == "__main__":
    unittest.main()
