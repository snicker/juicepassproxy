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
from juicebox_mitm_device import JuiceboxMITMDevice
from juicebox_mqtthandler import JuiceboxMQTTHandler

# Began with https://github.com/rsc-dev/pyproxy and rewrote when moving to async.

_LOGGER = logging.getLogger(__name__)


class JuiceboxMITM:

    def __init__(
        self,
        jpp_addr,
        device_name_prefix,
        enelx_addr,
        local_mitm_handler=None,
        ignore_enelx=False,
        remote_mitm_handler=None,
        mqtt_settings=None,
        loglevel=None,
        reuse_port=True,
        config=None,
        experimental=False
    ):
        if loglevel is not None:
            _LOGGER.setLevel(loglevel)
        self._jpp_addr = jpp_addr
        self._device_name_prefix = device_name_prefix
        self._enelx_addr = enelx_addr
        self._ignore_enelx = ignore_enelx
        self._local_mitm_handler = local_mitm_handler
        self._remote_mitm_handler = remote_mitm_handler
        self._mqtt_settings = mqtt_settings
        self._reuse_port = reuse_port
        self._loop = asyncio.get_running_loop()
        self._mitm_loop_task: asyncio.Task = None
        self._sending_lock = asyncio.Lock()
        self._dgram = None
        self._error_count = 0
        self._error_timestamp_list = []
        self._config = config
        self._experimental = experimental

        self._devices = {}

    async def start(self) -> None:
        _LOGGER.info(f"Starting JuiceboxMITM at {self._jpp_addr[0]}:{self._jpp_addr[1]} reuse_port={self._reuse_port}")
        _LOGGER.debug(f"EnelX: {self._enelx_addr[0]}:{self._enelx_addr[1]}")

        await self._connect()

    async def close(self):
        if self._dgram is not None:
            self._dgram.close()
            self._dgram = None
            await asyncio.sleep(3)
        
        for device in self._devices.values():
            if not device._mqtt_handler is None:
                await device._mqtt_handler.close()
                del device._mqtt_handler

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
                        self._jpp_addr, reuse_port=self._reuse_port
                    )
                else:
                    async with self._sending_lock:
                        self._dgram = await asyncio_dgram.bind(
                            self._jpp_addr, reuse_port=self._reuse_port
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

    async def _message_decode(self, data : bytes):
        decoded_message = None
        device = None
        try:
            decoded_message = juicebox_message_from_bytes(data)
            if isinstance(decoded_message, JuiceboxEncryptedMessage):
                # encrypted are not supported now
                # directory server can set the encripted mode, to disable the JuiceBox must be blocked to access the Directory Server
                _LOGGER.error("Encrypted messages are not supported yet, please restart yout Juicebox device without internet connection to be able to use unencrypted messages")
            elif isinstance(decoded_message, JuiceboxStatusMessage):
                # Decode the message and map it to a JuiceboxMITMDevice
                if decoded_message.has_value("serial"):
                    device_serial = decoded_message.get_value("serial");
                    # Default device name using the last 8 chars of the serial number
                    device_name = f"{self._device_name_prefix}{device_serial[-8:]}"
                    # Override the device name from the config file, if it is configured
                    device_name = self._config.get_device(device_serial, "name", device_name)
                    _LOGGER.info(f"Received Message from {device_name}")
                    device = self._devices.get(device_serial, None)
                    if not device:
                        # Initialize a new device with MQTT handler for each unique device which is seen
                        _LOGGER.info(f"Adding {device_name} for juicebox_id/serial {device_serial}")
                        self._config.update_device_value(device_serial, "name", device_name)
                        await self._config.write_if_changed()
                        mqtt_handler = JuiceboxMQTTHandler(
                            mqtt_settings=self._mqtt_settings,
                            device_name=device_name,
                            juicebox_id=device_serial,
                            config=self._config,
                            experimental=self._experimental,
                            loglevel=_LOGGER.getEffectiveLevel(),
                            mitm_handler=self
                        )
                        device = self._devices[device_serial] = JuiceboxMITMDevice(mqtt_handler)
                        await device._mqtt_handler.set_device(device)
                        await device._mqtt_handler.start()

                device._last_status_message = decoded_message
                if device._first_status_message_timestamp is None:
                   device._first_status_message_timestamp = time.time()
                elapsed = int(time.time() - device._first_status_message_timestamp)

                # Try to initialize the set entities with safe values from the juicebox device
                # This is not the best way to do, but can be made without need to store somewhere the data as config is not available here
                # TODO: better/safer way
                if not device._mqtt_handler.is_mqtt_numeric_entity_defined("current_max_online_set"):
                    if decoded_message.has_value("current_max_online"):
                        _LOGGER.info("setting current_max_online_set with current_max_online")
                        await device._mqtt_handler.get_entity("current_max_online_set").set_state(device._last_status_message.get_processed_value("current_max_online"))
                        
                    # Apparently all messages came with current_max_online then, this code will never be executed                            
                    elif ((elapsed > 600) or device._booted_in_less_than(30)) and decoded_message.has_value("current_rating"):
                        _LOGGER.info("setting current_max_online_set with current_rating")
                        await device._mqtt_handler.get_entity("current_max_online_set").set_state(device._last_status_message.get_processed_value("current_rating"))

                #TODO now the MQTT is storing previous data on config, this can be used to get initialize theses values from previous JPP execution
                if not device._mqtt_handler.is_mqtt_numeric_entity_defined("current_max_offline_set"): 
                    if decoded_message.has_value("current_max_offline"):
                        _LOGGER.info("setting current_max_offline_set with current_max_offline")
                        await device._mqtt_handler.get_entity("current_max_offline_set").set_state(device._last_status_message.get_processed_value("current_max_offline"))
                    # After a reboot of device, the device that does not send offline will start with online value defined with offline setting                            
                    # as the device will start to use the offline current after 5 minutes without responses from server, we can consider that after this time
                    # we got the offline value from the online parameter, use the parameter after 6 minutes from first status message
                    elif (self._booted_in_less_than(30) or (elapsed > 6*60) ) and decoded_message.has_value("current_max_online"):
                        _LOGGER.info(f"setting current_max_offline_set with current_max_online after reboot or more than 5 minutes (elapsed={elapsed})") 
                        await device._mqtt_handler.get_entity("current_max_offline_set").set_state(device._last_status_message.get_processed_value("current_max_online"))

                #TODO we still have a problem on v07 protocol that does not send the current_max_offline
                # the entity will not be updated
                            
            elif isinstance(decoded_message, JuiceboxDebugMessage):
                if decoded_message.is_boot():
                    device._boot_timestamp = time.time()
            else:
                _LOGGER.exception(f"Unexpected juicebox message type {decoded_message}")
          
        except Exception as e:
            _LOGGER.exception(f"Not a valid juicebox message |{data}| {e}")
        
        return device, decoded_message
    
    async def _main_mitm_handler(self, data: bytes, from_addr: tuple[str, int]):
        if data is None or from_addr is None:
            return

        # _LOGGER.debug(f"JuiceboxMITM Recv: {data} from {from_addr}")
        if from_addr[0] != self._enelx_addr[0]:
            # Must decode message to give correct command response based on version
            # Also this decoded message can will passed to the mqtt handler to skip a new decoding
            device, decoded_message = await self._message_decode(data)
            if device is not None:
                device._juicebox_addr = from_addr

                data = await device._mqtt_handler.local_mitm_handler(data, decoded_message)

                if self._ignore_enelx:
                    # Keep sending responses to local juicebox like the enelx servers using last values
                    # the responses should be send only to valid JuiceboxStatusMessages
                    if isinstance(decoded_message, JuiceboxStatusMessage):
                        await self.send_cmd_message_to_juicebox(device, new_values=False)
                else:
                    try:
                        await self.send_data(data, self._enelx_addr)
                    except OSError as e:
                        _LOGGER.warning(
                            f"JuiceboxMITM OSError {errno.errorcode[e.errno]} "
                            f"[{self._enelx_addr}]: {e}"
                        )
                        await device._mqtt_handler.local_mitm_handler(
                            f"JuiceboxMITM_OSERROR|server|{self._enelx_addr}|"
                            f"{errno.errorcode[e.errno]}|{e}"
                        )
                        await self._add_error()
        # TODO: DETERMINE HOW BEST TO SUPPORT ENELX MESSAGES; UNABLE TO TEST
        # CAN THE MESSAGE BE DECODED TO DETERMINE THE SERIAL NUMBER TO LOOK UP THE DEVICE?
        # elif from_addr == self._enelx_addr:
        #     if not self._ignore_enelx:
        #         data = await self._remote_mitm_handler(data)
        #         try:
        #             await self.send_data(data, device._juicebox_addr)
        #         except OSError as e:
        #             _LOGGER.warning(
        #                 f"JuiceboxMITM OSError {errno.errorcode[e.errno]} "
        #                 f"[{device._juicebox_addr}]: {e}"
        #             )
        #             await self._local_mitm_handler(
        #                 f"JuiceboxMITM_OSERROR|client|{device._juicebox_addr}|"
        #                 f"{errno.errorcode[e.errno]}|{e}"
        #             )
        #             await self._add_error()
        #     else:
        #         _LOGGER.info(f"JuiceboxMITM Ignoring From EnelX: {data}")
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

    async def send_data_to_juicebox(self, device, data: bytes):
        await self.send_data(data, device._juicebox_addr)
       
    async def __build_cmd_message(self, device, new_values):
       
       if type(device._last_status_message) is JuiceboxEncryptedMessage:
          _LOGGER.info("Responses for encrypted protocol not supported yet")
          return None
          
       # TODO: check which other versions can be considered as new_version of protocol
       # packet captures indicate that v07 uses old version
       new_version = device._last_status_message and (device._last_status_message.get_value("v") == "09u")
       if device._last_command:
          message = JuiceboxCommand(previous=device._last_command, new_version=new_version)
       else:
          message = JuiceboxCommand(new_version=new_version)
          # Should start with values 
          new_values = True
          
       if new_values:
           if (not device._mqtt_handler.is_mqtt_numeric_entity_defined("current_max_offline_set")) or (not device._mqtt_handler.is_mqtt_numeric_entity_defined("current_max_online_set")):
              _LOGGER.error("Must have both current_max(online|offline) defined to send command message")

              return None

           message.offline_amperage = int(device._mqtt_handler.get_entity("current_max_offline_set").state)
           message.instant_amperage = int(device._mqtt_handler.get_entity("current_max_online_set").state)
           
       _LOGGER.info(f"command message = {message} new_values={new_values} new_version={new_version}")

       device._last_command = message;
       return message.build()

    # Send a new message using values on mqtt entities
    async def send_cmd_message_to_juicebox(self, device, new_values):
       if device is None:
           _LOGGER.error(f"mitmdevice parameter is none when sending command to juicebox")
       if device._mqtt_handler is None:
           _LOGGER.error(f"mitmdevice._mqtt_handler parameter is none when sending command to juicebox")

       if not self._ignore_enelx:
          _LOGGER.warning("To send commands to juicebox you have to ignore ENEL X servers, please set ignore_enelx option")
          
       elif device._mqtt_handler.get_entity("act_as_server").is_on():

          cmd_message = await self.__build_cmd_message(device, new_values)
          if cmd_message:
              _LOGGER.info(f"Sending command to juicebox {cmd_message} new_values={new_values}")
              await self.send_data(cmd_message.encode('utf-8'), device._juicebox_addr)


    async def _add_error(self):
        self._error_timestamp_list.append(time.time())
        time_cutoff = time.time() - (ERROR_LOOKBACK_MIN * 60)
        temp_list = list(
            filter(lambda el: el > time_cutoff, self._error_timestamp_list)
        )
        self._error_timestamp_list = temp_list
        self._error_count = len(self._error_timestamp_list)
        _LOGGER.debug(f"Errors in last {ERROR_LOOKBACK_MIN} min: {self._error_count}")
