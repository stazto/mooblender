from __future__ import annotations

import unittest

from mooblender.model.expressions import evaluate_condition, evaluate_expression


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

    def test_observed_visibility_comparisons(self):
        self.assertEqual(evaluate_expression("$PH$>165", {"PH": 330}), 1.0)
        self.assertEqual(evaluate_expression("$PH$<=165", {"PH": 330}), 0.0)
        self.assertEqual(
            evaluate_expression("$PH$>=85 and $PH$<165", {"PH": 155}),
            1.0,
        )

    def test_model_information_selects_conditional_aggregate(self):
        information = {"coz_bal": {"tipo": "P1"}}

        self.assertTrue(
            evaluate_condition('@Coz_bal(TIPO)@ == "P1"', model_information=information)
        )
        self.assertFalse(
            evaluate_condition('@Coz_bal(TIPO)@ == "P2"', model_information=information)
        )

    def test_unknown_model_information_does_not_silently_remove_geometry(self):
        self.assertTrue(evaluate_condition('@Missing(TYPE)@ == "A"'))

    def test_never_executes_names_or_calls(self):
        self.assertEqual(evaluate_expression("open('/tmp/no')", default=7), 7)


if __name__ == "__main__":
    unittest.main()
