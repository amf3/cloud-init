"""Integration test of the cc_power_state_change module.

Test that the power state config options work as expected.
"""

import re
import time

import pytest

from tests.integration_tests.clouds import IntegrationCloud
from tests.integration_tests.instances import IntegrationInstance
from tests.integration_tests.integration_settings import PLATFORM
from tests.integration_tests.releases import IS_UBUNTU
from tests.integration_tests.util import (
    verify_clean_boot,
    verify_ordered_items_in_text,
)

USER_DATA = """\
#cloud-config
power_state:
  delay: {delay}
  mode: {mode}
  message: msg
  timeout: {timeout}
  condition: {condition}
"""


def _detect_reboot(instance: IntegrationInstance):
    # We'll wait for instance up here, but we don't know if we're
    # detecting the first boot or second boot, so we also check
    # the logs to ensure we've booted twice. If the logs show we've
    # only booted once, wait until we've booted twice
    instance.instance.wait()
    for _ in range(600):
        try:
            log = instance.read_from_file("/var/log/cloud-init.log")
            boot_count = log.count("running 'init-local'")
            if boot_count == 1:
                instance.instance.wait()
            elif boot_count > 1:
                break
        except Exception:
            pass
        time.sleep(1)
    else:
        raise Exception("Could not detect reboot")


def _can_connect(instance):
    return instance.execute("true").ok


# This test is marked unstable because even though it should be able to
# run anywhere, I can only get it to run in an lxd container, and even then
# occasionally some timing issues will crop up.
@pytest.mark.skipif(not IS_UBUNTU, reason="Only ever tested on Ubuntu")
@pytest.mark.skipif(
    PLATFORM != "lxd_container",
    reason="Test is unstable but most stable on lxd containers",
)
class TestPowerChange:
    @pytest.mark.parametrize(
        "mode,delay,timeout,expected",
        [
            ("poweroff", "now", "10", "will execute: shutdown -P now msg"),
            ("reboot", "now", "0", "will execute: shutdown -r now msg"),
            ("halt", "+1", "0", re.escape("will execute: shutdown -H +1 msg")),
        ],
    )
    def test_poweroff(
        self, session_cloud: IntegrationCloud, mode, delay, timeout, expected
    ):
        with session_cloud.launch(
            user_data=USER_DATA.format(
                delay=delay, mode=mode, timeout=timeout, condition="true"
            ),
            wait=False,
        ) as instance:
            if mode == "reboot":
                _detect_reboot(instance)
            else:
                instance.instance.wait_for_stop()
                instance.instance.start(wait=True)
            log = instance.read_from_file("/var/log/cloud-init.log")
            assert _can_connect(instance)
            verify_clean_boot(instance)
        lines_to_check = [
            "Running module power_state_change",
            expected,
            "running 'init-local'",
            "config-power_state_change already ran",
        ]
        verify_ordered_items_in_text(lines_to_check, log)

    @pytest.mark.user_data(
        USER_DATA.format(
            delay="0", mode="poweroff", timeout="0", condition="false"
        )
    )
    def test_poweroff_false_condition(self, client: IntegrationInstance):
        log = client.read_from_file("/var/log/cloud-init.log")
        assert _can_connect(client)
        assert "Condition was false. Will not perform state change" in log
