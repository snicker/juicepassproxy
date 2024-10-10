import asyncio
import logging
import re
import time

import ha_mqtt_discoverable.sensors as ha_mqtt
from const import ERROR_LOOKBACK_MIN, VERSION  # MAX_ERROR_COUNT,
from ha_mqtt_discoverable import DeviceInfo, Settings
from paho.mqtt.client import Client, MQTTMessage
from juicebox_message import JuiceboxStatusMessage, JuiceboxDebugMessage

_LOGGER = logging.getLogger(__name__)
MQTT_SENDING_ENTITIES = ["text", "number", "switch", "button"]


class JuiceboxMQTTEntity:
    def __init__(
        self,
        name,
        **kwargs,
    ):
        # _LOGGER.debug(f"Entity Init: {name}")
        self.name = name
        self._kwargs = kwargs
        self._process_kwargs()
        self._state = None
        self.attributes = {}
        self._mqtt = None
        self._loop = asyncio.get_running_loop()
        # self.entity_type  # Each use of this class to create a child class needs to set this variable in __init__
        # self._set_func  # Each use of this class to create a child class needs to set this variable in __init__

    def add_kwargs(self, **kwargs):
        self._kwargs.update(kwargs)
        self._process_kwargs()

    def _process_kwargs(self):
        self._kwargs.update(
            {
                "name": self.name,
                "unique_id": f"{self._kwargs.get('juicebox_id', None)} {self.name}",
            }
        )
        self.experimental = self._kwargs.get("experimental", False)
        self._unique_id = f"{self._kwargs.get('juicebox_id', None)} {self.name}"
        self._mitm_handler = self._kwargs.get("mitm_handler", None)
        self._add_error = self._kwargs.get("add_error_func", None)

    @property
    def state(self):
        return self._state

    async def start(self):
        entity_info_keys = getattr(
            ha_mqtt, f"{self.entity_type.title()}Info"
        ).__fields__.keys()
        entity_info = {}
        for key in entity_info_keys:
            if self._kwargs.get(key, None) is not None:
                entity_info.update({key: self._kwargs.get(key, None)})
        self._mqtt = getattr(ha_mqtt, f"{self.entity_type.title()}")(
            Settings(
                mqtt=self._kwargs.get("mqtt", self._kwargs.get("mqtt_settings", None)),
                entity=getattr(ha_mqtt, f"{self.entity_type.title()}Info").parse_obj(
                    entity_info
                ),
            )
        )

        if self._kwargs.get("initial_state", None) is not None:
            await self.set(self._kwargs.get("initial_state", None))

    async def close(self):
        if self._mqtt is not None:
            self._mqtt.mqtt_client.disconnect()

    async def set_state(self, state):
        await self.set(state)

    async def set(self, state=None):
        self._state = state
        try:
            if self.entity_type == 'number':
                # float to be used by any number, JuiceboxMessage will use int
                getattr(self._mqtt, self._set_func)(float(state))
            elif self.entity_type == 'switch':
                # float to be used by any number, JuiceboxMessage will use int
                getattr(self._mqtt, self._set_func)(state.lower() == 'on')
            else:
                getattr(self._mqtt, self._set_func)(state)
        except AttributeError as e:
            if self._add_error is not None:
                await self._add_error()
            _LOGGER.warning(
                f"Can't update attributes for {self.name} "
                "as MQTT isn't connected/started. "
                f"({e.__class__.__qualname__}: {e})"
            )

    async def set_attributes(self, attr={}):
        self.attributes = attr
        try:
            self._mqtt.set_attributes(attr)
        except AttributeError as e:
            if self._add_error is not None:
                await self._add_error()
            _LOGGER.warning(
                f"Can't update attributes for {self.name} "
                "as MQTT isn't connected/started. "
                f"({e.__class__.__qualname__}: {e})"
            )


