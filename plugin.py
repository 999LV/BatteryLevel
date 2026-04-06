"""
Domoticz Python plugin for Monitoring and logging of battery level for z-wave nodes

Author: Logread (aka 999LV on GitHub). Contact @logread on www.domoticz.com/forum

Icons are from wpclipart.com. many thanks to them for these public domain graphics:

Versions:
    0.2.0: made code more object oriented with cleaner scoping of variables
    0.3.0: refactor of code to use asyncronous callbacks for http calls
    0.3.1: skip zwave devices with "non standard" ID attribution (thanks @bdormael)
    0.3.2: rewrote the hashing of device ID into zwave node id in line with /hardware/ZWaveBase.cpp
    0.4.0: Major change: Use openzwave as data source instead of the Domoticz API...
            simpler, faster and possibly more "real-time" information
    0.4.1: Code made compliant with Python plugin framework breaking changes
            https://www.domoticz.com/forum/viewtopic.php?f=65&t=17554
    0.4.2: Code cleanup
    0.4.3: Added support for Synology Jadahl install (different location of zwave config file)
    0.4.4: Fixed typo in battery level low icon callup, causing device update errors for that level
    0.4.5: Fixed bug in the polling of zwave nodes (thanks to domoticz forum user @PBdA !)
    0.4.6: Fixed issue when on system reboot the zwave conf file is empty as openzwave rebuilts it
    0.4.7: Added battery levels as parameters (jrcasal)
    0.4.8: zwave controller validity check at each poll rather than only at startup
    0.5.0: Support of openzwave 1.6 breaking changes
    0.5.1: Minor code improvements
    0.5.2: Do not update devices if no change in battery level + added plugin description for HW page + cosmetics
    0.6.0: Major rewrite since openzwave 1.6 no longer updates cache file.
            Using a new domoticz API call created on purpose by @gizmocuz ! Many thanks to him
    0.6.1: update domoticz version check following new version numbering scheme implemented 22/03/2020 in domoticz
    0.7.0: complete revamping to work with MQTT zwave-js-ui as openzwave has been deprecated.
    0.7.1: adjust code to changes in paho.mqtt python module (no "force" parameter anymore)

    WARNING !!! PREREQUISITE: install paho.mqtt python module "sudo pip install paho.mqtt" (see https://github.com/eclipse/paho.mqtt.python)
"""
"""
<plugin key="BatteryLevel" name="Battery monitoring for Z-Wave nodes" author="logread" version="0.7.1" wikilink="http://www.domoticz.com/wiki/plugins/BatteryLevel.html" externallink="https://github.com/999LV/BatteryLevel">
    <description>
        <h2>Battery Level Plugin</h2><br/>
        Version 0.7.1 for domoticz version 2022.2 minimum. Prerequisite: "sudo pip install paho.mqtt"
        <p>This plugin allows monitoring of the battery level of ZWave devices managed by zwave-js-ui via MQTT.
        </p>
        <ol><li>It polls at regular intervals domoticz for battery operated nodes and creates/updates a Domoticz device for each.</li>
        <li>Each of the devices representing a battery operated z-wave node will allow:
        <ol><li>An easy to read display of the current battery level</li>
        <li>Logging over time like for any Domoticz sensor</li>
        <li>The definition of custom battery level notifications or events for each specific z-wave node</li>
        <li>As a bonus, a dynamic icon will display the battery level in 4 colors (green if &gt;75%, yellow if 50 to 75%, orange if 25 to 50% and red if below 25%).</li>
        <li>NOTE: upon Domoticz startup, battery levels will not be available until each zwave node sends update/wakes up. Please be patient as it may take a few</li>
        <li>hours for devices to be created (for new installs or newly included zwave nodes) or updated (red background in the GUI).</li>
        </ol></li></ol>
    </description>
    <params>
        <param field="Address" label="zwave-js-ui IP address" width="200px" required="true" default="127.0.0.1"/>
        <param field="Port" label="Port" width="60px" required="true" default="1883"/>
        <param field="Username" label="MQTT Username" width="200px" required="false" default=""/>
        <param field="Password" label="MQTT Password" width="200px" required="false" default=""/>
        <param field="Mode1" label="Polling interval (minutes, between 30 and 1440 min)" width="40px" required="true" default="60"/>
        <param field="Mode2" label="Battery Level is Full (percent, between 75 and 99)"  width="40px" required="true" default="75" />
        <param field="Mode3" label="Battery Level is OK (percent, between 40 and 75)"    width="40px" required="true" default="50" />
        <param field="Mode4" label="Battery Level is empty (percent, between 10 and 25)" width="40px" required="true" default="25" />
        <param field="Mode5" label="MQTT name of zwave-js-ui client" width="200px" required="true" default="zwave-js-ui"/>
        <param field="Mode6" label="Debug" width="75px">
            <options>
                <option label="True"  value="Debug"/>
                <option label="False" value="Normal"  default="true" />
            </options>
        </param>
    </params>
</plugin>
"""
import Domoticz
import json
from datetime import datetime
from datetime import timedelta
import paho.mqtt.client as mqtt


