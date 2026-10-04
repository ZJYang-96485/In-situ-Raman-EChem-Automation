import unittest

from chi760 import (
    AdaptationStatus,
    CAParameters,
    CHI760Controller,
    CurrentStep,
    IMPEParameters,
    IRCompensationPlan,
    ISTEPParameters,
    MockCHI760,
    PotentialStep,
    RDEExperiment,
    RamanSyncPolicy,
    STEPParameters,
    SWVParameters,
    Technique,
    adapt_rde_protocol,
    build_rde_protocol,
    chronocoulometry_from_ca_C,
    cumulative_charge_C,
    evaluate_compensation_trials,
    profile_for,
    technique_uses_ir_compensation,
    validate_ru_measurements,
    request_rde_hardware_control,
    HardwareOperationBlockedError,
)


class CHI760EProtocolTests(unittest.TestCase):
    def test_optional_rde_hardware_control_is_explicitly_blocked(self):
        with self.assertRaises(HardwareOperationBlockedError):
            request_rde_hardware_control()

    def test_760e_exposes_all_documented_libec_techniques(self):
        profile = profile_for("760E")
        expected = {
            Technique.CV,
            Technique.IT,
            Technique.CA,
            Technique.SWV,
            Technique.EIS,
            Technique.IMPE,
            Technique.OCP,
            Technique.STEP,
            Technique.ISTEP,
        }
        self.assertEqual(expected, profile.supported_techniques)
        self.assertNotIn(Technique.LSV, profile.supported_techniques)

    def test_760e_controller_dispatches_new_mock_techniques(self):
        controller = CHI760Controller(MockCHI760(), model="760E")
        results = [
            controller.run_ca(CAParameters([PotentialStep(0.1, 2.0)])),
            controller.run_swv(SWVParameters(0.2, -0.8, 0.004, 0.025, 15.0)),
            controller.run_impe(IMPEParameters(-0.2, 0.8, 0.05, 0.01, 1000.0)),
            controller.run_step(STEPParameters([PotentialStep(0.1, 2.0)])),
            controller.run_istep(ISTEPParameters([CurrentStep(0.001, 2.0)])),
        ]
        self.assertEqual(
            ["CA", "SWV", "IMPE", "STEP", "ISTEP/CPCS"],
            [result["technique"] for result in results],
        )

    def test_controller_rejects_wrong_parameter_model_before_dispatch(self):
        controller = CHI760Controller(MockCHI760(), model="760E")
        with self.assertRaisesRegex(TypeError, "CA requires CAParameters"):
            controller.run_ca(SWVParameters(0.2, -0.8, 0.004, 0.025, 15.0))

    def test_charge_is_derived_from_ca_current(self):
        charge = cumulative_charge_C([0, 1, 2], [2, 2, 2])
        self.assertEqual((0.0, 2.0, 4.0), charge)
        self.assertEqual(charge, chronocoulometry_from_ca_C([0, 1, 2], [2, 2, 2]))

    def test_adapts_ca_range_and_marks_lsv_desktop_only(self):
        result = adapt_rde_protocol(
            {
                "protocol_name": "RDE reference",
                "steps": [
                    {
                        "name": "forward",
                        "type": "ca_range",
                        "start_voltage_v": -0.1,
                        "end_voltage_v": -0.3,
                        "step_voltage_v": -0.1,
                        "duration_s": 10,
                    },
                    {
                        "name": "ORR LSV",
                        "technique": "lsv",
                        "start_voltage_v": 0.2,
                        "end_voltage_v": -0.8,
                    },
                ],
            }
        )
        experiment_steps = [
            step for step in result.protocol.steps if step.action.value == "run_experiment"
        ]
        self.assertEqual(4, len(experiment_steps))
        self.assertEqual(
            [-0.1, -0.2, -0.3],
            [step.parameters["voltage_v"] for step in experiment_steps[:3]],
        )
        self.assertEqual(
            ["chronocoulometry_C"],
            experiment_steps[0].parameters["derived_outputs"],
        )
        self.assertEqual(
            AdaptationStatus.DESKTOP_ONLY.value,
            experiment_steps[-1].parameters["adaptation_status"],
        )
        self.assertTrue(result.warnings)

    def test_adapts_amperometric_it_as_documented_760e_technique(self):
        result = adapt_rde_protocol(
            {
                "protocol_name": "i-t hold",
                "steps": [
                    {
                        "name": "amperometry",
                        "technique": "it",
                        "potential_v": 0.1,
                        "duration_s": 10,
                        "sample_period_s": 1,
                    }
                ],
            }
        )
        step = result.protocol.steps[0]
        self.assertEqual("i-t", step.parameters["chi_technique"])
        self.assertEqual(AdaptationStatus.LIBEC_760E.value, step.parameters["adaptation_status"])

    def test_builds_execution_disabled_synchronized_rde_plan(self):
        plan = build_rde_protocol(
            name="Levich preparation",
            speeds_rpm=(400, 900, 1600, 2500),
            experiment=RDEExperiment(Technique.CA, {"potential_V": 0.2}),
            equilibration_s=10,
            raman_sync=RamanSyncPolicy.AFTER_EQUILIBRATION,
        )
        self.assertFalse(plan.execution_enabled)
        self.assertEqual("optional_disk_only", plan.metadata["rde_mode"])
        self.assertEqual((400.0, 900.0, 1600.0, 2500.0), plan.metadata["speeds_rpm"])
        self.assertEqual("stop_rde", plan.steps[-2].action.value)
        self.assertEqual(4, sum(step.action.value == "capture_raman" for step in plan.steps))
        self.assertEqual(
            4,
            sum(step.action.value == "prepare_ir_compensation" for step in plan.steps),
        )

    def test_rde_plan_rejects_boolean_numeric_values(self):
        experiment = RDEExperiment(Technique.CA, {"potential_V": 0.2})
        with self.assertRaises(ValueError):
            build_rde_protocol(
                name="invalid speed",
                speeds_rpm=(True,),
                experiment=experiment,
                equilibration_s=10,
            )
        with self.assertRaises(ValueError):
            build_rde_protocol(
                name="invalid wait",
                speeds_rpm=(400,),
                experiment=experiment,
                equilibration_s=False,
            )

    def test_adapter_rejects_nonboolean_enabled_flag(self):
        with self.assertRaisesRegex(ValueError, "enabled must be a boolean"):
            adapt_rde_protocol(
                {
                    "protocol_name": "ambiguous enabled",
                    "steps": [{"technique": "ca", "enabled": "false"}],
                }
            )

    def test_selects_repeatable_ru_and_calculates_requested_compensation(self):
        result = validate_ru_measurements(
            [12.0, 12.4],
            IRCompensationPlan(),
        )
        self.assertTrue(result.passed)
        self.assertAlmostEqual(12.2, result.selected_ohm)
        self.assertAlmostEqual(11.59, result.requested_compensation_ohm)

    def test_ir_strategy_is_the_default_without_review_metadata(self):
        plan = IRCompensationPlan()
        self.assertEqual(0.95, plan.target_compensation_fraction)
        self.assertEqual(10, plan.max_compensation_trials)
        self.assertNotIn("starting_policy_confirmed", vars(plan))
        self.assertNotIn("live_use_approved", vars(plan))

    def test_ir_loop_stops_when_95_percent_is_confirmed(self):
        result = evaluate_compensation_trials(
            [0.70, 0.90, 0.95, 0.96],
            IRCompensationPlan(),
        )
        self.assertTrue(result.reached_target)
        self.assertFalse(result.exhausted)
        self.assertEqual((0.70, 0.90, 0.95), result.observed_fractions)
        self.assertEqual(0.95, result.accepted_fraction)
        self.assertEqual(3, result.accepted_trial_number)
        self.assertFalse(result.accepted_at_ceiling)

    def test_ir_loop_stops_at_every_possible_pre_ceiling_target(self):
        for target_trial in range(1, 10):
            observations = [0.90] * (target_trial - 1) + [0.95] + [0.50] * 10
            with self.subTest(target_trial=target_trial):
                result = evaluate_compensation_trials(observations, IRCompensationPlan())
                self.assertTrue(result.reached_target)
                self.assertEqual(target_trial, result.accepted_trial_number)
                self.assertEqual(target_trial, len(result.observed_fractions))

    def test_ir_loop_stops_after_ten_trials_without_target(self):
        result = evaluate_compensation_trials(
            [0.90] * 12,
            IRCompensationPlan(),
        )
        self.assertFalse(result.reached_target)
        self.assertTrue(result.exhausted)
        self.assertEqual(10, len(result.observed_fractions))
        self.assertEqual(0.90, result.accepted_fraction)
        self.assertEqual(10, result.accepted_trial_number)
        self.assertTrue(result.accepted_at_ceiling)
        self.assertIsNone(result.next_trial_number)
        self.assertEqual(
            "Accepted final valid value at the 10-trial ceiling",
            result.reason,
        )

    def test_invalid_tenth_trial_uses_failure_path(self):
        result = evaluate_compensation_trials(
            [0.90] * 9 + [None],
            IRCompensationPlan(),
        )
        self.assertTrue(result.exhausted)
        self.assertIsNone(result.accepted_fraction)
        self.assertFalse(result.accepted_at_ceiling)
        self.assertEqual("Final trial produced no valid value", result.reason)

    def test_target_reached_on_tenth_trial_is_accepted_as_target(self):
        result = evaluate_compensation_trials(
            [0.90] * 9 + [0.95, 0.20],
            IRCompensationPlan(),
        )
        self.assertTrue(result.reached_target)
        self.assertEqual(10, result.accepted_trial_number)
        self.assertEqual(0.95, result.accepted_fraction)
        self.assertEqual(10, len(result.observed_fractions))

    def test_boolean_tenth_trial_is_not_silently_treated_as_100_percent(self):
        result = evaluate_compensation_trials(
            [0.90] * 9 + [True],
            IRCompensationPlan(),
        )
        self.assertTrue(result.exhausted)
        self.assertIsNone(result.accepted_fraction)
        self.assertFalse(result.accepted_at_ceiling)

    def test_ir_trial_ceiling_is_fixed_at_ten(self):
        for value in (9, 11, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                IRCompensationPlan(max_compensation_trials=value)

    def test_ir_target_is_fixed_at_95_percent(self):
        with self.assertRaises(ValueError):
            IRCompensationPlan(target_compensation_fraction=0.9)

    def test_ir_plan_rejects_nonfinite_and_boolean_numeric_values(self):
        for kwargs in (
            {"ru_repeatability_limit": float("nan")},
            {"ocp_stabilization_s": float("inf")},
            {"ru_frequency_Hz": True},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                IRCompensationPlan(**kwargs)

    def test_rejects_non_integer_ru_retry_count(self):
        for value in (2, 3.5, 21, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                IRCompensationPlan(ru_retry_count=value)

    def test_ir_plan_is_limited_to_reference_rde_cv_ca_family(self):
        self.assertTrue(technique_uses_ir_compensation(Technique.CV))
        self.assertTrue(technique_uses_ir_compensation(Technique.CA))
        self.assertFalse(technique_uses_ir_compensation(Technique.SWV))
        self.assertFalse(technique_uses_ir_compensation(Technique.STEP))

    def test_ru_validation_records_invalid_attempt_and_continues(self):
        result = validate_ru_measurements(
            ["not-a-number", 10.0, 10.1],  # type: ignore[list-item]
            IRCompensationPlan(),
        )
        self.assertEqual((None, 10.0, 10.1), result.attempts_ohm)
        self.assertTrue(result.passed)

    def test_boolean_ru_reading_is_recorded_as_invalid(self):
        result = validate_ru_measurements(
            [True, 10.0, 10.1],  # type: ignore[list-item]
            IRCompensationPlan(),
        )
        self.assertEqual((None, 10.0, 10.1), result.attempts_ohm)
        self.assertTrue(result.passed)

    def test_ru_selection_matches_reference_median_outlier_policy(self):
        result = validate_ru_measurements(
            [10.0, 100.0, 10.1],
            IRCompensationPlan(),
        )
        self.assertTrue(result.passed)
        self.assertEqual(10.1, result.selected_ohm)

    def test_charge_rejects_boolean_data(self):
        with self.assertRaises(ValueError):
            cumulative_charge_C([0, 1, True], [1, 1, 1])

    def test_ca_range_rejects_nonfinite_voltage(self):
        with self.assertRaisesRegex(ValueError, "finite"):
            adapt_rde_protocol(
                {
                    "protocol_name": "invalid range",
                    "steps": [
                        {
                            "type": "ca_range",
                            "start_voltage_v": "NaN",
                            "end_voltage_v": 1,
                            "step_voltage_v": 0.1,
                        }
                    ],
                }
            )

    def test_ca_range_rejects_increment_that_silently_misses_endpoint(self):
        with self.assertRaisesRegex(ValueError, "land exactly"):
            adapt_rde_protocol(
                {
                    "protocol_name": "misaligned range",
                    "steps": [
                        {
                            "type": "ca_range",
                            "start_voltage_v": 0,
                            "end_voltage_v": 1,
                            "step_voltage_v": 0.3,
                        }
                    ],
                }
            )


if __name__ == "__main__":
    unittest.main()
