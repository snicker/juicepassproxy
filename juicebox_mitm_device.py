import time

class JuiceboxMITMDevice:

    def __init__(
        self,
        mqtt_handler = None
    ):

        self._juicebox_addr = None
        self._mqtt_handler = mqtt_handler
        # Last command sent to juicebox device
        self._last_command = None
        # Last message received from juicebox device
        self._last_status_message = None
        self._first_status_message_timestamp = None
        self._boot_timestamp = None

    def _booted_in_less_than(self, seconds):
        return self._boot_timestamp and ((time.time() - self._boot_timestamp) < seconds)
