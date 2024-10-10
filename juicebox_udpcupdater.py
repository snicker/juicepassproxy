import asyncio
import logging
import time

from const import (
    ERROR_LOOKBACK_MIN,
    MAX_ERROR_COUNT,
    MAX_RETRY_ATTEMPT,
    UDPC_UPDATE_CHECK_TIMEOUT,
)
from juicebox_telnet import JuiceboxTelnet

_LOGGER = logging.getLogger(__name__)


class JuiceboxUDPCUpdater:
    def __init__(
        self,
        juicebox_host,
        jpp_host,
        telnet_port,
        udpc_port=8047,
        telnet_timeout=None,
        loglevel=None,
    ):
        if loglevel is not None:
            _LOGGER.setLevel(loglevel)
        self._juicebox_host = juicebox_host
        self._jpp_host = jpp_host
        self._udpc_port = udpc_port
        self._telnet_port = telnet_port
        self._telnet_timeout = telnet_timeout
        self._default_sleep_interval = 30
        self._udpc_update_loop_task = None
        self._telnet = None
        self._error_count = 0
        self._error_timestamp_list = []

    async def start(self):
        _LOGGER.info("Starting JuiceboxUDPCUpdater")

        await self._connect()

    async def close(self):
        if self._telnet is not None:
            await self._telnet.close()
            self._telnet = None

    async def _connect(self):
        connect_attempt = 1
        while (
            self._telnet is None
            and connect_attempt <= MAX_RETRY_ATTEMPT
            and self._error_count < MAX_ERROR_COUNT
        ):
            _LOGGER.debug(
                f"Telnet connection attempt {connect_attempt} of {MAX_RETRY_ATTEMPT}"
            )
            connect_attempt += 1
            self._telnet = JuiceboxTelnet(
                self._juicebox_host,
                self._telnet_port,
                loglevel=_LOGGER.getEffectiveLevel(),
                timeout=self._telnet_timeout,
            )
            try:
                await self._telnet.open()
            except TimeoutError as e:
                _LOGGER.warning(
                    "JuiceboxUDPCUpdater Telnet Timeout. Reconnecting. "
                    f"({e.__class__.__qualname__}: {e})"
                )
                await self._add_error()
                await self._telnet.close()
                self._telnet = None
                pass
            except ConnectionResetError as e:
                _LOGGER.warning(
                    "JuiceboxUDPCUpdater Telnet Connection Error. Reconnecting. "
                    f"({e.__class__.__qualname__}: {e})"
                )
                await self._add_error()
                await self._telnet.close()
                self._telnet = None
                pass
        if self._telnet is None:
            raise ChildProcessError("JuiceboxUDPCUpdater: Unable to connect to Telnet.")
        if self._udpc_update_loop_task is None or self._udpc_update_loop_task.done():
            self._udpc_update_loop_task = await self._udpc_update_loop()
            self._loop.create_task(self._udpc_update_loop_task)
        _LOGGER.info("JuiceboxUDPCUpdater Connected to Juicebox Telnet")

    async def _udpc_update_loop(self):
        _LOGGER.debug("Starting JuiceboxUDPCUpdater Loop")
        while self._error_count < MAX_ERROR_COUNT:
            sleep_interval = self._default_sleep_interval
            if self._telnet is None:
                _LOGGER.warning(
                    "JuiceboxUDPCUpdater Telnet Connection Lost. Reconnecting."
                )
                await self._connect()
                continue
            try:
                async with asyncio.timeout(UDPC_UPDATE_CHECK_TIMEOUT):
                    sleep_interval = await self._udpc_update_handler(sleep_interval)
            except TimeoutError as e:
                _LOGGER.warning(
                    f"UDPC Update Check timeout after {UDPC_UPDATE_CHECK_TIMEOUT} sec. "
                    f"({e.__class__.__qualname__}: {e})"
                )
                await self._add_error()
                await self._telnet.close()
                self._telnet = None
                sleep_interval = 3
            await asyncio.sleep(sleep_interval)
        raise ChildProcessError(
            f"JuiceboxUDPCUpdater: More than {self._error_count} "
            f"errors in the last {ERROR_LOOKBACK_MIN} min."
        )

    async def _udpc_update_handler(self, default_sleep_interval):
        sleep_interval = default_sleep_interval
        try:
            _LOGGER.info("JuiceboxUDPCUpdater Check Starting")
            connections = await self._telnet.get_udpc_list()
            update_required = True
            udpc_streams_to_close = {}  # Key = Connection id, Value = list id
            udpc_stream_to_update = 0

            # _LOGGER.debug(f"connections: {connections}")

            for i, connection in enumerate(connections):
                if connection["type"] == "UDPC":
                    udpc_streams_to_close.update({int(connection["id"]): i})
                    if self._jpp_host not in connection["dest"]:
                        udpc_stream_to_update = int(connection["id"])
            # _LOGGER.debug(f"udpc_streams_to_close: {udpc_streams_to_close}")
            if udpc_stream_to_update == 0 and len(udpc_streams_to_close) > 0:
                udpc_stream_to_update = int(max(udpc_streams_to_close, key=int))
            _LOGGER.debug(f"Active UDPC Stream: {udpc_stream_to_update}")

            for stream in list(udpc_streams_to_close):
                if stream < udpc_stream_to_update:
                    udpc_streams_to_close.pop(stream, None)

            if len(udpc_streams_to_close) == 0:
                _LOGGER.info("UDPC IP not found, updating")
            elif (
                self._jpp_host
                not in connections[udpc_streams_to_close[udpc_stream_to_update]]["dest"]
            ):
                _LOGGER.info("UDPC IP incorrect, updating")
            elif len(udpc_streams_to_close) == 1:
                _LOGGER.info("UDPC IP correct")
                update_required = False

            if update_required:
                for id in udpc_streams_to_close:
                    _LOGGER.debug(f"Closing UDPC stream: {id}")
                    await self._telnet.close_udpc_stream(id)
                await self._telnet.write_udpc_stream(self._jpp_host, self._udpc_port)
                # Save is not recommended https://github.com/snicker/juicepassproxy/issues/96
                # await self._telnet.save_udpc()
                _LOGGER.info("UDPC IP Changed")
        except ConnectionResetError as e:
            _LOGGER.warning(
                "Telnet connection to JuiceBox lost. "
                "Nothing to worry about unless this happens a lot. "
                f"({e.__class__.__qualname__}: {e})"
            )
            await self._add_error()
            await self._telnet.close()
            self._telnet = None
            sleep_interval = 3
        except TimeoutError as e:
            _LOGGER.warning(
                "Telnet connection to JuiceBox has timed out. "
                "Nothing to worry about unless this happens a lot. "
                f"({e.__class__.__qualname__}: {e})"
            )
            await self._add_error()
            await self._telnet.close()
            self._telnet = None
            sleep_interval = 3
        except OSError as e:
            _LOGGER.warning(
                "Could not route Telnet connection to JuiceBox. "
                "Nothing to worry about unless this happens a lot. "
                f"({e.__class__.__qualname__}: {e})"
            )
            await self._add_error()
            await self._telnet.close()
            self._telnet = None
            sleep_interval = 3
        return sleep_interval

    async def _add_error(self):
        self._error_timestamp_list.append(time.time())
        time_cutoff = time.time() - (ERROR_LOOKBACK_MIN * 60)
        temp_list = list(
            filter(lambda el: el > time_cutoff, self._error_timestamp_list)
        )
        self._error_timestamp_list = temp_list
        self._error_count = len(self._error_timestamp_list)
        _LOGGER.debug(f"Errors in last {ERROR_LOOKBACK_MIN} min: {self._error_count}")
