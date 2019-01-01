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
    0.4.1: Code made compliant with Python plugin framework breaking changes
            https://www.domoticz.com/forum/viewtopic.php?f=65&t=17554
    0.4.2: Code cleanup
    0.4.3: Added support for Synology Jadahl install (different location of zwave config file)
    0.4.4: Fixed typo in battery level low icon callup, causing device update errors for that level
    0.4.5: Fixed bug in the polling of zwave nodes (thanks to domoticz forum user @PBdA !)
    0.4.6: Fixed issue when on system reboot the zwave conf file is empty as openzwave rebuilts it
    0.4.7: Added battery levels as parameters (jrcasal)
    0.4.8: zwave controller validity check at each poll rather than only at startup
"""
"""
<plugin key="BatteryLevel" name="Battery monitoring for Z-Wave nodes" author="logread" version="0.4.8" wikilink="http://www.domoticz.com/wiki/plugins/BatteryLevel.html" externallink="https://github.com/999LV/BatteryLevel">
    <params>
        <param field="Mode1" label="Polling interval (minutes, between 30 and 1440 min)" width="40px" required="true" default="60"/>
        <param field="Mode2" label="Battery Level is Full (percent, between 75 and 99)"  width="40px" required="true" default="75" />
        <param field="Mode3" label="Battery Level is OK (percent, between 40 and 75)"    width="40px" required="true" default="50" />
        <param field="Mode4" label="Battery Level is empty (percent, between 10 and 25)" width="40px" required="true" default="25" />
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


# noinspection SyntaxError
class BasePlugin:

    def __init__(self):
        self.debug = False
        self.BatteryNodes = []  # work list that contains 'zwnode' objects
        self.nextupdate = datetime.now()
        self.pollinterval = 60  # default polling interval in minutes
        self.batterylevelfull = 75 # Default values for Battery Levels
        self.batterylevelok   = 50
        self.batterylevellow  = 25
        self.zwaveinfofilepath = None
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
            self.batterylevelfull = temp
        Domoticz.Log("Setting battery level to full if greater or equal than {} percent".format(str(self.batterylevelfull)))
            
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
            self.batterylevelok = temp
        Domoticz.Log("Setting battery level to normal if greater or equal than {} percent".format(str(self.batterylevelok)))
            
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
            self.batterylevellow = temp
        Domoticz.Log("Setting battery level to empty if less or equal than {} percent".format(str(self.batterylevellow)))
        
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


    def onStop(self):
        Domoticz.Debug("onStop called")
        Domoticz.Debugging(0)


    def onHeartbeat(self):
        now = datetime.now()
        if now >= self.nextupdate:
            self.nextupdate = now + timedelta(minutes=self.pollinterval)
            self.pollnodes()

    # BatteryLevel specific methods

    def pollnodes(self):
        self.BatteryNodes = []

        if not self.zwaveinfofilepath:
            # find zwave controller(s)... only one active allowed !
            controllers = glob.glob("./Config/zwcfg_0x????????.xml")
            if not controllers:
                # test if we are running on a synology (different file locations)
                controllers = glob.glob("/volume1/@appstore/domoticz/var/zwcfg_0x????????.xml")
            for controller in controllers:
                lastmod = datetime.fromtimestamp(os.stat(controller).st_mtime)
                if lastmod < datetime.now() - timedelta(hours=2):
                    Domoticz.Error(
                        "Ignoring controller {} since presumed dead (not updated for more than 2 hours)".format(
                            controller))
                    self.zwaveinfofilepath = None
                else:
                    self.zwaveinfofilepath = controller
                    break

            if not self.zwaveinfofilepath:
                Domoticz.Error("Enable to find a zwave controller configuration file !")
            else:
                # poll the openzwave file
                try:
                    zwavexml = xml.parse(self.zwaveinfofilepath)
                    zwave = zwavexml.getroot()
                except:
                    Domoticz.Error("Error reading openzwave file {}".format(self.zwaveinfofilepath))
                else:
                    for node in zwave:
                        for commandclass in node[1]:  # node[1] is the list of CommandClasses
                            if commandclass.attrib["id"] == "128":  # CommandClass id=128 is BATTERY_LEVEL
                                self.BatteryNodes.append(zwnode(int(node.attrib["id"]), node.attrib["name"],
                                                                int(commandclass[1].attrib["value"])))
                                break

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
            if levelBatt >= self.batterylevelfull:
                icon = "batterylevelfull"
            elif levelBatt >= self.batterylevelok:
                icon = "batterylevelok"
            elif levelBatt >= self.batterylevellow:
                icon = "batterylevellow"
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