icons = {"batterylevelfull": "batterylevelfull icons.zip",
         "batterylevelok": "batterylevelok icons.zip",
         "batterylevellow": "batterylevellow icons.zip",
         "batterylevelempty": "batterylevelempty icons.zip"}


class BasePlugin:

    def __init__(self):
        global batterylevelfull, batterylevelok, batterylevellow
        self.debug = False
        self.BatteryNodes = []      # work list that contains 'zwnode' objects
        self.nextupdate = datetime.now()
        self.pollinterval = 60      # default polling interval in minutes
        batterylevelfull = 75  # Default values for Battery Levels
        batterylevelok   = 50
        batterylevellow  = 25
        self.MQTT_OK = False


    def onStart(self):
        global icons, topic, batterylevelfull, batterylevelok, batterylevellow
        if Parameters["Mode6"] == 'Debug':
            self.debug = True
            Domoticz.Debugging(1)
            DumpConfigToLog()
        else:
            Domoticz.Debugging(0)
        Domoticz.Debug("onStart called")

        # proceed with the plugin setup

        # Load custom battery levels
        # Battery  Full
        try:
            temp = int(Parameters["Mode2"])
        except:
            Domoticz.Error("Invalid Battery Full parameter")
        else:
            if temp < 75:
                temp = 75
                Domoticz.Error("Specified Battery Full value too low: changed to 75%")
            elif temp > 99:
                temp = 99
                Domoticz.Error("Specified Battery Full value too high: changed to 99%")
            batterylevelfull = temp
        Domoticz.Log("Setting battery level to full if greater or equal than {} percent".format(batterylevelfull))

        # Battery OK
        try:
            temp = int(Parameters["Mode3"])
        except:
            Domoticz.Error("Invalid Battery OK parameter")
        else:
            if temp < 40:
                temp = 40
                Domoticz.Error("Specified Battery OK value too low: changed to 40%")
            elif temp > 75:
                temp = 75
                Domoticz.Error("Specified Battery OK value too high: changed to 75%")
            batterylevelok = temp
        Domoticz.Log("Setting battery level to normal if greater or equal than {} percent".format(batterylevelok))

        # Battery LOW
        try:
            temp = int(Parameters["Mode4"])
        except:
            Domoticz.Error("Invalid Battery LOW parameter")
        else:
            if temp < 10:
                temp = 10
                Domoticz.Error("Specified Battery LOW value too low: changed to 10%")
            elif temp > 25:
                temp = 25
                Domoticz.Error("Specified Battery LOW value too high: changed to 25%")
            batterylevellow = temp
        Domoticz.Log("Setting battery level to empty if less or equal than {} percent".format(batterylevellow))

        # load custom battery images
        for key, value in icons.items():
            if key not in Images:
                Domoticz.Image(value).Create()
                Domoticz.Debug("Added icon: " + key + " from file " + value)
        Domoticz.Debug("Number of icons loaded = " + str(len(Images)))
        for image in Images:
            Domoticz.Debug("Icon " + str(Images[image].ID) + " " + Images[image].Name)

        # check polling interval parameter
        try:
            temp = int(Parameters["Mode1"])
        except:
            Domoticz.Error("Invalid polling interval parameter")
        else:
            if temp < 30:
                temp = 30  # minimum polling interval
                Domoticz.Error("Specified polling interval too short: changed to 30 minutes")
            elif temp > 1440:
                temp = 1440  # maximum polling interval is 1 day
                Domoticz.Error("Specified polling interval too long: changed to 1440 minutes (24 hours)")
            self.pollinterval = temp
        Domoticz.Status("Using polling interval of {} minutes".format(str(self.pollinterval)))

        # create MQQT connection, connect to it and start network loop
        self.client = mqtt.Client()
        self.client.on_connect = on_connect
        self.client.on_disconnect = on_disconnect
        self.client.on_message = on_message
        self.client.username_pw_set(Parameters["Username"], password=Parameters["Password"])
        topic = "zwave/_CLIENTS/ZWAVE_GATEWAY-{}/api/getNodes".format(Parameters["Mode5"])
        try:
            # establish an asynchronous connection (different thread)
            self.client.connect_async(Parameters["Address"], int(Parameters["Port"]), 60)
        except Exception as err:
            Domoticz.Error("MQTT connection error: {}".format(err))
        else:
            self.MQTT_OK = True
            Domoticz.Debug("Starting MQTT network loop")
            # launch MQTT network loop thread
            self.client.loop_start()


    def onStop(self):
        Domoticz.Debug("onStop called")
        Domoticz.Debugging(0)
        # kill the MQTT loop thread
        self.client.loop_stop(force=True)
        self.client.disconnect()


    def onHeartbeat(self):
        global topic
        now = datetime.now()
        if now >= self.nextupdate:
            self.nextupdate = now + timedelta(minutes=self.pollinterval)
            if self.MQTT_OK:
                Domoticz.Status("Polling MQTT client '{}' for zwave nodes data".format(Parameters["Mode5"]))
                self.client.publish(topic + "/set", payload='{"args": []}', qos=0, retain=False)


