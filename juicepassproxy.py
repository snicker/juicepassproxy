#!/usr/bin/env python3

import argparse
import asyncio
import ipaddress
import logging
import socket
import sys
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import dns
from aiorun import run
from const import (
    DAYS_TO_KEEP_LOGS,
    DEFAULT_DEVICE_NAME,
    DEFAULT_ENELX_IP,
    DEFAULT_ENELX_PORT,
    DEFAULT_ENELX_SERVER,
    DEFAULT_LOCAL_IP,
    DEFAULT_LOGLEVEL,
    DEFAULT_MQTT_DISCOVERY_PREFIX,
    DEFAULT_MQTT_HOST,
    DEFAULT_MQTT_PORT,
    DEFAULT_TELNET_PORT,
    DEFAULT_TELNET_TIMEOUT,
    EXTERNAL_DNS,
    LOG_DATE_FORMAT,
    LOG_FORMAT,
    LOGFILE,
    MAX_JPP_LOOP,
    VERSION,
)
from ha_mqtt_discoverable import Settings
from juicebox_mitm import JuiceboxMITM
from juicebox_mqtthandler import JuiceboxMQTTHandler
from juicebox_telnet import JuiceboxTelnet
from juicebox_udpcupdater import JuiceboxUDPCUpdater
from juicebox_config import JuiceboxConfig

logging.basicConfig(
    format=LOG_FORMAT,
    datefmt=LOG_DATE_FORMAT,
    level=DEFAULT_LOGLEVEL,
    handlers=[
        logging.StreamHandler(),
    ],
)
_LOGGER = logging.getLogger(__name__)


AP_DESCRIPTION = """
JuicePass Proxy - by snicker
Publish JuiceBox data from a UDP Man in the Middle Proxy to MQTT discoverable by HomeAssistant.

https://github.com/snicker/juicepassproxy

To get the destination IP:Port of the EnelX server, telnet to your Juicenet device:

$ telnet 192.168.x.x 2000 and type the list command: list

! # Type  Info
# 0 FILE  webapp/index.html-1.4.0.24 (1995, 0)
# 1 UDPC  juicenet-udp-prod3-usa.enelx.com:8047 (26674)

The address is in the UDPC line.
Run ping, nslookup, or similar command to determine the IP.

As of November, 2023: juicenet-udp-prod3-usa.enelx.com = 54.161.185.130.
"""


async def get_local_ip():
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    try:
        transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol,
            remote_addr=("10.254.254.254", 80),
            family=socket.AF_INET,
        )
        local_ip = transport.get_extra_info("sockname")[0]
    except Exception as e:
        _LOGGER.warning(f"Unable to get Local IP. ({e.__class__.__qualname__}: {e})")
        local_ip = None
    finally:
        transport.close()
    return local_ip


async def resolve_ip_external_dns(address, use_dns=EXTERNAL_DNS):
    # res = await dns.asyncresolver.Resolver()
    res = dns.resolver.Resolver()
    res.nameservers = [use_dns]
    try:
        # answers = await res.resolve(
        answers = res.resolve(address, rdtype=dns.rdatatype.A, raise_on_no_answer=True)
    except (
        dns.resolver.LifetimeTimeout,
        dns.resolver.NoNameservers,
        dns.resolver.NoAnswer,
    ) as e:
        _LOGGER.warning(
            f"Unable to resolve {address}. ({e.__class__.__qualname__}: {e})"
        )
        return None

    if len(answers) > 0:
        return answers[0].address
    return None


async def is_valid_ip(test_ip):
    try:
        ipaddress.ip_address(test_ip)
    except ValueError:
        return False
    return True


