# Config

**juicebox_host**: Set this field to the ip of the JuiceBox device.

**juicebox_device_name**: Set this field to the name of the device given in the Enel X Way app.

**debug**: Enable debug logging

# Setup

There is some required setup to get some of the config values and ensure the device connects to the proxy.

1. Find the ip of the JuiceBox. This should be available in the router assuming it provides DHCP. Set the ip as static so that the IP doesn't change. This value is used as `juicebox_host` above.
2. Connect to the juicebox via telnet: `telnet <ip> 2000`, and type `list` to get the connect domain/port in the line marked UDPC.
3. Setup dns override for the domain found in step 2 so that the domain maps to the system running juicepassproxy (home assistant ip)

# Notes

I had to intercept DNS for both `juicenet-udp-prod5-usa.enelx.com` and `jbv1.emotorwerks.com`. It's unclear if that's due to fiddling I did in the remote console, or if it came that way.
