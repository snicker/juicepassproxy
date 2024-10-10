import yaml
from pathlib import Path
import logging

from const import (
    CONF_YAML,
)

_LOGGER = logging.getLogger(__name__)

class JuiceboxConfig:

    
    def __init__(self, config_loc, filename=CONF_YAML):
        self.config_loc = Path(config_loc)
        self.config_loc.mkdir(parents=True, exist_ok=True)
        self.config_loc = self.config_loc.joinpath(filename)
        self.config_loc.touch(exist_ok=True)
        _LOGGER.info(f"config_loc: {self.config_loc}")
        self._config = {}
        self._changed = False


    async def load(self):
        config = {}
        try:
            _LOGGER.info(f"Reading config from {self.config_loc}")
            with open(self.config_loc, "r") as file:
               config = yaml.safe_load(file)
        except Exception as e:
            _LOGGER.warning(f"Can't load {self.config_loc}. ({e.__class__.__qualname__}: {e})")
        if not config:
            config = {}
        self._config = config
        
    async def write(self):
        try:
            _LOGGER.info(f"Writing config to {self.config_loc}")
            with open(self.config_loc, "w") as file:
                yaml.dump(self._config, file)
            self._changed = False
            return True
        except Exception as e:
            _LOGGER.warning(
                f"Can't write to {self.config_loc}. ({e.__class__.__qualname__}: {e})"
            )
        return False


    async def write_if_changed(self):
        if self._changed:
            return await self.write()
        return True
        
    def get(self, key, default):
        return self._config.get(key, default)

    # Get device specific configuration, if not found try to use global parameter
    def get_device(self, device, key, default):
        return self._config.get(device +"_" + key, self._config.get(key, default))
                
    def update(self, data):
        # TODO detect changes 
        return self._config.update(data)

    def update_value(self, key, value):
        if self._config.get(key, None) != value:
            self.update({ key : value })
            self._changed = True

    def update_device_value(self, device, key, value):
        self.update_value(device + "_" + key, value)


    def pop(self, key):
       if key in self._config:
           self._config.pop(key, None)
           self._changed = True
           
    def is_changed(self):
       return self._changed
       
              
    
           
       
        
        
    