class JuiceboxMQTTSendingEntity(JuiceboxMQTTEntity):
    def __init__(
        self,
        name,
        **kwargs,
    ):
        # _LOGGER.debug(f"SendingEntity Init: {name}")
        super().__init__(name, **kwargs)
        self.command_timestamp = None

    async def start(self):
        entity_info_keys = getattr(
            ha_mqtt, f"{self.entity_type.title()}Info"
        ).__fields__.keys()
        entity_info = {}
        for key in entity_info_keys:
            if self._kwargs.get(key, None) is not None:
                entity_info.update({key: self._kwargs.get(key, None)})
        self._mqtt = getattr(ha_mqtt, f"{self.entity_type.title()}")(
            Settings(
                mqtt=self._kwargs.get("mqtt", self._kwargs.get("mqtt_settings", None)),
                entity=getattr(ha_mqtt, f"{self.entity_type.title()}Info").parse_obj(
                    entity_info
                ),
            ),
            command_callback=self._callback,
            user_data=self._kwargs.get("user_data", None),
        )

        if self._kwargs.get("initial_state", None) is not None:
            await self.set(self._kwargs.get("initial_state", None))
        elif self.entity_type == 'number':
            # The state will came on juicebox messages
            _LOGGER.warning(f"{self.name} has no initial_state")
        else:
            await self.set(self.name)

    def _callback(self, client: Client, user_data, message: MQTTMessage):
        self._loop.create_task(self._callback_async(client, user_data, message))

    async def _callback_async(self, client: Client, user_data, message: MQTTMessage):
        """
        Currently, this just sends the received message to the JuiceBox.
        Likely, this callback will either need to be built out to build a working
        CMD or the callback will call a method that builds a working CMD.
        """
        state = message.payload.decode()
        _LOGGER.info(
            f"{self.entity_type.title()} Callback ({self.name}): "
            f"{state}. User Data: {user_data}"
        )
        if self._mitm_handler:
            if user_data == 'RAW':
                _LOGGER.debug(f"Sending to MITM: {state}")
                await self._mitm_handler.send_data_to_juicebox(state.encode("utf-8"))
            else:
                # Internal state must be set before sending message to juicebox
                await self.set(state)
                self.command_timestamp = time.time()
                await self._mitm_handler.send_cmd_message_to_juicebox(new_values=True)
        else:
            if self._add_error is not None:
                await self._add_error()
            _LOGGER.warning(
                f"Cannot send to MITM. mitm_handler type: {type(self._mitm_handler)}"
            )
        await self.set(state)


class JuiceboxMQTTSensor(JuiceboxMQTTEntity):
    def __init__(
        self,
        name,
        **kwargs,
    ):
        # _LOGGER.debug(f"Sensor Init: {name}")
        self.entity_type = "sensor"
        self._set_func = "set_state"
        super().__init__(name, **kwargs)


class JuiceboxMQTTNumber(JuiceboxMQTTSendingEntity):
    def __init__(
        self,
        name,
        **kwargs,
    ):
        # _LOGGER.debug(f"Number Init: {name}")
        self.entity_type = "number"
        self._set_func = "set_value"
        super().__init__(name, **kwargs)



class JuiceboxMQTTSwitch(JuiceboxMQTTSendingEntity):
    def __init__(
        self,
        name,
        **kwargs,
    ):
        # _LOGGER.debug(f"Boolean Init: {name}")
        self.entity_type = "switch"
        self._set_func = "update_state"
        super().__init__(name, **kwargs)


    def is_on(self):

        if type(self.state) is str:
           return self.state.lower() == 'on'
           
        return self.state


class JuiceboxMQTTText(JuiceboxMQTTSendingEntity):
    def __init__(
        self,
        name,
        **kwargs,
    ):
        # _LOGGER.debug(f"Text Init: {name}")
        self.entity_type = "text"
        self._set_func = "set_text"
        super().__init__(name, **kwargs)

    async def set_text(self, state):
        await self.set(state)


