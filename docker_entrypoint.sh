#!/bin/bash

JUICEPASSPROXY="/juicepassproxy/juicepassproxy.py"

function logger() {
  if [ "${1^^}" != "DEBUG" ] || ($DEBUG && [ "${1^^}" = "DEBUG" ]); then
    printf "%-20s %-9s [entrypoint.sh] %s\n" "$(date +'%Y-%m-%d %H:%M:%S')" "${1^^}" "${2}"
  fi
}

echo "--------------------------------"
logger INFO "Starting JuicePass Proxy"
echo ""

JPP_STRING="python3 ${JUICEPASSPROXY}"
logger INFO "Docker Environment Variables:"
if [[ ! -z "${DEVICE_NAME}" ]]; then
  logger INFO "DEVICE_NAME: ${DEVICE_NAME}"
  JPP_STRING+=" --name ${DEVICE_NAME}"
fi
if [[ ! -z "${JUICEBOX_HOST}" ]]; then
  logger INFO "JUICEBOX_HOST: ${JUICEBOX_HOST}"
  JPP_STRING+=" --juicebox_host ${JUICEBOX_HOST}"
fi
if [[ ! -z "${JUICEBOX_ID}" ]]; then
  logger INFO "JUICEBOX_ID: ${JUICEBOX_ID}"
  JPP_STRING+=" --juicebox_id ${JUICEBOX_ID}"
fi
if [[ ! -z "${LOCAL_IP}" ]]; then
  logger INFO "LOCAL_IP: ${LOCAL_IP}"
  JPP_STRING+=" --local_ip ${LOCAL_IP}"
elif [[ ! -z "${SRC}" ]]; then
  logger INFO "LOCAL_IP: ${SRC}"
  JPP_STRING+=" --local_ip ${SRC}"
fi
if [[ ! -z "${LOCAL_PORT}" ]]; then
  logger INFO "LOCAL_PORT: ${LOCAL_PORT}"
  JPP_STRING+=" --local_port ${LOCAL_PORT}"
fi
if [[ ! -z "${ENELX_IP}" ]]; then
  logger INFO "ENELX_IP: ${ENELX_IP}"
  JPP_STRING+=" --enelx_ip ${ENELX_IP}"
elif [[ ! -z "${DST}" ]]; then
  logger INFO "ENELX_IP: ${DST}"
  JPP_STRING+=" --enelx_ip ${DST}"
fi
if [[ ! -z "${MQTT_HOST}" ]]; then
  logger INFO "MQTT_HOST: ${MQTT_HOST}"
  JPP_STRING+=" --mqtt_host ${MQTT_HOST}"
fi
if [[ ! -z "${MQTT_PORT}" ]]; then
  logger INFO "MQTT_PORT: ${MQTT_PORT}"
  JPP_STRING+=" --mqtt_port ${MQTT_PORT}"
fi
if [[ ! -z "${MQTT_USER}" ]]; then
  logger INFO "MQTT_USER: ${MQTT_USER}"
  JPP_STRING+=" --mqtt_user ${MQTT_USER}"
fi
if [[ ! -z "${MQTT_PASS}" ]]; then
  logger INFO "MQTT_PASS: $(echo ${MQTT_PASS} | sed -E 's/./*/g')"
  JPP_STRING+=" --mqtt_password ${MQTT_PASS}"
fi
if [[ ! -z "${MQTT_DISCOVERY_PREFIX}" ]]; then
  logger INFO "MQTT_DISCOVERY_PREFIX: ${MQTT_DISCOVERY_PREFIX}"
  JPP_STRING+=" --mqtt_discovery_prefix ${MQTT_DISCOVERY_PREFIX}"
fi
if [[ ! -z "${JPP_HOST}" ]]; then
  logger INFO "JPP_HOST: ${JPP_HOST}"
  JPP_STRING+=" --juicepass_proxy_host ${JPP_HOST}"
fi
if [[ ! -z "${TELNET_TIMEOUT}" ]]; then
  logger INFO "TELNET_TIMEOUT: ${TELNET_TIMEOUT}"
  JPP_STRING+=" --telnet_timeout ${TELNET_TIMEOUT}"
fi
JPP_STRING+=" --config_loc /config"
if [[ -v LOG_LOC ]]; then
  logger INFO "LOG_LOC: ${LOG_LOC}"
  JPP_STRING+=" --log_loc ${LOG_LOC}"
else
  JPP_STRING+=" --log_loc /log"
fi   
logger INFO "DEBUG: ${DEBUG}"
if $DEBUG; then
  JPP_STRING+=" --debug"
fi
if [[ -v UPDATE_UDPC ]] && $UPDATE_UDPC; then
  JPP_STRING+=" --update_udpc"
  logger INFO "UPDATE_UDPC: true"
else
  logger INFO "UPDATE_UDPC: false"
fi
if [[ -v IGNORE_ENELX ]] && $IGNORE_ENELX; then
  JPP_STRING+=" --ignore_enelx"
  logger INFO "IGNORE_ENELX: true"
else
  logger INFO "IGNORE_ENELX: false"
fi
if [[ -v EXPERIMENTAL ]] && $EXPERIMENTAL; then
  JPP_STRING+=" --experimental"
  logger INFO "EXPERIMENTAL: true"
else
  logger INFO "EXPERIMENTAL: false"
fi
if [[ ! -z "${CRON_REBOOT_SCHEDULE}" ]]; then
  logger INFO "CRON_REBOOT_SCHEDULE: ${CRON_REBOOT_SCHEDULE}"
  JPP_STRING+=" --cron_reboot_schedule \"${CRON_REBOOT_SCHEDULE}\""
fi

logger DEBUG "COMMAND: $(echo "${JPP_STRING}" | sed -E 's/(.* --mqtt_password )([\"]?[a-zA-Z0-9_\?\*\^\&\#\@\!]+[\"]?)/\1*****/g')"
exec bash -c "${JPP_STRING}"