async def get_enelx_server_port(juicebox_host, telnet_port, telnet_timeout=None):
    try:
        async with JuiceboxTelnet(
            juicebox_host,
            telnet_port,
            loglevel=_LOGGER.getEffectiveLevel(),
            timeout=telnet_timeout,
        ) as tn:
            connections = await tn.get_udpc_list()
            # _LOGGER.debug(f"connections: {connections}")
            for connection in connections:
                if connection["type"] == "UDPC" and not await is_valid_ip(
                    connection["dest"].split(":")[0]
                ):
                    return connection["dest"]
    except TimeoutError as e:
        _LOGGER.warning(
            "Error in getting EnelX Server and Port via Telnet. "
            f"({e.__class__.__qualname__}: {e})"
        )
        return None
    except ConnectionResetError as e:
        _LOGGER.warning(
            "Error in getting EnelX Server and Port via Telnet. "
            f"({e.__class__.__qualname__}: {e})"
        )
        return None
    return None


async def get_juicebox_id(juicebox_host, telnet_port, telnet_timeout=None):
    try:
        async with JuiceboxTelnet(
            juicebox_host,
            telnet_port,
            loglevel=_LOGGER.getEffectiveLevel(),
            timeout=telnet_timeout,
        ) as tn:
            juicebox_id = (await tn.get_variable("email.name_address")).decode("utf-8")
            return juicebox_id
    except TimeoutError as e:
        _LOGGER.warning(
            "Error in getting JuiceBox ID via Telnet. "
            f"({e.__class__.__qualname__}: {e})"
        )
        return None
    except ConnectionResetError as e:
        _LOGGER.warning(
            "Error in getting JuiceBox ID via Telnet. "
            f"({e.__class__.__qualname__}: {e})"
        )
        return None
    return None




def ip_to_tuple(ip):
    if isinstance(ip, tuple):
        return ip
    ip, port = ip.split(":")
    return (ip, int(port))


async def parse_args():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=AP_DESCRIPTION,
    )

    parser.add_argument(
        "--juicebox_host",
        type=str,
        metavar="HOST",
        help="Host or IP address of the JuiceBox. Required for --update_udpc or if --enelx_ip not defined.",
    )
    parser.add_argument(
        "--update_udpc",
        action="store_true",
        help="Update UDPC on the JuiceBox. Requires --juicebox_host",
    )
    parser.add_argument(
        "--jpp_host",
        "--juicepass_proxy_host",
        dest="jpp_host",
        type=str,
        metavar="HOST",
        help="EXTERNAL host or IP address of the machine running JuicePass "
        "Proxy. Optional: only necessary when using --update_udpc and "
        "it will be inferred from the address in --local_ip if omitted.",
    )
    parser.add_argument(
        "-H",
        "--mqtt_host",
        type=str,
        metavar="HOST",
        default=DEFAULT_MQTT_HOST,
        help="MQTT Hostname to connect to (default: %(default)s)",
    )
    parser.add_argument(
        "-p",
        "--mqtt_port",
        type=int,
        metavar="PORT",
        default=DEFAULT_MQTT_PORT,
        help="MQTT Port (default: %(default)s)",
    )
    parser.add_argument(
        "-u", "--mqtt_user", type=str, help="MQTT Username", metavar="USER"
    )
    parser.add_argument(
        "-P", "--mqtt_password", type=str, help="MQTT Password", metavar="PASSWORD"
    )
    parser.add_argument(
        "-D",
        "--mqtt_discovery_prefix",
        type=str,
        metavar="PREFIX",
        dest="mqtt_discovery_prefix",
        default=DEFAULT_MQTT_DISCOVERY_PREFIX,
        help="Home Assistant MQTT topic prefix (default: %(default)s)",
    )
    parser.add_argument(
        "--config_loc",
        type=str,
        metavar="LOC",
        default=Path.home().joinpath(".juicepassproxy"),
        help="The location to store the config file (default: %(default)s)",
    )
    parser.add_argument(
        "--log_loc",
        type=str,
        metavar="LOC",
        default=Path.home(),
        help="The location to store the log files (default: %(default)s)",
    )
    parser.add_argument(
        "--name",
        type=str,
        default=DEFAULT_DEVICE_NAME,
        help="Home Assistant Device Name (default: %(default)s)",
        dest="device_name",
    )
    parser.add_argument(
        "--debug", action="store_true", help="Show Debug level logging. (default: Info)"
    )
    parser.add_argument(
        "--experimental",
        action="store_true",
        help="Enables additional entities in Home Assistant that are in in development or can be used toward developing the ability to send commands to a JuiceBox.",
    )
    parser.add_argument(
        "--ignore_enelx",
        action="store_true",
        help="If set, will not send commands received from EnelX to the JuiceBox nor send outgoing information from the JuiceBox to EnelX",
    )
    parser.add_argument(
        "--tp",
        "--telnet_port",
        dest="telnet_port",
        required=False,
        type=int,
        metavar="PORT",
        default=DEFAULT_TELNET_PORT,
        help="Telnet PORT (default: %(default)s)",
    )
    parser.add_argument(
        "--telnet_timeout",
        type=int,
        metavar="SECONDS",
        default=DEFAULT_TELNET_TIMEOUT,
        help="Timeout in seconds for Telnet operations (default: %(default)s)",
    )
    parser.add_argument(
        "--juicebox_id",
        type=str,
        metavar="ID",
        help="JuiceBox ID. If not defined, will obtain it automatically.",
        dest="juicebox_id",
    )
    parser.add_argument(
        "--local_ip",
        "-s",
        "--src",
        dest="local_ip",
        required=False,
        type=str,
        metavar="IP",
        help="Local IP (and optional port). If not defined, will obtain it automatically. (Ex. 127.0.0.1:8047) [Deprecated: -s --src]",
    )
    parser.add_argument(
        "--local_port",
        dest="local_port",
        required=False,
        type=int,
        metavar="PORT",
        help="Local Port for JPP to listen on.",
    )
    parser.add_argument(
        "--enelx_ip",
        "-d",
        "--dst",
        dest="enelx_ip",
        required=False,
        type=str,
        metavar="IP",
        help="Destination IP (and optional port) of EnelX Server. If not defined, --juicebox_host required and then will obtain it automatically. (Ex. 54.161.185.130:8047) [Deprecated: -d --dst]",
    )

    return parser.parse_args()


