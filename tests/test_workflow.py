import unittest

from dual_spark.workflow import SetupWorkflow


class FakeSetup:
    def __init__(self, fail_at=None):
        self.fail_at = fail_at
        self.calls = []

    def perform(self, stage):
        self.calls.append(stage)
        if stage == self.fail_at:
            raise RuntimeError("stage failed")

    def offer_studio(self):
        self.calls.append("offer_studio")
        return False


class WorkflowTests(unittest.TestCase):
    def test_studio_choice_is_withheld_after_any_failed_check(self):
        for stage in SetupWorkflow.STAGES:
            with self.subTest(stage=stage):
                fake = FakeSetup(fail_at=stage)
                with self.assertRaises(RuntimeError):
                    SetupWorkflow(fake).run()
                self.assertNotIn("offer_studio", fake.calls)

    def test_studio_choice_appears_only_after_all_checks(self):
        fake = FakeSetup()
        self.assertFalse(SetupWorkflow(fake).run())
        self.assertEqual(fake.calls, [*SetupWorkflow.STAGES, "offer_studio"])


if __name__ == "__main__":
    unittest.main()