def on_connect(client, userdata, flags, rc):
    global topic
    Domoticz.Debug("Connected to MQTT with result code {}".format(rc))
    # Subscribing in on_connect() means that if we lose the connection and
    # reconnect then subscriptions will be renewed.
    client.subscribe(topic)


def on_disconnect(client, userdata, rc):
    if rc != 0:
        Domoticz.Error("Unexpected disconnection from MQTT. Error code {}".format(rc))
    else:
        Domoticz.Debug("Disconnect from MQTT broker OK !")


def on_message(client, userdata, msg):
    global topic, batterylevelfull, batterylevelok, batterylevellow
    Domoticz.Debug("MQTT message received: {}".format(msg.topic))
    if msg.topic == topic:
        Domoticz.Debug("MQTT response received")
        r = json.loads(msg.payload.decode())
        if r["success"]:
            BatteryNodes = {}
            Domoticz.Status("zwave nodes data received from MQTT client '{}'. Updating devices as required.".format(Parameters["Mode5"]))
            # loop all nodes received from MQTT client
            for node in r["result"]:
                if "minBatteryLevel" in node:
                    Domoticz.Debug("Node {} {} has battery level of {}%".format(node["id"], node["name"], node["minBatteryLevel"]))
                    if not (int(node["id"]) in Devices):
                        Domoticz.Device(Name=node["name"] if node["name"] != "" else "Node {}".format(node["id"]), Unit=int(node["id"]),
                                        TypeName="Custom", Options={"Custom": "1;%"}).Create()
                    BatteryNodes[int(node["id"])] = int(node["minBatteryLevel"])
            # loop all devices of the plugin and check if we need to update or mark as not  updated
            for Unit in Devices:
                Domoticz.Debug("Unit = {} {}".format(Unit, type(Unit)))
                try:
                    levelBatt = int(BatteryNodes[Unit])
                except KeyError:  # the node is not in the list returned by the MQTT zwave gateway... e.g. not yet updated or deleted ?
                    UpdateDevice(Unit, TimedOut=True)
                else:
                    if levelBatt >= batterylevelfull:
                        icon = "batterylevelfull"
                    elif levelBatt >= batterylevelok:
                        icon = "batterylevelok"
                    elif levelBatt >= batterylevellow:
                        icon = "batterylevellow"
                    else:
                        icon = "batterylevelempty"
                    UpdateDevice(Unit, sValue=str(BatteryNodes[Unit]), TimedOut=False, Image=Images[icon].ID)
        else:
            Domoticz.Error("MQTT call error: {}".format(r["message"]))
            for Unit in Devices:  # loop all devices of the plugin and mark as timedout due to bad MQTT status
                UpdateDevice(Unit, TimedOut=True)


