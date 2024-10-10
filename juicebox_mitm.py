import asyncio
import errno
import logging
import time

import asyncio_dgram
from const import (
    ERROR_LOOKBACK_MIN,
    MAX_ERROR_COUNT,
    MAX_RETRY_ATTEMPT,
    MITM_HANDLER_TIMEOUT,
    MITM_RECV_TIMEOUT,
    MITM_SEND_DATA_TIMEOUT,
)
from juicebox_message import JuiceboxCommand, JuiceboxStatusMessage, JuiceboxEncryptedMessage, JuiceboxDebugMessage, juicebox_message_from_bytes

# Began with https://github.com/rsc-dev/pyproxy and rewrote when moving to async.

_LOGGER = logging.getLogger(__name__)


class JuiceboxMITM:

    def __init__(
        self,
        jpp_addr,
        enelx_addr,
        local_mitm_handler=None,
        ignore_enelx=False,
        remote_mitm_handler=None,
        mqtt_handler=None,
        loglevel=None,
    ):
        if loglevel is not None:
            _LOGGER.setLevel(loglevel)
        self._jpp_addr = jpp_addr
        self._enelx_addr = enelx_addr
        self._juicebox_addr = None
        self._ignore_enelx = ignore_enelx
        self._local_mitm_handler = local_mitm_handler
        self._remote_mitm_handler = remote_mitm_handler
        self._mqtt_handler = mqtt_handler
        self._loop = asyncio.get_running_loop()
        self._mitm_loop_task: asyncio.Task = None
        self._sending_lock = asyncio.Lock()
        self._dgram = None
        self._error_count = 0
        self._error_timestamp_list = []
        # Last command sent to juicebox device
        self._last_command = None
        # Last message received from juicebox device
        self._last_status_message = None
        self._first_status_message_timestamp = None
        self._boot_timestamp = None

    async def start(self) -> None:
        _LOGGER.info("Starting JuiceboxMITM")
        _LOGGER.debug(f"JPP: {self._jpp_addr[0]}:{self._jpp_addr[1]}")
        _LOGGER.debug(f"EnelX: {self._enelx_addr[0]}:{self._enelx_addr[1]}")

        await self._connect()

    async def close(self):
        if self._dgram is not None:
            self._dgram.close()
            self._dgram = None
            await asyncio.sleep(3)

    async def _connect(self):
        connect_attempt = 1
        while (
            self._dgram is None
            and connect_attempt <= MAX_RETRY_ATTEMPT
            and self._error_count < MAX_ERROR_COUNT
        ):
            if connect_attempt != 1:
                _LOGGER.debug(
                    "Retrying UDP Server Startup. Attempt "
                    f"{connect_attempt} of {MAX_RETRY_ATTEMPT}"
                )
            connect_attempt += 1
            try:
                if self._sending_lock.locked():
                    self._dgram = await asyncio_dgram.bind(
                        self._jpp_addr, reuse_port=True
                    )
                else:
                    async with self._sending_lock:
                        self._dgram = await asyncio_dgram.bind(
                            self._jpp_addr, reuse_port=True
                        )
            except OSError as e:
                _LOGGER.warning(
                    "JuiceboxMITM UDP Server Startup Error. Reconnecting. "
                    f"({e.__class__.__qualname__}: {e})"
                )
                await self._add_error()
                self._dgram = None
                pass
            await asyncio.sleep(5)
        if self._dgram is None:
            raise ChildProcessError("JuiceboxMITM: Unable to start MITM UDP Server.")
        if self._mitm_loop_task is None or self._mitm_loop_task.done():
            self._mitm_loop_task = await self._mitm_loop()
            self._loop.create_task(self._mitm_loop_task)
        _LOGGER.debug(f"JuiceboxMITM Connected. {self._jpp_addr}")

    async def _mitm_loop(self) -> None:
        _LOGGER.debug("Starting JuiceboxMITM Loop")
        while self._error_count < MAX_ERROR_COUNT:
            if self._dgram is None:
                _LOGGER.warning("JuiceboxMITM Reconnecting.")
                await self._add_error()
                await self._connect()
                continue
            # _LOGGER.debug("Listening")
            try:
                async with asyncio.timeout(MITM_RECV_TIMEOUT):
                    data, remote_addr = await self._dgram.recv()
            except asyncio_dgram.TransportClosed:
                _LOGGER.warning("JuiceboxMITM Connection Lost.")
                await self._add_error()
                self._dgram = None
                continue
            except TimeoutError as e:
                _LOGGER.warning(
                    f"No Message Received after {MITM_RECV_TIMEOUT} sec. "
                    f"({e.__class__.__qualname__}: {e})"
                )
                await self._add_error()
                self._dgram = None
                continue
            try:
                async with asyncio.timeout(MITM_HANDLER_TIMEOUT):
                    await self._main_mitm_handler(data, remote_addr)
            except TimeoutError as e:
                _LOGGER.warning(
                    f"MITM Handler timeout after {MITM_HANDLER_TIMEOUT} sec. "
                    f"({e.__class__.__qualname__}: {e})"
                )
                await self._add_error()
                self._dgram = None
        raise ChildProcessError(
            f"JuiceboxMITM: More than {self._error_count} errors in the last "
            f"{ERROR_LOOKBACK_MIN} min."
        )


    def _booted_in_less_than(self, seconds):
        return self._boot_timestamp and ((time.time() - self._boot_timestamp) < seconds)
            
    async def _message_decode(self, data : bytes):
        decoded_message = None
        try:
            decoded_message = juicebox_message_from_bytes(data)
            if isinstance(decoded_message, JuiceboxStatusMessage):
                self._last_status_message = decoded_message
                if self._first_status_message_timestamp is None:
                   self._first_status_message_timestamp = time.time()
                elapsed = int(time.time() - self._first_status_message_timestamp)

                # Try to initialize the set entities with safe values from the juicebox device
                # This is not the best way to do, but can be made without need to store somewhere the data as config is not available here
                # TODO: better/safer way
                if not self.is_mqtt_numeric_entity_defined("current_max_online_set"):
                    if decoded_message.has_value("current_max_online"):
                        _LOGGER.info("setting current_max_online_set with current_max_online")
                        await self._mqtt_handler.get_entity("current_max_online_set").set_state(self._last_status_message.get_processed_value("current_max_online"))
                    # Apparently all messages came with current_max_online then, this code will never be executed                            
                    elif ((elapsed > 600) or self._booted_in_less_than(30)) and decoded_message.has_value("current_rating"):
                        _LOGGER.info("setting current_max_online_set with current_rating")
                        await self._mqtt_handler.get_entity("current_max_online_set").set_state(self._last_status_message.get_processed_value("current_rating"))

                #TODO now the MQTT is storing previous data on config, this can be used to get initialize theses values from previous JPP execution
                if not self.is_mqtt_numeric_entity_defined("current_max_offline_set"): 
                    if decoded_message.has_value("current_max_offline"):
                        _LOGGER.info("setting current_max_offline_set with current_max_offline")
                        await self._mqtt_handler.get_entity("current_max_offline_set").set_state(self._last_status_message.get_processed_value("current_max_offline"))
                    # After a reboot of device, the device that does not send offline will start with online value defined with offline setting                            
                    # as the device will start to use the offline current after 5 minutes without responses from server, we can consider that after this time
                    # we got the offline value from the online parameter, use the parameter after 6 minutes from first status message
                    elif (self._booted_in_less_than(30) or (elapsed > 6*60) ) and decoded_message.has_value("current_max_online"):
                        _LOGGER.info(f"setting current_max_offline_set with current_max_online after reboot or more than 5 minutes (elapsed={elapsed})") 
                        await self._mqtt_handler.get_entity("current_max_offline_set").set_state(self._last_status_message.get_processed_value("current_max_online"))
                            
            elif isinstance(decoded_message, JuiceboxDebugMessage):
                if decoded_message.is_boot():
                    self._boot_timestamp = time.time()
          
        except Exception as e:
            _LOGGER.exception(f"Not a valid juicebox message |{data}| {e}")
        
        return decoded_message
    
    async def _main_mitm_handler(self, data: bytes, from_addr: tuple[str, int]):
        if data is None or from_addr is None:
            return

        # _LOGGER.debug(f"JuiceboxMITM Recv: {data} from {from_addr}")
        if from_addr[0] != self._enelx_addr[0]:
            self._juicebox_addr = from_addr

        if from_addr == self._juicebox_addr:
            # Must decode message to give correct command response based on version
            # Also this decoded message can will passed to the mqtt handler to skip a new decoding
            decoded_message = await self._message_decode(data)

            data = await self._local_mitm_handler(data, decoded_message)

            if self._ignore_enelx:
                # Keep sending responses to local juicebox like the enelx servers using last values
                # the responses should be send only to valid JuiceboxStatusMessages
                if isinstance(decoded_message, JuiceboxStatusMessage):
                    await self.send_cmd_message_to_juicebox(new_values=False)
            else:
                try:
                    await self.send_data(data, self._enelx_addr)
                except OSError as e:
                    _LOGGER.warning(
                        f"JuiceboxMITM OSError {errno.errorcode[e.errno]} "
                        f"[{self._enelx_addr}]: {e}"
                    )
                    await self._local_mitm_handler(
                        f"JuiceboxMITM_OSERROR|server|{self._enelx_addr}|"
                        f"{errno.errorcode[e.errno]}|{e}"
                    )
                    await self._add_error()
        elif self._juicebox_addr is not None and from_addr == self._enelx_addr:
            if not self._ignore_enelx:
                data = await self._remote_mitm_handler(data)
                try:
                    await self.send_data(data, self._juicebox_addr)
                except OSError as e:
                    _LOGGER.warning(
                        f"JuiceboxMITM OSError {errno.errorcode[e.errno]} "
                        f"[{self._juicebox_addr}]: {e}"
                    )
                    await self._local_mitm_handler(
                        f"JuiceboxMITM_OSERROR|client|{self._juicebox_addr}|"
                        f"{errno.errorcode[e.errno]}|{e}"
                    )
                    await self._add_error()
            else:
                _LOGGER.info(f"JuiceboxMITM Ignoring From EnelX: {data}")
        else:
            _LOGGER.warning(f"JuiceboxMITM Unknown address: {from_addr}")

    async def send_data(
        self, data: bytes, to_addr: tuple[str, int], blocking_time: int = 0.1
    ):
        sent = False
        send_attempt = 1
        while not sent and send_attempt <= MAX_RETRY_ATTEMPT:
            if send_attempt != 1:
                _LOGGER.warning(
                    f"JuiceboxMITM Resending (Attempt: {send_attempt} of "
                    f"{MAX_RETRY_ATTEMPT}): {data} to {to_addr}"
                )
            send_attempt += 1

            if self._dgram is None:
                _LOGGER.warning("JuiceboxMITM Reconnecting.")
                await self._connect()

            try:
                async with asyncio.timeout(MITM_SEND_DATA_TIMEOUT):
                    async with self._sending_lock:
                        try:
                            await self._dgram.send(data, to_addr)
                        except asyncio_dgram.TransportClosed:
                            _LOGGER.warning(
                                "JuiceboxMITM Connection Lost while Sending."
                            )
                            await self._add_error()
                            self._dgram = None
                        else:
                            sent = True
            except TimeoutError as e:
                _LOGGER.warning(
                    f"Send Data timeout after {MITM_SEND_DATA_TIMEOUT} sec. "
                    f"({e.__class__.__qualname__}: {e})"
                )
                await self._add_error()
            await asyncio.sleep(max(blocking_time, 0.1))
        if not sent:
            raise ChildProcessError("JuiceboxMITM: Unable to send data.")

        # _LOGGER.debug(f"JuiceboxMITM Sent: {data} to {to_addr}")

    async def send_data_to_juicebox(self, data: bytes):
        await self.send_data(data, self._juicebox_addr)


    def is_mqtt_numeric_entity_defined(self, entity_name):
        entity = self._mqtt_handler.get_entity(entity_name)

        # TODO: not clear why sometimes "0" came at this point as string instead of numeric
        # Using same way on HA dashboard sometimes came 0.0 float and sometimes "0" str
        # _LOGGER.debug(f"is_mqtt_entity_defined {entity_name} {entity} {entity.state}")
        defined = entity and (isinstance(entity.state, int | float) or (isinstance(entity.state, str) and entity.state.isnumeric()))

        return defined
        
    async def __build_cmd_message(self, new_values):
       
       if type(self._last_status_message) is JuiceboxEncryptedMessage:
          _LOGGER.info("Responses for encrypted protocol not supported yet")
          return None
          
       # TODO: check which other versions can be considered as new_version of protocol
       # packet captures indicate that v07 uses old version
       new_version = self._last_status_message and (self._last_status_message.get_value("v") == "09u")
       if self._last_command:
          message = JuiceboxCommand(previous=self._last_command, new_version=new_version)
       else:
          message = JuiceboxCommand(new_version=new_version)
          # Should start with values 
          new_values = True
          
       if new_values:
           if (not self.is_mqtt_numeric_entity_defined("current_max_offline_set")) or (not self.is_mqtt_numeric_entity_defined("current_max_online_set")):
              _LOGGER.error("Must have both current_max(online|offline) defined to send command message")

              return None

           message.offline_amperage = int(self._mqtt_handler.get_entity("current_max_offline_set").state)
           message.instant_amperage = int(self._mqtt_handler.get_entity("current_max_online_set").state)
           
       _LOGGER.info(f"command message = {message} new_values={new_values} new_version={new_version}")

       self._last_command = message;
       return message.build()

    # Send a new message using values on mqtt entities
    async def send_cmd_message_to_juicebox(self, new_values):
       
       if self._mqtt_handler.get_entity("act_as_server").is_on():

          cmd_message = await self.__build_cmd_message(new_values)
          if cmd_message:
              _LOGGER.info(f"Sending command to juicebox {cmd_message} new_values={new_values}")
              await self.send_data(cmd_message.encode('utf-8'), self._juicebox_addr)

    async def set_mqtt_handler(self, mqtt_handler):
        self._mqtt_handler = mqtt_handler

    async def set_local_mitm_handler(self, local_mitm_handler):
        self._local_mitm_handler = local_mitm_handler

    async def set_remote_mitm_handler(self, remote_mitm_handler):
        self._remote_mitm_handler = remote_mitm_handler

    async def _add_error(self):
        self._error_timestamp_list.append(time.time())
        time_cutoff = time.time() - (ERROR_LOOKBACK_MIN * 60)
        temp_list = list(
            filter(lambda el: el > time_cutoff, self._error_timestamp_list)
        )
        self._error_timestamp_list = temp_list
        self._error_count = len(self._error_timestamp_list)
        _LOGGER.debug(f"Errors in last {ERROR_LOOKBACK_MIN} min: {self._error_count}")
