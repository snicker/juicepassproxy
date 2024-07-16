#
# Original source  : https://github.com/philipkocanda/juicebox-protocol
#
from juicebox_checksum import JuiceboxChecksum
from juicebox_exceptions import JuiceboxInvalidMessageFormat
import datetime
import logging
import re

_LOGGER = logging.getLogger(__name__)

STATUS_CHARGING = "Charging"
STATUS_ERROR = "Error"
STATUS_PLUGGED_IN = "Plugged In"
STATUS_UNPLUGGED = "Unplugged"


STATUS_DEFS = { 
    0: STATUS_UNPLUGGED,
    1: STATUS_PLUGGED_IN,
    2: STATUS_CHARGING,
    5: STATUS_ERROR
    }


FIELD_SERIAL = "serial"
FIELD_CURRENT = "current"

  
def process_status(message, value):
    if value and value.isnumeric() and (int(value) in STATUS_DEFS):
       return STATUS_DEFS[int(value)]
    
    # Old Protocol does not send status in all messages
    # try to detect state based on current
    if (value is None) and message.has_value(FIELD_CURRENT) and message.get_value(FIELD_CURRENT).isnumeric():
       current = int(message.get_value(FIELD_CURRENT))
       # must test more to know if they send messages like this when Unplugged
       if current == 0:
          return STATUS_PLUGGED_IN
          
       if current > 0:
          return STATUS_CHARGING

    return f"unknown {value}"
    
def process_voltage(message, value):
    # Older messages came with less digits
    if len(value) < 4:
        return float(value)

    return float(value) * 0.1
    

FROM_JUICEBOX_FIELD_DEFS = {
    # Undefined parts: F, e, r, b, B, P, p
    # https://github.com/snicker/juicepassproxy/issues/52
    "A" : { "alias" : "current" },
    "C" : { "alias" : "current_max" },
    "E" : { "alias" : "energy_session" },
    "f" : { "alias" : "frequency" },
    # i = Interval number. It contains a 96-slot interval memory (15-minute x 24-hour cycle) and
    #   this tells you how much energy was consumed in the rolling window as it reports one past
    #   (or current, if it's reporting the "right-now" interval) interval per message.
    #   The letter after "i" = the energy in that interval (usually 0 if you're not charging basically 24/7)
    "i" : { "alias" : "interval" },
    "m" : { "alias" : "current_rating" },
    "M" : { "alias" : "current_max_charging" },
    "L" : { "alias" : "energy_lifetime" },
    "s" : { "alias" : "counter" },
    "S" : { "alias" : "status", "process" : process_status },
    # t - probably the report time in seconds - "every 9 seconds" (or may end up being 10).
    #   It can change its reporting interval if the bit mask in the reply command indicates that it should send reports faster (yet to be determined).
    "t" : { "alias" : "report_time" },
    "T" : { "alias" : "temperature" },
    "u" : { "alias" : "loop_counter" },
    "v" : { "alias" : "protocol_version" },
    "V" : { "alias" : "voltage", "process" : process_voltage },
    }


#
# try to detect message format and use correct decoding process
#
def juicebox_message_from_bytes(data : bytes):
   ## TODO: try to detect here if message is encrypted or not
   # Currently all non encrypted messages that we have capture can be converted to string
   try:
       string = data.decode("utf-8")
       return juicebox_message_from_string(string)
   except UnicodeDecodeError as e:
       # Probably is a encrypted messsage
       return JuiceboxEncryptedMessage().from_bytes(data)
   

#
# Groups used on regex patterns
#
PATTERN_GROUP_SERIAL = "serial"
PATTERN_GROUP_VERSION = "version"
PATTERN_GROUP_VALUE = "value"
PATTERN_GROUP_TYPE = "type"
PATTERN_GROUP_PAYLOAD = "payload"
PATTERN_GROUP_CHECKSUM = "checksum"
   
# ID:version   
BASE_MESSAGE_PATTERN = r'^(?P<' + PATTERN_GROUP_SERIAL + '>[0-9]+):(?P<' + PATTERN_GROUP_VERSION + '>v[0-9]+[eu])'
BASE_MESSAGE_PATTERN_NO_VERSION = r'^(?P<' + PATTERN_GROUP_SERIAL + '>[0-9]+):'
PAYLOAD_CHECKSUM_PATTERN = r'((?P<' + PATTERN_GROUP_PAYLOAD + '>[^!]*)(!(?P<' + PATTERN_GROUP_CHECKSUM + r'>[A-Z0-9]{3}))?(?:\$|:))'