def UpdateDevice(Unit, **kwargs):
    if Unit in Devices:
        # check if kwargs contain an update for nValue or sValue... if not, use the existing one(s)
        if "nValue" in kwargs:
            nValue = kwargs["nValue"]
        else:
            nValue = Devices[Unit].nValue
        if "sValue" in kwargs:
            sValue = kwargs["sValue"]
        else:
            sValue = Devices[Unit].sValue

        # build the arguments for the call to Device.Update
        update_args = {"nValue": nValue, "sValue": sValue}
        change = False
        if nValue != Devices[Unit].nValue or sValue != Devices[Unit].sValue:
            change = True
        for arg in kwargs:
            if arg == "TimedOut":
                if kwargs[arg] != Devices[Unit].TimedOut:
                    change = True
                    update_args[arg] = kwargs[arg]
                Domoticz.Debug("TimedOut = {}".format(kwargs[arg]))
            if arg == "BatteryLevel":
                if kwargs[arg] != Devices[Unit].BatteryLevel:
                    change = True
                    update_args[arg] = kwargs[arg]
                Domoticz.Debug("BatteryLevel = {}".format(kwargs[arg]))
            if arg == "Color":
                try:
                    if kwargs[arg] != Devices[Unit].Color:
                        change = True
                except:
                    change = True
                finally:
                    if change:
                        update_args[arg] = kwargs[arg]
                Domoticz.Debug("Color = {}".format(kwargs[arg]))
            if arg == "Image":
                    if kwargs[arg] != Devices[Unit].Image:
                        change = True
                        update_args[arg] = kwargs[arg]
            if arg == "Forced":
                change = change or kwargs[arg]
        Domoticz.Debug("Change in device {} = {}".format(Unit, change))
        if change:
            Devices[Unit].Update(**update_args)


global _plugin
_plugin = BasePlugin()


def onStart():
    global _plugin
    _plugin.onStart()


def onStop():
    global _plugin
    _plugin.onStop()


def onHeartbeat():
    global _plugin
    _plugin.onHeartbeat()


# Generic helper functions
def DumpConfigToLog():
    for x in Parameters:
        if Parameters[x] != "":
            Domoticz.Debug( "'" + x + "':'" + str(Parameters[x]) + "'")
    Domoticz.Debug("Device count: " + str(len(Devices)))
    for x in Devices:
        Domoticz.Debug("Device:           " + str(x) + " - " + str(Devices[x]))
        Domoticz.Debug("Device ID:       '" + str(Devices[x].ID) + "'")
        Domoticz.Debug("Device Name:     '" + Devices[x].Name + "'")
        Domoticz.Debug("Device nValue:    " + str(Devices[x].nValue))
        Domoticz.Debug("Device sValue:   '" + Devices[x].sValue + "'")
        Domoticz.Debug("Device LastLevel: " + str(Devices[x].LastLevel))
    return