class JuiceboxMQTTHandler:
    def __init__(
        self,
        device_name,
        mqtt_settings,
        experimental,
        config,
        juicebox_id=None,
        mitm_handler=None,
        loglevel=None,
    ):
        if loglevel is not None:
            _LOGGER.setLevel(loglevel)
        self._mqtt_settings = mqtt_settings
        self._device_name = device_name
        self._juicebox_id = juicebox_id
        self._experimental = experimental
        self._config = config
        self._mitm_handler = mitm_handler
        # Try to use first the MAX_CURRENT as maximum, if not found use the previous run current_rating or default of 48 which is safe and not so big
        self._max_current = config.get_device(self._juicebox_id, "MAX_CURRENT", config.get_device(self._juicebox_id, "current_rating", 48))
        _LOGGER.info(f"max_current: {self._max_current}")
        self._error_count = 0
        self._error_timestamp_list = []

        self._device = DeviceInfo(
            name=self._device_name,
            identifiers=(
                [self._juicebox_id]
                if self._juicebox_id is not None
                else [self._device_name]
            ),
            connections=[
                (
                    ["JuiceBox ID", self._juicebox_id]
                    if self._juicebox_id is not None
                    else []
                )
            ],
            manufacturer="EnelX",
            model="JuiceBox",
            sw_version=VERSION,
            via_device="JuicePass Proxy",
        )

        self._entities = {
            "status": JuiceboxMQTTSensor(
                name="Status",
                icon="mdi:ev-station",
                expire_after=7200,
            ),
            "current": JuiceboxMQTTSensor(
                name="Current",
                state_class="measurement",
                device_class="current",
                unit_of_measurement="A",
                expire_after=7200,
            ),
            # Maximum supported by device
            "current_rating": JuiceboxMQTTSensor(
                name="Current Rating",
                device_class="current",
                unit_of_measurement="A",
                expire_after=7200,
            ),
            # Offline max 
            "current_max_offline": JuiceboxMQTTSensor(
                name="Max Current(Offline/Device)",
                state_class="measurement",
                device_class="current",
                unit_of_measurement="A",
                expire_after=7200,
            ),
            "current_max_offline_set": JuiceboxMQTTNumber(
                name="Max Current(Offline/Wanted)",
                device_class="current",
                unit_of_measurement="A",
                min=0,
                max=self._max_current,
                # no initial state, to use the value that will be received from juicebox or from config
                # because of this, the entity will only show later (first time) on homeassistant when value is set
                # and can change the homeassistant value
            ),
            # Instant / Charging current
            "current_max_online": JuiceboxMQTTSensor(
                name="Max Current(Online/Device)",
                state_class="measurement",
                device_class="current",
                unit_of_measurement="A",
                expire_after=7200,
            ),
            "current_max_online_set": JuiceboxMQTTNumber(
                name="Max Current(Online/Wanted)",
                device_class="current",
                unit_of_measurement="A",
                min=0,
                max=self._max_current,
                # no initial state, to use the value that will be received from juicebox or from config
                # because of this, the entity will only show later (first time) on homeassistant when value is set
                # and can change the homeassistant value
            ),
            "frequency": JuiceboxMQTTSensor(
                name="Frequency",
                state_class="measurement",
                device_class="frequency",
                unit_of_measurement="Hz",
                expire_after=7200,
            ),
            "energy_lifetime": JuiceboxMQTTSensor(
                name="Energy (Lifetime)",
                state_class="total_increasing",
                device_class="energy",
                unit_of_measurement="Wh",
                expire_after=7200,
            ),
            "energy_session": JuiceboxMQTTSensor(
                name="Energy (Session)",
                state_class="total_increasing",
                device_class="energy",
                unit_of_measurement="Wh",
                expire_after=7200,
            ),
            "temperature": JuiceboxMQTTSensor(
                name="Temperature",
                state_class="measurement",
                device_class="temperature",
                unit_of_measurement="°F",
                expire_after=7200,
            ),
            "voltage": JuiceboxMQTTSensor(
                name="Voltage",
                state_class="measurement",
                device_class="voltage",
                unit_of_measurement="V",
                expire_after=7200,
            ),
            "power": JuiceboxMQTTSensor(
                name="Power",
                state_class="measurement",
                device_class="power",
                unit_of_measurement="W",
                expire_after=7200,
            ),
            # Make possible to control from HA when juicepassproxy will act as ENEL X server for the juicebox
            # Will only work when ignoring ENEL X server
            "act_as_server": JuiceboxMQTTSwitch(
                name="Act as Server",
                enabled_by_default=False,
                # As will only work when ignoring ENEL X server, True appear to be good for initial state
                initial_state="ON",
            ),
            "debug_message": JuiceboxMQTTSensor(
                name="Last Debug Message",
                enabled_by_default=False,
                icon="mdi:bug",
                entity_category="diagnostic",
                initial_state=f"INFO: Starting JuicePass Proxy {VERSION}",
                expire_after=0, # Keep last message available
            ),
            "data_from_juicebox": JuiceboxMQTTSensor(
                name="Data from JuiceBox",
                experimental=True,
                enabled_by_default=False,
                entity_category="diagnostic",
                expire_after=0, # Keep last message available
            ),
            "data_from_enelx": JuiceboxMQTTSensor(
                name="Data from EnelX",
                experimental=True,
                enabled_by_default=False,
                entity_category="diagnostic",
                expire_after=0, # Keep last message available
            ),
            "send_to_juicebox": JuiceboxMQTTText(
                name="Send Command to JuiceBox",
                user_data="RAW",
                experimental=True,
                enabled_by_default=False,
            ),
        }
        
        _LOGGER.info("Checking for initial_states on config")        
        for key in self._entities.keys():
            initial_state = self._config.get_device(self._juicebox_id, key + "_initial_state", None)
            if initial_state:
                _LOGGER.info(f"got initial_state on config : {key} -> {initial_state}")
                self._entities[key].add_kwargs(initial_state=initial_state)
                
        for entity in self._entities.values():
            entity.add_kwargs(
                juicebox_id=self._juicebox_id,
                device=self._device,
                mqtt_settings=self._mqtt_settings,
                add_error_func=self._add_error,
            )
            if entity.entity_type in MQTT_SENDING_ENTITIES:
                entity.add_kwargs(mitm_handler=self._mitm_handler)

    def get_entity(self, name):
        return self._entities[name]
        
    async def start(self):
        _LOGGER.info("Starting JuiceboxMQTTHandler")

        # while self._error_count < MAX_ERROR_COUNT:
        mqtt_task_list = []
        for entity in self._entities.values():
            if entity.experimental is False or self._experimental is True:
                mqtt_task_list.append(asyncio.create_task(entity.start()))
        await asyncio.gather(
            *mqtt_task_list,
        )

    async def close(self):
        for entity in self._entities.values():
            await entity.close()

    async def set_mitm_handler(self, mitm_handler):
        self._mitm_handler = mitm_handler
        for entity in self._entities.values():
            if entity.entity_type in MQTT_SENDING_ENTITIES:
                entity.add_kwargs(mitm_handler=mitm_handler)

    # TODO: To be removed as the the message is now parsed on JuiceboxMessage
    async def _basic_message_parse(self, data: bytes):

        message = {"type": "basic", "current": 0, "energy_session": 0}
        active = True
        
        parts = re.split(r",|!|:", data.decode("utf-8"))
        parts.pop(0)  # JuiceBox ID
        parts.pop(-1)  # Ending blank
        parts.pop(-1)  # CRC

        for part in parts:
            if part[0] == "S":
                message["status"] = {
                    "S0": "Unplugged",
                    "S1": "Plugged In",
                    "S2": "Charging",
                    "S5": "Error",
                    "S00": "Unplugged",
                    "S01": "Plugged In",
                    "S02": "Charging",
                    "S05": "Error",
                }.get(part)
                if message["status"] is None:
                    message["status"] = f"unknown {part}"
                active = message["status"].lower() == "charging"
            elif part[0] == "A":
                message["current"] = (
                    round(float(part.split("A")[1]) * 0.1, 2) if active else 0
                )
            elif part[0] == "m":
                message["current_rating"] = float(part.split("m")[1])
            elif part[0] == "C":
                message["current_max_offline"] = float(part.split("C")[1])
            elif part[0] == "M":
                message["current_max_online"] = float(part.split("M")[1])
            elif part[0] == "f":
                message["frequency"] = round(float(part.split("f")[1]) * 0.01, 2)
            elif part[0] == "L":
                message["energy_lifetime"] = float(part.split("L")[1])
            elif part[0] == "v":
                message["protocol_version"] = part.split("v")[1]
            elif part[0] == "E":
                message["energy_session"] = float(part.split("E")[1]) if active else 0
            elif part[0] == "t":
                message["report_time"] = part.split("t")[1]
            elif part[0] == "v":
                message["protocol_version"] = part.split("v")[1]
            elif part[0] == "i":
                message["interval"] = part.split("i")[1]
            elif part[0] == "u":
                message["loop_counter"] = part.split("u")[1]
            elif part[0] == "T":
                message["temperature"] = round(float(part.split("T")[1]) * 1.8 + 32, 2)
            elif part[0] == "V":
                # Device that does not send protocol_version dont send decimal value for Voltage
                if message["protocol_version"]:
                    message["voltage"] = round(float(part.split("V")[1]) * 0.1, 2)
                else:
                    message["voltage"] = round(float(part.split("V")[1]), 2)
            else:
                message["unknown_" + part[0]] = part[1:]
        message["power"] = round(
            message.get("voltage", 0) * message.get("current", 0), 2
        )

        message["data_from_juicebox"] = data.decode("utf-8")
        return message

    async def _udp_mitm_oserror_message_parse(self, data):
        message = {"type": "udp_mitm_oserror"}
        err_data = str(data).split("|")
        message["status"] = "unavailable"
        message["debug_message"] = (
            f"JuiceboxMITM {err_data[1].title()} OSError {err_data[3]} "
            f"[{err_data[2]}]: {err_data[4]}"
        )
        return message

    async def _debug_message_parse(self, data):
        message = {"type": "debug"}

        dbg_data = (
            data.decode("utf-8")
            .replace("https://", "https//")
            .replace("http://", "http//")
        )
        dbg_level_abbr = dbg_data.split(":")[1].split(",")[1]
        if dbg_level_abbr == "NFO":
            dbg_level = "INFO"
        elif dbg_level_abbr == "WRN":
            dbg_level = "WARNING"
        elif dbg_level_abbr == "ERR":
            dbg_level = "ERROR"
        else:
            dbg_level = dbg_level_abbr
        dbg_data = dbg_data[dbg_data.find(":", dbg_data.find(":") + 1) + 1: -1]
        dbg_msg = dbg_data.replace("https//", "https://").replace("http//", "http://")

        message["debug_message"] = f"{dbg_level}: {dbg_msg}"
        return message

    async def _store_if_on_message(self, message, key):
        if key in message:
            self._config.update_device_value(self._juicebox_id, key, message[key])
            await self._config.write_if_changed()
            
    async def _basic_message_publish(self, message):
        _LOGGER.debug(f"Publish {message.get('type').title()} Message: {message}")

        # try:
        attributes = {}
        
        # This values are usefull when JPP starts again to start fast
        await self._store_if_on_message(message, "current_rating")
        await self._store_if_on_message(message, "current_max_offline")
        
        for k in message:
            entity = self._entities.get(k, None)
            if entity and (entity.experimental is False or self._experimental is True):

                await entity.set_state(message.get(k, None))
                    
            attributes[k] = message.get(k, None)
        if (
            self._experimental
            and self._entities.get("data_from_juicebox", None) is not None
        ):
            attributes.pop("data_from_juicebox", None)
            attr_sorted = dict(sorted(attributes.items()))
            unknown_attr = {}
            for key in list(attr_sorted.keys()):
                if key.startswith("unknown"):
                    unknown_attr.update({key: attr_sorted.pop(key, None)})
            attr_sorted.update(unknown_attr)
            await self._entities.get("data_from_juicebox").set_attributes(attr_sorted)
        # except Exception as e:
        #    _LOGGER.exception(
        #        f"Failed to publish sensor data to MQTT. ({e.__class__.__qualname__}: {
        #            e})"
        #    )

    async def remote_mitm_handler(self, data):
        try:
            _LOGGER.debug(f"From EnelX: {data}")
            if (
                self._experimental
                and self._entities.get("data_from_enelx", None) is not None
            ):
                await self._entities.get("data_from_enelx").set_state(
                    data.decode("utf-8")
                )

            return data
        except IndexError as e:
            await self._add_error()
            _LOGGER.warning(
                "Index error when handling remote data, probably wrong number of items in list. "
                "Nothing to worry about unless this happens a lot. "
                f"({e.__class__.__qualname__}: {e})"
            )
        # except Exception as e:
        #    _LOGGER.exception(
        #        f"Exception handling remote data. ({e.__class__.__qualname__}: {e})"
        #    )

    async def local_mitm_handler(self, data, decoded_message):
        message = None
        try:
            _LOGGER.debug(f"From JuiceBox: {data} decoded={decoded_message}")            
            if "JuiceboxMITM_OSERROR" in str(data):
                message = await self._udp_mitm_oserror_message_parse(data)
                
            # Now using the classes as priority over older code
            elif isinstance(decoded_message, JuiceboxStatusMessage):
                message = decoded_message.to_simple_format()
            elif isinstance(decoded_message, JuiceboxDebugMessage):
                message = decoded_message.to_simple_format()
            # still using old code for messages that cannot be decoded                
            # should be removed in future versions
            elif ":DBG," in str(data):
                message = await self._debug_message_parse(data)
            else:
                message = await self._basic_message_parse(data)
        
            _LOGGER.debug(f"decode/parsed message = {message}")
            
            # Something is wrong if device is changed
            # as the entities use the juicebox_id as unique_id this should not happen
            if "serial" in message:
                if message["serial"] != self._juicebox_id:
                    _LOGGER.error(f"serial {message['serial']} on received message does not match juicebox_id {self._juicebox_id}")
                    # For now just give the error, but will be better to dont send values on entities and return 
            
            if message:
                await self._basic_message_publish(message)
            return data
        except IndexError as e:
            await self._add_error()
            _LOGGER.warning(
                "Index error when handling local data, probably wrong number of items in list"
                "Nothing to worry about unless this happens a lot. "
                f"({e.__class__.__qualname__}: {e})"
            )
        # except Exception as e:
        #    _LOGGER.exception(
        #        f"Exception handling local data. ({e.__class__.__qualname__}: {e})"
        #    )

    async def _add_error(self):
        self._error_timestamp_list.append(time.time())
        time_cutoff = time.time() - (ERROR_LOOKBACK_MIN * 60)
        temp_list = list(
            filter(lambda el: el > time_cutoff, self._error_timestamp_list)
        )
        self._error_timestamp_list = temp_list
        self._error_count = len(self._error_timestamp_list)
        _LOGGER.debug(f"Errors in last {ERROR_LOOKBACK_MIN} min: {self._error_count}")
