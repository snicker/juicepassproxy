import unittest
import random

from juicebox_config import JuiceboxConfig
from test_message import FAKE_SERIAL

class TestMessage(unittest.IsolatedAsyncioTestCase):

    def test_basic_config(self):
        """
        Test Config
        """
        config = JuiceboxConfig("/tmp/juicepass-test/")
        self.assertEqual("default", config.get("not_defined", "default"))
        value = random.seed(10000)

        config.update({ "ANY" : value })
        self.assertEqual(value, config.get("ANY", None))
        config.pop("ANY")
        self.assertEqual(None, config.get("ANY", None))

        config.update_value("ANY", value )
        self.assertEqual(value, config.get("ANY", None))
        config.pop("ANY")
        self.assertEqual(None, config.get("ANY", None))

        self.assertTrue(config.is_changed())


        self.assertEqual(None, config.get_device(FAKE_SERIAL, "ANY", None))
        config.update_device_value(FAKE_SERIAL, "ANY", value)
        self.assertEqual(value, config.get_device(FAKE_SERIAL, "ANY", None))

        # TODO more basic tests
        
    async def test_sample_config(self):
        """
        Test Sample Config
        """
        config = JuiceboxConfig("./", filename="test_config.yaml")
        await config.load()

        self.assertEqual(1, config.get("MAX_CURRENT", None))
        self.assertEqual(2, config.get_device("0000", "MAX_CURRENT", None))
        self.assertEqual(1, config.get_device("0001", "MAX_CURRENT", None))

        value = random.seed(10000)
        self.assertEqual(value, config.get("x", value))
        self.assertEqual(value, config.get_device("0000", "x", value))
        self.assertEqual(value, config.get_device("0001", "x", value))

        self.assertFalse(config.is_changed())
        # TODO more tests
        
if __name__ == '__main__':
    unittest.main()
        