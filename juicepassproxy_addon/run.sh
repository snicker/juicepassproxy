#!/usr/bin/env bashio

export MQTT_HOST="$(bashio::services mqtt 'host')"
export MQTT_USER="$(bashio::services mqtt 'username')"
export MQTT_PASS="$(bashio::services mqtt 'password')"

export JUICEBOX_HOST="$(bashio::config 'juicebox_host')"
export DEVICE_NAME="$(bashio::config 'juicebox_device_name')"
export DEBUG="$(bashio::config 'debug')"
export IGNORE_ENELX="$(bashio::config 'ignore_enelx')"
export LOCAL_PORT="8042"

/juicepassproxy/docker_entrypoint.sh