async def main():
    args = await parse_args()
    log_loc = Path(args.log_loc)
    log_loc.mkdir(parents=True, exist_ok=True)
    log_loc = log_loc.joinpath(LOGFILE)
    log_loc.touch(exist_ok=True)
    logging.basicConfig(
        format=LOG_FORMAT,
        datefmt=LOG_DATE_FORMAT,
        level=DEFAULT_LOGLEVEL,
        handlers=[
            logging.StreamHandler(),
            TimedRotatingFileHandler(
                log_loc, when="midnight", backupCount=DAYS_TO_KEEP_LOGS
            ),
        ],
        force=True,
    )
    if args.debug:
        _LOGGER.setLevel(logging.DEBUG)
    _LOGGER.warning(
        f"Starting JuicePass Proxy {VERSION} "
        f"(Log Level: {logging.getLevelName(_LOGGER.getEffectiveLevel())})"
    )
    _LOGGER.info(f"log_loc: {log_loc}")
    if len(sys.argv) == 1:
        _LOGGER.error(
            "Exiting: no command-line arguments given. Run with --help to see options."
        )
        sys.exit(1)

    if len(sys.argv) > 1 and args.update_udpc and not args.juicebox_host:
        _LOGGER.error(
            "Exiting: --update_udpc is set, thus --juicebox_host is required.",
        )
        sys.exit(1)

    if len(sys.argv) > 1 and not args.enelx_ip and not args.juicebox_host:
        _LOGGER.error(
            "Exiting: --enelx_ip is not set, thus --juicebox_host is required.",
        )
        sys.exit(1)

    config = JuiceboxConfig(args.config_loc)
    await config.load()

    telnet_port = int(args.telnet_port)
    _LOGGER.info(f"telnet port: {telnet_port}")
    if telnet_port == 0:
        telnet_port = 2000

    telnet_timeout = int(args.telnet_timeout)
    _LOGGER.info(f"telnet timeout: {telnet_timeout}")
    if telnet_timeout == 0:
        telnet_timeout = None

    ignore_enelx = args.ignore_enelx
    _LOGGER.info(f"ignore_enelx: {ignore_enelx}")

    enelx_server_port = None
    if not ignore_enelx:
        enelx_server_port = await get_enelx_server_port(
            args.juicebox_host, args.telnet_port, telnet_timeout=telnet_timeout
        )

    if enelx_server_port:
        _LOGGER.debug(f"enelx_server_port: {enelx_server_port}")
        enelx_server = enelx_server_port.split(":")[0]
        enelx_port = enelx_server_port.split(":")[1]
    else:
        enelx_server = config.get("ENELX_SERVER", DEFAULT_ENELX_SERVER)
        enelx_port = config.get("ENELX_PORT", DEFAULT_ENELX_PORT)
    config.update_value("ENELX_SERVER", enelx_server)
    config.update_value("ENELX_PORT", enelx_port)
    _LOGGER.info(f"enelx_server: {enelx_server}")
    _LOGGER.info(f"enelx_port: {enelx_port}")

    if (
        args.local_port
        and args.local_ip
        and ":" in args.local_ip
        and int(args.local_ip.split(":")[1]) != args.local_port
    ):
        _LOGGER.error(
            "Exiting: Local port conflict: --local_ip with port "
            f"{args.local_ip.split(':')[1]} and --local_port of {args.local_port}"
        )
        sys.exit(1)

    if args.local_port:
        local_port = args.local_port
    else:
        local_port = enelx_port
    if args.local_ip:
        if ":" in args.local_ip:
            local_addr = ip_to_tuple(args.local_ip)
        else:
            local_addr = ip_to_tuple(f"{args.local_ip}:{local_port}")
    elif local_ip := await get_local_ip():
        local_addr = ip_to_tuple(f"{local_ip}:{local_port}")
    else:
        local_addr = ip_to_tuple(
            f"{config.get('LOCAL_IP', config.get('SRC', DEFAULT_LOCAL_IP))}:"
            f"{local_port}"
        )
    config.update_value("LOCAL_IP", local_addr[0])
    _LOGGER.info(f"local_addr: {local_addr[0]}:{local_addr[1]}")

    localhost_check = (
        local_addr[0].startswith("0.")
        or local_addr[0].startswith("127")
        or "localhost" in local_addr[0]
    )
    if args.update_udpc and localhost_check and not args.jpp_host:
        _LOGGER.error(
            "Exiting: when --update_udpc is set, --local_ip must not be a localhost address (ex. 127.0.0.1) or "
            "--jpp_host must also be set.",
        )
        sys.exit(1)

    if args.enelx_ip:
        if ":" in args.enelx_ip:
            enelx_addr = ip_to_tuple(args.enelx_ip)
        else:
            enelx_addr = ip_to_tuple(f"{args.enelx_ip}:{enelx_port}")
    elif enelx_server_ip := await resolve_ip_external_dns(enelx_server):
        enelx_addr = ip_to_tuple(f"{enelx_server_ip}:{enelx_port}")
    else:
        enelx_addr = ip_to_tuple(
            f"{config.get('ENELX_IP', config.get('DST', DEFAULT_ENELX_IP))}:"
            f"{enelx_port}"
        )
    config.update_value("ENELX_IP", enelx_addr[0])
    _LOGGER.info(f"enelx_addr: {enelx_addr[0]}:{enelx_addr[1]}")
    _LOGGER.info(f"telnet_addr: {args.juicebox_host}:{args.telnet_port}")

    if juicebox_id := args.juicebox_id:
        pass
    elif juicebox_id := await get_juicebox_id(
        args.juicebox_host, args.telnet_port, telnet_timeout=telnet_timeout
    ):
        pass
    else:
        juicebox_id = config.get("JUICEBOX_ID")
    if juicebox_id:
        config.update_value("JUICEBOX_ID", juicebox_id)
        _LOGGER.info(f"juicebox_id: {juicebox_id}")
    else:
        _LOGGER.error(
            "Cannot get JuiceBox ID from Telnet and not in Config. If a JuiceBox ID is later set or is obtained via Telnet, it will likely create a new JuiceBox Device with new Entities in Home Assistant."
        )

    experimental = args.experimental
    _LOGGER.info(f"experimental: {experimental}")

    # Remove DST and SRC from Config as they have been replaced by ENELX_IP and LOCAL_IP respectively
    config.pop("DST")
    config.pop("SRC")

    await config.write_if_changed()

    mqtt_settings = Settings.MQTT(
        host=args.mqtt_host,
        port=args.mqtt_port,
        username=args.mqtt_user,
        password=args.mqtt_password,
        discovery_prefix=args.mqtt_discovery_prefix,
    )

    jpp_loop_count = 1
    while jpp_loop_count <= MAX_JPP_LOOP:
        if jpp_loop_count != 1:
            _LOGGER.error(f"Restarting JuicePass Proxy Loop ({jpp_loop_count})")
        jpp_loop_count += 1
        jpp_task_list = []
        udpc_updater = None
        mqtt_handler = JuiceboxMQTTHandler(
            mqtt_settings=mqtt_settings,
            device_name=args.device_name,
            juicebox_id=juicebox_id,
            config=config,
            experimental=experimental,
            loglevel=_LOGGER.getEffectiveLevel(),
        )
        jpp_task_list.append(
            asyncio.create_task(mqtt_handler.start(), name="mqtt_handler")
        )

        mitm_handler = JuiceboxMITM(
            jpp_addr=local_addr,  # Local/Docker IP
            enelx_addr=enelx_addr,  # EnelX IP
            ignore_enelx=ignore_enelx,
            loglevel=_LOGGER.getEffectiveLevel(),
        )
        await mitm_handler.set_local_mitm_handler(mqtt_handler.local_mitm_handler)
        await mitm_handler.set_remote_mitm_handler(mqtt_handler.remote_mitm_handler)
        jpp_task_list.append(
            asyncio.create_task(mitm_handler.start(), name="mitm_handler")
        )

        await mqtt_handler.set_mitm_handler(mitm_handler)
        await mitm_handler.set_mqtt_handler(mqtt_handler)

        if args.update_udpc:
            jpp_host = args.jpp_host or local_addr[0]
            udpc_updater = JuiceboxUDPCUpdater(
                juicebox_host=args.juicebox_host,
                jpp_host=jpp_host,
                telnet_port=telnet_port,
                udpc_port=local_addr[1],
                telnet_timeout=telnet_timeout,
                loglevel=_LOGGER.getEffectiveLevel(),
            )
            jpp_task_list.append(
                asyncio.create_task(udpc_updater.start(), name="udpc_updater")
            )

        try:
            await asyncio.gather(
                *jpp_task_list,
            )
        except Exception as e:
            _LOGGER.exception(
                f"A JuicePass Proxy task failed: {e.__class__.__qualname__}: {e}"
            )
            await mqtt_handler.close()
            await mitm_handler.close()
            del mqtt_handler
            del mitm_handler
            if udpc_updater is not None:
                await udpc_updater.close()
                del udpc_updater
            await asyncio.sleep(5)
            _LOGGER.debug(f"jpp_task_list: {jpp_task_list}")
            for task in jpp_task_list:
                task.cancel()
        await asyncio.sleep(5)

    _LOGGER.error("JuicePass Proxy Exiting")
    sys.exit(1)


if __name__ == "__main__":
    run(main(), stop_on_unhandled_errors=True)
