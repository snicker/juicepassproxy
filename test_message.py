import unittest
from juicebox_message import juicebox_message_from_string, juicebox_message_from_bytes, JuiceboxMessage, JuiceboxDebugMessage, JuiceboxEncryptedMessage, JuiceboxCommand
from juicebox_exceptions import JuiceboxInvalidMessageFormat
import codecs
import datetime


FAKE_SERIAL = "0910000000000000000000000000"

#
# Some messages here are not the real one captured, the serial number of device was changed after doing tests with real values and crc corrected
#
class TestMessage(unittest.TestCase):

    def setUp(self):
        self.maxDiff = None
    
    def do_test_message_building(self, new_version, offline_amperage, instant_amperage, full_command):
        m = JuiceboxCommand(new_version=new_version)
        m.time = datetime.datetime(2012, 3, 23, 23, 24, 55, 173504)
        m.offline_amperage = offline_amperage
        m.instant_amperage = instant_amperage
        self.assertEqual(m.build(), full_command)
    
    def test_message_building(self):
        self.do_test_message_building(False, 0, 0, "CMD52324A00M00C006S001!SHP$")
        self.do_test_message_building(False, 16, 20, "CMD52324A20M16C006S001!5RE$")


    def test_message_building_new(self):
        self.do_test_message_building(True, 0, 0, "CMD52324A0000M000C006S001!ETK$")
        self.do_test_message_building(True, 16, 20, "CMD52324A0020M016C006S001!YUK$")


    def test_entrypted_message(self):
        messages = [
            # https://github.com/snicker/juicepassproxy/issues/73#issuecomment-2149670058
            "303931303034323030313238303636303432373332333632303533353a7630396512b10a000000716b1493270404a809cbcbb7995fd86b391e4b5e606fd5153a81ecd6251eb2bf87da82db9ceaefb268caa8f0c01b538af48e45d1ef3ad28ca72a4fdf05261780fd753b361906368634821bf6cada5624bae11feb7dc975cfe14e2c305eb01adcc7b39687ddc130d66cc39bc2ccac7f903cb9b50adb9a77b95b77bd364b82dcbe8599dc9a8a880cc44eb0f04e8a1d9f4a6305978a7f3e3c58d5"
            "303931303034323030313238303636303432373332333632303533353a7630396512b10a00000073480d38833df8ebed8add322332c5c9f0501b32e9b35b71d1d8d3e389f5b9002b42ee953b5d9f712ddd36ebcb9f0a8973eba739f388583429d3fcd4cd135f9e4d437ad6ad21c11ad8e89369252ada194b52436beeb67a15b4a24f85eae07ebeeb6270588c94e390fa6da00c831e290a8552bd49ce014db1aa70843ebb5db2b0dea0fa20d0ed00714ae3001c895bf54779d5d1449ee15bf486"
            # TODO try to find a message that maybe can be decoded as string if possible
        ]
        for message in messages:
            print("enc")
            m = juicebox_message_from_bytes(codecs.decode(message,'hex'))
            self.assertEqual(JuiceboxEncryptedMessage, type(m))
    
    def test_message_validation(self):
        messages = [
            "g4rbl3d",
        ]
        for message in messages:
            with self.assertRaises(JuiceboxInvalidMessageFormat):
                print(f"bad : {message}")
                juicebox_message_from_string(message)


    def test_command_message_parsing(self):
        """
        Command messages are typically sent by the Cloud to the Juicebox
        """
        raw_msg = "CMD41325A0040M040C006S638!5N5$"
        m = juicebox_message_from_string(raw_msg)
        self.assertEqual(m.payload_str, "CMD41325A0040M040C006S638")
        self.assertEqual(m.crc_str, "5N5")
        self.assertEqual(m.crc_str, m.crc_computed())
        self.assertEqual(m.build(), raw_msg)

        self.assertEqual(m.get_value("DOW"), "4")
        self.assertEqual(m.get_value("HHMM"), "1325")



    def test_status_message_parsing(self):
        """
        Status messages are sent by the Juicebox
        """
        raw_msg = "0910000000000000000000000000:v09u,s627,F10,u01254993,V2414,L00004555804,S01,T08,M0040,C0040,m0040,t29,i75,e00000,f5999,r61,b000,B0000000!S1H:"

        m = juicebox_message_from_string(raw_msg)
        self.assertEqual(m.payload_str, "0910000000000000000000000000:v09u,s627,F10,u01254993,V2414,L00004555804,S01,T08,M0040,C0040,m0040,t29,i75,e00000,f5999,r61,b000,B0000000")
        self.assertEqual(m.crc_str, "S1H")
        self.assertEqual(m.crc_str, m.crc_computed())
        self.assertEqual(True, m.has_value("C"))
        self.assertEqual(m.get_value("C"), "0040")
        self.assertEqual(m.get_value("v"), "09u")
        self.assertEqual(m.get_value("V"), "2414")
        self.assertEqual(m.get_value("voltage"), "2414")
        self.assertEqual(m.get_processed_value("status"), "Plugged In")
        self.assertEqual(m.get_processed_value("voltage"), 241.4)
        self.assertEqual(m.get_value("temperature"), "08")
        self.assertEqual(m.get_processed_value("temperature"), 46.4)
        self.assertEqual(m.get_value("serial"), "0910000000000000000000000000")
        self.assertEqual(True, m.has_value("L"))
        self.assertEqual(True, m.has_value("M"))
        self.assertEqual(m.build(), raw_msg)

    # https://github.com/snicker/juicepassproxy/issues/80
    OLD_MESSAGE = '0910000000000000000000000000:V247,L11097,S0,T34,E14,i84,e1,t30:'
    OLD_MESSAGE_2 = '0910000000000000000000000000:V247,L11156,E13322,A138,T28,t10,E14,i41,e1:'
    OLD_CHARGING = '0910000000000000000000000000:V247,L11097,E60,A137,T20,t10,E14,i94,e2:'
    OLD_PLUGGED_IN = '0910000000000000000000000000:V247,L11097,E67,A0,T20,t10,E14,i49,e1:'


    def test_old_message(self):
        """
        Test old  message
        """

        m = juicebox_message_from_string(self.OLD_MESSAGE)
        self.assertEqual(m.payload_str, self.OLD_MESSAGE[:-1])
        self.assertEqual(m.crc_str, None)
        self.assertEqual(m.get_value("serial"), FAKE_SERIAL)
        self.assertEqual(m.get_processed_value("status"), "Unplugged")
        self.assertEqual(m.get_processed_value("voltage"), 247)
        self.assertEqual(m.get_value("temperature"), "34")
        self.assertEqual(m.get_processed_value("temperature"), 93.2)
        # TODO complete other tests with this kind of assert 
        self.assertDictEqual(m.to_simple_format(), { "type" : "basic", "current" : 0, "serial" : FAKE_SERIAL, "status" : "Unplugged", "voltage": 247.0, 
            "temperature" : 93.2, "energy_lifetime": 11097,  "energy_session": 14, "interval": 84,  "report_time": "30", "e" : "1",
            "power" : 0})

    def test_old_message_2(self):
        """
        Test old  message
        """

        m = juicebox_message_from_string(self.OLD_MESSAGE_2)
        self.assertEqual(m.payload_str, self.OLD_MESSAGE_2[:-1])
        self.assertEqual(m.crc_str, None)
        self.assertEqual(m.get_value("serial"), FAKE_SERIAL)
        self.assertEqual(m.get_processed_value("status"), "Charging")
        self.assertEqual(m.get_value("temperature"), "28")
        self.assertEqual(m.get_processed_value("temperature"), 82.4)
        # the duplicate value is saved but what they mean ???
        self.assertEqual(m.get_value("E"), "13322")
        self.assertEqual(m.get_value("E:1"), "14")
        self.assertEqual(m.get_value("A"), "138")

    def test_old_charging(self):
        """
        Test old charging message
        """

        m = juicebox_message_from_string(self.OLD_CHARGING)
        self.assertEqual(m.payload_str, self.OLD_CHARGING[:-1])
        self.assertEqual(m.crc_str, None)
        self.assertEqual(m.get_value("serial"), FAKE_SERIAL)
        self.assertEqual(m.get_processed_value("status"), "Charging")
        self.assertEqual(m.get_processed_value("voltage"), 247)
        self.assertEqual(m.get_value("temperature"), "20")
        self.assertEqual(m.get_processed_value("temperature"), 68.0)
        # the duplicate value is saved but what they mean ???
        self.assertEqual(m.get_value("E"), "60")
        self.assertEqual(m.get_value("E:1"), "14")

    def test_old_pluggedin(self):
        """
        Test old PluggedIn message
        """

        m = juicebox_message_from_string(self.OLD_PLUGGED_IN)
        self.assertEqual(m.payload_str, self.OLD_PLUGGED_IN[:-1])
        self.assertEqual(m.crc_str, None)
        self.assertEqual(m.get_value("serial"), FAKE_SERIAL)
        self.assertEqual(m.get_processed_value("status"), "Plugged In")
        self.assertEqual(m.get_processed_value("voltage"), 247)
        self.assertEqual(m.get_value("temperature"), "20")
        self.assertEqual(m.get_processed_value("temperature"), 68.0)
        # the duplicate value is saved but what they mean ???
        self.assertEqual(m.get_value("E"), "67")
        self.assertEqual(m.get_value("E:1"), "14")


    # Original messages changed to remove real serial number
    V09U_SAMPLE =  '0910000000000000000000000000:v09u,s001,F31,u00412974,V1366,L00004262804,S02,T28,M0024,C0024,m0032,t09,i23,e-0001,f5990,r99,b000,B0000000,P0,E0004501,A00161,p0996!ZW5:';
    # from https://github.com/snicker/juicepassproxy/issues/90
    V07_SAMPLE  =  '0910000000000000000000000000:v07,s0001,u30048,V2400,L0024880114,S2,T62,M40,m40,t09,i78,e-001,f6001,X0,Y0,E006804,A0394,p0992!KKD:';
    # from discord channel
    V07_SAMPLE_2 = '0910000000000000000000000000:v07,s0177,u16708,V2422,L0024957914,S2,T61,M40,m40,t09,i51,e-001,f6001,X0,Y0,E019146,A0393,p0992!QBJ:'

    def test_v09(self):
        """
        Test v09 sample message
        """

        m = juicebox_message_from_string(self.V09U_SAMPLE)
        chkidx = self.V09U_SAMPLE.index('!')
        self.assertEqual(m.payload_str, self.V09U_SAMPLE[:chkidx])
        self.assertEqual(m.crc_str, self.V09U_SAMPLE[(chkidx+1):(chkidx+4)])
        self.assertEqual(m.get_processed_value("status"), "Charging")
        self.assertEqual(m.get_processed_value("voltage"), 136.6)
        self.assertEqual(m.get_processed_value("current_rating"), 32)
        self.assertEqual(m.get_processed_value("current_max_online"), 24)
        self.assertEqual(m.get_processed_value("current_max_offline"), 24)
        self.assertEqual(m.get_processed_value("energy_session"), 4501)
        self.assertEqual(m.get_processed_value("energy_lifetime"), 4262804)
        self.assertEqual(m.get_processed_value("interval"), 23)
        self.assertEqual(m.get_value("temperature"), "28")
        self.assertEqual(m.get_processed_value("temperature"), 82.4)

    def test_v07(self):
        """
        Test v07 sample message
        """

        m = juicebox_message_from_string(self.V07_SAMPLE)
        chkidx = self.V07_SAMPLE.index('!')
        self.assertEqual(m.payload_str, self.V07_SAMPLE[:chkidx])
        self.assertEqual(m.crc_str, self.V07_SAMPLE[(chkidx+1):(chkidx+4)])
        self.assertEqual(m.get_processed_value("status"), "Charging")
        self.assertEqual(m.get_processed_value("voltage"), 240.0)
        self.assertEqual(m.get_processed_value("frequency"), 60.01)
        self.assertEqual(m.get_processed_value("current"), 39.4)
        self.assertEqual(m.get_processed_value("current_rating"), 40)
        self.assertEqual(m.get_processed_value("current_max_online"), 40)
        # The process will return value for this parameter that are not comming on the message
        self.assertEqual(m.get_processed_value("current_max_offline"), None)
        self.assertEqual(m.get_processed_value("energy_session"), 6804)
        self.assertEqual(m.get_processed_value("energy_lifetime"), 24880114)
        self.assertEqual(m.get_processed_value("interval"), 78)
        self.assertEqual(m.get_value("temperature"), "62")
        self.assertEqual(m.get_processed_value("temperature"), 143.6)
        self.assertDictEqual(m.to_simple_format(), { "type" : "basic", "current" : 39.4, "serial" : FAKE_SERIAL, "status" : "Charging", "voltage": 240.0, 
            "temperature" : 143.6, "energy_lifetime": 24880114,  "energy_session": 6804, "interval": 78, 
            "report_time": "09", "e" : "-001", "frequency" : 60.01, "loop_counter": "30048", 
            "protocol_version" : "07", "p" : "0992", "current_max_online": 40, "current_rating": 40, 
            "power" : 9456,
            "X" : "0", "Y" : "0", "counter" : "0001" })

    def test_v07_2(self):
        """
        Test v07_2 sample message
        """

        m = juicebox_message_from_string(self.V07_SAMPLE_2)
        chkidx = self.V07_SAMPLE_2.index('!')
        self.assertEqual(m.payload_str, self.V07_SAMPLE_2[:chkidx])
        self.assertEqual(m.crc_str, self.V07_SAMPLE_2[(chkidx+1):(chkidx+4)])
        self.assertEqual(m.get_processed_value("status"), "Charging")
        self.assertEqual(m.get_processed_value("voltage"), 242.2)
        self.assertEqual(m.get_processed_value("frequency"), 60.01)
        self.assertEqual(m.get_processed_value("current"), 39.3)
        self.assertEqual(m.get_processed_value("current_rating"), 40)
        self.assertEqual(m.get_processed_value("current_max_online"), 40)
        # The process will return value for this parameter that are not comming on the message
        self.assertEqual(m.get_processed_value("current_max_offline"), None)
        self.assertEqual(m.get_processed_value("energy_session"), 19146)
        self.assertEqual(m.get_processed_value("energy_lifetime"), 24957914)
        self.assertEqual(m.get_processed_value("interval"), 51)
        self.assertEqual(m.get_value("temperature"), "61")
        self.assertEqual(m.get_processed_value("temperature"), 141.8)
        self.assertDictEqual(m.to_simple_format(), { "type" : "basic", "current" : 39.3, "serial" : FAKE_SERIAL, "status" : "Charging", "voltage": 242.2, 
            "temperature" : 141.8, "energy_lifetime": 24957914,  "energy_session": 19146, "interval": 51,  
            "report_time": "09", "e" : "-001", "frequency" : 60.01, "loop_counter": "16708", 
            "protocol_version" : "07", "p" : "0992", "current_max_online": 40, "current_rating": 40, 
            "power" : 9518,
            "X" : "0", "Y" : "0", "counter" : "0177" })


    DEBUG_BOT_VERSION = "0000000000000000000000000000:DBG,NFO:BOT:EMWERK-JB_1_1-1.4.0.28, 2021-04-27T20:39:50Z, ZentriOS-WZ-3.6.4.0:"

    def test_debug_BOT_VERSION(self):
        m = juicebox_message_from_string(self.DEBUG_BOT_VERSION)
        self.assertTrue(isinstance(m, JuiceboxDebugMessage))
        self.assertEqual(m.get_value("debug_message"),"INFO: BOT:EMWERK-JB_1_1-1.4.0.28, 2021-04-27T20:39:50Z, ZentriOS-WZ-3.6.4.0")
        self.assertTrue(m.is_boot())

            
    def test_message_crcs(self):
        cmd_messages = [
            'CMD41325A0040M040C006S638!5N5$', # @MrDrew514 (v09u)
            'CMD62210A20M18C006S006!31Y$',
            'CMD62228A20M15C008S048!IR4$',
            'CMD62207A20M20C244S997!R5Y$',
            'CMD62207A20M20C008S996!ZI4$',
            'CMD62201A20M20C244S981!ECD$',
            'CMD62201A20M20C006S982!QT8$',
            'CMD31353A0000M010C244S741!2B3$', # (v09u)
            # https://github.com/snicker/juicepassproxy/issues/90
            'CMD41301A40M40C006S074!F0P$',
            'CMD41301A29M40C242S075!TJ5$',
            'CMD41301A40M40C008S076!YCA$',
            'CMD41301A40M40C244S077!B72$',
            'CMD41301A40M40C006S078!J0P$',
            'CMD41301A40M40C242S079!RQ7$',
            'CMD41302A40M40C008S080!S9E$',
            'CMD41302A40M40C244S081!T2P$',
            'CMD41302A40M40C006S082!KQL$'
        ]
        
        crc_messages = [
            self.V09U_SAMPLE,
            self.V07_SAMPLE,
            self.V07_SAMPLE_2,
        ]
        
        debug_messages = [
            self.DEBUG_BOT_VERSION,
            "0000000000000000000000000000:DBG,NFO:BOT:FW Init.ENC.Y/ECDAYS.90/EVT.Y/ECHTTP.Y:",
            "0000000000000000000000000000:DBG,NFO:BOT:UUID 0000000000000000000000000000000000000000:",
            "0000000000000000000000000000:DBG,NFO:BOT:BT:BootLoader(0), OTA(3), crc(ffffffff):",
            "0000000000000000000000000000:DBG,ERR:Miss CRC 'CMD01216A27M30C006S23':",
            "0000000000000000000000000000:DBG,WRN:Events_03_04e22Z-01-01 Open Err 7034:",
            "0000000000000000000000000000:DBG,NFO:ELife [-1,-1,5340542], 2, w 5340542, r 5340542,5340543:",
        ]
        
        old_messages = [
            self.OLD_MESSAGE,
            self.OLD_MESSAGE_2,
            self.OLD_PLUGGED_IN,
            self.OLD_CHARGING
        ]

        for message in (cmd_messages + crc_messages + old_messages + debug_messages):
            m = juicebox_message_from_string(message)

            self.assertEqual(m.build(), message)
            self.assertEqual(m.crc_str, m.crc_computed())
#            print(m.inspect())


        for message in crc_messages:
            # expect for error when trying to parse a crc message ignoring crc
            with self.assertRaises(JuiceboxInvalidMessageFormat):
                m = JuiceboxMessage(False).from_string(message)

        for message in old_messages:
            # expect for error when trying to parse old message without checking considering crc
            with self.assertRaises(JuiceboxInvalidMessageFormat):
                m = JuiceboxMessage().from_string(message)

if __name__ == '__main__':
    unittest.main()