# For version there is an ending 'u' for this unencrypted messages, the 'e' encrypted messages are not supported here
# all other values are numeric
# Serial appear only on messages that came from juicebox device 
PAYLOAD_PARTS_PATTERN = r'((?P<' + FIELD_SERIAL + '>[0-9]+):)?[,]?(?P<' + PATTERN_GROUP_TYPE + '>[A-Za-z]+)(?P<' + PATTERN_GROUP_VALUE + '>[-]?[0-9]+[u]?)'

   
def is_encrypted_version(version : str):
   #   https://github.com/snicker/juicepassproxy/issues/73
   return version == 'v09e'
   
def juicebox_message_from_string(string : str):
   if string[0:3] == "CMD":
      return JuiceboxCommand().from_string(string)

   msg = re.search(BASE_MESSAGE_PATTERN, string)
      
   if msg:
      if is_encrypted_version(msg.group(PATTERN_GROUP_VERSION)):
         return JuiceboxEncryptedMessage(str.encode(string))

      return JuiceboxMessage().from_string(string)

   msg = re.search(BASE_MESSAGE_PATTERN_NO_VERSION, string)
   if msg:
      return JuiceboxMessage(False).from_string(string)
      
   raise JuiceboxInvalidMessageFormat(f"Unable to parse message: '{string}'")
      
      
      
class JuiceboxMessage:

    def __init__(self, has_checksum=True, defs=FROM_JUICEBOX_FIELD_DEFS) -> None:
        self.has_checksum = has_checksum
        self.payload_str = None
        self.checksum_str = None
        self.values = None
        self.end_char = ':'
        self.defs = defs        
        self.aliases = {}
        # to make easier to use get_values
        for k in self.defs:
           self.aliases[self.defs[k]["alias"]] = k

        pass


    def parse_values(self):
        # Nothing to do here now
        _LOGGER.debug(f"No values conversion on base JuiceboxMessage : {self.values}")

    def store_value(self, values, type, value):
        if not type in values:
            values[type] = value
        else:
            #TODO think better option after understanding of this case whe same type repeats in message
            ok = False
            for idx in range(1,2):
               if not (type + ":" + str(idx)) in values:
                  values[type + ":" + str(idx)] = value
                  ok = True
                  break
            if not ok:
                _LOGGER.error(f"Unable to store duplicate type {type}={value} other_values={values}")
        
    def from_string(self, string: str) -> 'Message':
        _LOGGER.info(f"from_string {string}")
        msg = re.search(PAYLOAD_CHECKSUM_PATTERN, string)

        if msg is None:
            raise JuiceboxInvalidMessageFormat(f"Unable to parse message: '{string}'")

        self.payload_str = msg.group(PATTERN_GROUP_PAYLOAD)
        self.checksum_str = msg.group(PATTERN_GROUP_CHECKSUM)

        if not self.has_checksum and self.checksum_str:
            raise JuiceboxInvalidMessageFormat(f"Found checksum in message that are supposed to dont have checksum '{string}'")

        if self.has_checksum and not self.checksum_str:
            raise JuiceboxInvalidMessageFormat(f"Checksum not found in message that are supposed to have checksum '{string}'")

        values = {}        
        tmp = self.payload_str
        while len(tmp) > 0:
            data = re.search(PAYLOAD_PARTS_PATTERN, tmp)
            if data:
                if data.group(FIELD_SERIAL):
                   values[FIELD_SERIAL] = data.group(FIELD_SERIAL)
                self.store_value(values, data.group(PATTERN_GROUP_TYPE), data.group(PATTERN_GROUP_VALUE))
                tmp = tmp[len(data.group(0)):]
            else: 
               _LOGGER.error(f"unable to parse value from message {tmp}")
               break

        self.values = values
        self.parse_values()

        return self


    def has_value(self, type):
        if type in self.aliases:
            return self.aliases[type] in self.values
        else:
            return type in self.values
        

    def get_value(self, type):
           
        if self.has_value(type):
           if type in self.aliases:
               return self.values[self.aliases[type]]
           else:
               return self.values[type]
           
        return None
        

    def get_processed_value(self, type):
        if type in self.aliases:
           return self.get_processed_value(self.aliases[type])
           
        if "process" in self.defs[type]:
            return self.defs[type]["process"](self, self.get_value(type))

        return self.get_value(type)
        

    def checksum(self) -> JuiceboxChecksum:
        return JuiceboxChecksum(self.payload_str)


    def checksum_computed(self) -> str:
        if self.has_checksum:
            return self.checksum().base35()
        else:
            return None


    def build_payload(self) -> None:
        if self.payload_str:
            return

        _LOGGER.error("this base class cannot build payload")


    def build(self) -> str:
        self.build_payload()
        if self.has_checksum:
            return f"{(self.payload_str)}!{self.checksum_str}{self.end_char}"
        else:
            return f"{(self.payload_str)}{self.end_char}"


    def inspect(self) -> dict:
        data = {
            "payload_str": self.payload_str,
        }
        if self.has_checksum:
           data.update({
            "checksum_str": self.checksum_str,
            "checksum_computed": self.checksum_computed(),
           })

        # Generic base class does not know specific fields, then put all split values
        if self.values:
            for k in self.values:
               if k in self.defs:
                  data[self.defs[k]["alias"]] = self.values[k]
               else:
                  data[k] = self.values[k]

        return data


    def __str__(self):
        return self.build()



