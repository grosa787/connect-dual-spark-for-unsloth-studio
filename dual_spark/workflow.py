"""Keep the optional Studio launch behind every installation check."""


class SetupWorkflow:
    STAGES = (
        "detect_cluster",
        "install_studio",
        "sync_and_build_rpc",
        "start_rpc",
        "smoke_test",
        "configure_studio",
        "verify_installation",
    )

    def __init__(self, setup):
        self.setup = setup

    def run(self) -> bool:
        for stage in self.STAGES:
            self.setup.perform(stage)
        return self.setup.offer_studio()
