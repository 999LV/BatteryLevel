"""
Domoticz Python plugin for Monitoring and logging of battery level for z-wave nodes

Author: Logread

Versions:
    0.2.0: made code more object oriented with cleaner scoping of variables
    0.3.0: refactor of code to use asyncronous callbacks for http calls
    0.3.1: skip zwave devices with "non standard" ID attribution (thanks @bdormael)
    0.3.2: rewrote the hashing of device ID into zwave node id in line with /hardware/ZWaveBase.cpp
    0.4.0: Major change: Use openzwave as data source instead of the Domoticz API... 
        simpler, faster and possibly more "real-time" information
#
"""
"""
<plugin key="BatteryLevel" name="Battery monitoring for Z-Wave nodes" author="logread" version="0.4.0" wikilink="http://www.domoticz.com/wiki/plugins/BatteryLevel.html" externallink="https://github.com/999LV/BatteryLevel">
    <params>
        <param field="Mode1" label="Polling interval (minutes, 30 mini)" width="40px" required="true" default="60"/>
        <param field="Mode6" label="Debug" width="75px">
            <options>
                <option label="True" value="Debug"/>
                <option label="False" value="Normal"  default="true" />
            </options>
        </param>
    </params>
</plugin>
"""
import Domoticz
import xml.etree.ElementTree as xml
import os
import glob
from datetime import datetime
from datetime import timedelta

icons = {"batterylevelfull": "batterylevelfull icons.zip",
         "batterylevelok": "batterylevelok icons.zip",
         "batterylevellow": "batterylevellow icons.zip",
         "batterylevelempty": "batterylevelempty icons.zip"}

class zwnode:
    def __init__(self, nodeid, name, level):
        self.nodeid = nodeid
        self.name = name
        self.level = level

class BasePlugin:

    def __init__(self):
        self.debug = False
        self.BatteryNodes = []  # work list that contains 'zwnode' objects
        self.nextupdate = datetime.now()
        self.pollinterval = 60  # default polling interval in minutes
        self.zwaveinfofilepath = ""
        self.error = False
        return

    def onStart(self):
        global icons
        Domoticz.Debug("onStart called")
        if Parameters["Mode6"] == 'Debug':
            self.debug = True
            Domoticz.Debugging(1)
            DumpConfigToLog()
        else:
            Domoticz.Debugging(0)

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
        Domoticz.Log("Using polling interval of {} minutes".format(str(self.pollinterval)))

        # find zwave controller(s)... only one active allowed !
        self.error = True
        controllers = glob.glob("./Config/zwcfg_0x????????.xml")
        for controller in controllers:
            lastmod = datetime.fromtimestamp(os.stat(controller).st_mtime)
            if lastmod < datetime.now() - timedelta(hours=2):
                Domoticz.Error("Ignoring controller {} since presumed dead (not updated for more than 2 hours)".format(controller))
            else:
                self.zwaveinfofilepath = controller
                self.error = False
                break
        if self.error:
            Domoticz.Error("Enable to find a zwave controller configuration file !")

    def onStop(self):
        Domoticz.Debug("onStop called")
        Domoticz.Debugging(0)

    def onConnect(self, Status, Description):
        Domoticz.Debug("onConnect called")
        return True

    def onMessage(self, Data, Status, Extra):
        return

    def onCommand(self, Unit, Command, Level, Hue):
        Domoticz.Debug("onCommand called for Unit " + str(Unit) + ": Parameter '" + str(Command) + "', Level: " + str(Level))

    def onNotification(self, Name, Subject, Text, Status, Priority, Sound, ImageFile):
        Domoticz.Debug("Notification: " + Name + "," + Subject + "," + Text + "," + Status + "," + str(Priority) + "," + Sound + "," + ImageFile)

    def onDisconnect(self):
        Domoticz.Debug("onDisconnect called")

    def onHeartbeat(self):
        now = datetime.now()
        if now >= self.nextupdate:
            self.nextupdate = now + timedelta(minutes=self.pollinterval)
            self.pollnodes()

    # BatteryLevel specific methods

    def pollnodes(self):
        # poll the openzwave file
        if not self.error:
            try:
                zwavexml = xml.parse(self.zwaveinfofilepath)
                zwave = zwavexml.getroot()
            except:
                error = True
                Domoticz.Error("Error reading openzwave file {}".format(self.zwaveinfofilepath))
            else:
                for node in zwave:
                    for commandclass in node[1]:  # node[1] is the list of CommandClasses
                        if commandclass.attrib["id"] == "128":  # CommandClass id=128 is BATTERY_LEVEL
                            self.BatteryNodes.append(zwnode(int(node.attrib["id"]), node.attrib["name"],
                                                            int(commandclass[1].attrib["value"])))
                            break
        if self.error:
            self.BatteryNodes = []

        for node in self.BatteryNodes:
            Domoticz.Debug("Node {} {} has battery level of {}%".format(node.nodeid, node.name, node.level))
            # if device does not yet exist, then create it
            if not (node.nodeid in Devices):
                Domoticz.Device(Name=node.name, Unit=node.nodeid, TypeName="Custom",
                                Options={"Custom": "1;%"}).Create()
            self.UpdateDevice(node.nodeid, str(node.level))

    def UpdateDevice(self, Unit, Percent):
        # Make sure that the Domoticz device still exists (they can be deleted) before updating it
        if Unit in Devices:
            levelBatt = int(Percent)
            if levelBatt >= 75:
                icon = "batterylevelfull"
            elif levelBatt >= 50:
                icon = "batterylevelok"
            elif levelBatt >= 25:
                icon = "batterylevelow"
            else:
                icon = "batterylevelempty"
            try:
                Devices[Unit].Update(nValue=0, sValue=Percent, Image=Images[icon].ID)
            except:
                Domoticz.Error("Failed to update device unit " + str(Unit))
        return

global _plugin
_plugin = BasePlugin()

def onStart():
    global _plugin
    _plugin.onStart()

def onStop():
    global _plugin
    _plugin.onStop()

def onConnect(Status, Description):
    global _plugin
    _plugin.onConnect(Status, Description)

def onMessage(Data, Status, Extra):
    global _plugin
    _plugin.onMessage(Data, Status, Extra)

def onCommand(Unit, Command, Level, Hue):
    global _plugin
    _plugin.onCommand(Unit, Command, Level, Hue)

def onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile):
    global _plugin
    _plugin.onNotification(Name, Subject, Text, Status, Priority, Sound, ImageFile)

def onDisconnect():
    global _plugin
    _plugin.onDisconnect()

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