class JuiceboxEncryptedMessage(JuiceboxMessage):

    
    def from_bytes(self, data : bytes):
       # get only serial and version 
       string = data[0:33].decode("utf-8")
       msg = re.search(BASE_MESSAGE_PATTERN, string)
      
       if msg:
           if is_encrypted_version(msg.group(PATTERN_GROUP_VERSION)):
               _LOGGER.warning(f"TODO: encrypted {data}")
               # TODO
               return self
           else:
             raise JuiceboxInvalidMessageFormat(f"Unsupported encrypted message version: '{data}'")
           
       else:
           raise JuiceboxInvalidMessageFormat(f"Unsupported message format: '{data}'")
        

class JuiceboxCommand(JuiceboxMessage):

    def __init__(self, previous=None, new_version=False) -> None:
        super().__init__(defs={})
        self.new_version = new_version
        self.command = 6 # Alternates between C242, C244, C008, C006. Meaning unclear.
        self.end_char = "$"

        # increments by one for every message until 999 then it loops back to 1
        if previous:
            self.counter = previous.counter + 1
            if (self.counter > 999):
               self.counter = 1
            self.offline_amperage = previous.offline_amperage
            self.instant_amperage = previous.instant_amperage 
        else:
            self.counter = 1
            self.offline_amperage = 0
            self.instant_amperage = 0

        self.time = datetime.datetime.today()

    def inspect(self) -> dict:
        data = {
            "command": self.command,
            "offline_amperage": self.offline_amperage,
            "instant_amperage": self.instant_amperage,
            "counter": self.counter,
            "payload_str": self.payload_str,
            "checksum_str": self.checksum_str,
            "checksum_computed": self.checksum_computed(),
        }

        # add any extra received value        
        if self.values:
            data.update(self.values)

        return data

    def build_payload(self) -> None:
        if self.payload_str:
            return

        weekday = self.time.strftime('%w') # 0 = Sunday, 6 = Saturday

        # Original comment :
        #     Instant amperage may need to be represented using 4 digits (e.g. 0040) on newer Juicebox versions.
        # mine wich send data using version 09u works with 4 digits on offline and 3 digit on instant
        #    sizes got from original packet dump when communicating with enel x server
        #
        # https://github.com/snicker/juicepassproxy/issues/39#issuecomment-2002312548
        #   @FalconFour definition of currents
        if self.new_version:
            self.payload_str = f"CMD{weekday}{self.time.strftime('%H%M')}A{self.instant_amperage:04d}M{self.offline_amperage:03d}C{self.command:03d}S{self.counter:03d}"
        else:
            self.payload_str = f"CMD{weekday}{self.time.strftime('%H%M')}A{self.instant_amperage:02d}M{self.offline_amperage:02d}C{self.command:03d}S{self.counter:03d}"
        self.checksum_str = self.checksum_computed()

    def parse_values(self):
        if "CMD" in self.values:
            self.values["DOW"] = self.values["CMD"][0]
            self.values["HHMM"] = self.values["CMD"][1:]
            self.values.pop("CMD")
        if "C" in self.values:
            self.command = int(self.values["C"])
            self.values.pop("C")
        if "A" in self.values:
            self.offline_amperage = int(self.values["A"])
            self.values.pop("A")
        if "M" in self.values:
            self.instant_amperage = int(self.values["M"])
            self.values.pop("M")
        if "S" in self.values:
            self.counter = int(self.values["S"])
            self.values.pop("S")
            
        _LOGGER.info(f"parse_values values {self.values}")
