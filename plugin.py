# Domoticz Python plugin for Monitoring and logging of battery level for z-wave nodes
#
# Author: Logread
#
# Version: 0.2.0: made code more object oriented with cleaner scoping of variables
# Version: 0.3.0: refactor of code to use asyncronous callbacks for http calls
# Version: 0.3.1: skip zwave devices with "non standard" ID attribution (thanks @bdormael)
# Version: 0.3.2: rewrote the hashing of device ID into zwave node id in line with /hardware/ZWaveBase.cpp
#
"""
<plugin key="BatteryLevel" name="Battery monitoring for Z-Wave nodes" author="logread" version="0.3.2" wikilink="http://www.domoticz.com/wiki/plugins/BatteryLevel.html" externallink="https://github.com/999LV/BatteryLevel">
    <params>
        <param field="Address" label="Source Domoticz IP Address" width="200px" required="true" default="127.0.0.1"/>
        <param field="Port" label="Port" width="40px" required="true" default="8080"/>
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
import json

icons = {"batterylevelfull": "batterylevelfull icons.zip",
         "batterylevelok": "batterylevelok icons.zip",
         "batterylevellow": "batterylevellow icons.zip",
         "batterylevelempty": "batterylevelempty icons.zip"}

class c_node:
    def __init__(self, name, level):
        self.name = name
        self.level = level

class BasePlugin:

    def __init__(self):
        self.debug = False
        self.maxhartbeats = 59 * 6  # poll and update every 59 minutes, so that devices do not turn red in the GUI due to inactivity...
        #self.maxhartbeats = 6 # for debug
        self.lasthartbeat = -1
        self.hwidx = 0  # hardware idx of zwave controller
        self.zwNodes = {}  # list of all zwave nodes
        self.BatteryNodes = {}  # work dictionary for the plugin
        self.APIRequest = ""
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

        Domoticz.Transport("TCP/IP", Parameters["Address"], Parameters["Port"])
        Domoticz.Protocol("HTTP")

        # initiates initial Domoticz API request for a list of present Hardware
        self.APIRequest = "/json.htm?type=hardware"
        Domoticz.Connect()

    def onStop(self):
        Domoticz.Debug("onStop called")
        Domoticz.Debugging(0)

    def onConnect(self, Status, Description):
        Domoticz.Debug("onConnect called")
        data = ''
        headers = {'Content-Type': 'text/xml; charset=utf-8',
                   'Connection': 'close',
                   'Accept': 'Content-Type: text/html; charset=UTF-8',
                   'Host': Parameters["Address"] + ":" + Parameters["Port"],
                   'User-Agent': 'Domoticz/1.0',
                   'Content-Length': "%d" % (len(data))}
        Domoticz.Send(data, 'GET', self.APIRequest, headers)
        return True

    def onMessage(self, Data, Status, Extra):
        Domoticz.Debug("onMessage called")
        strData = Data.decode("utf-8", "ignore")
        Domoticz.Debug("HTTP Status = " + str(Status))
        if Status == 200:
            Response = json.loads(strData)
            Domoticz.Debug("Received Domoticz API response for " + Response["title"])
            if Response["status"] == "OK" and "title" in Response:
                if Response["title"] == "Hardware":
                    self.getZWaveController(Response)
                elif Response["title"] == "OpenZWaveNodes":
                    self.getZWaveNodes(Response)
                elif Response["title"] == "Devices":
                    self.scanDevices(Response)
                else:
                    Domoticz.Error("Unknown Domoticz API response " + + Response["title"])
            else:
                Domoticz.Error("Domoticz API returned an error")
        else:
            Domoticz.Debug("Domoticz HTTP connection error")

    def onCommand(self, Unit, Command, Level, Hue):
        Domoticz.Debug("onCommand called for Unit " + str(Unit) + ": Parameter '" + str(Command) + "', Level: " + str(Level))

    def onNotification(self, Name, Subject, Text, Status, Priority, Sound, ImageFile):
        Domoticz.Debug("Notification: " + Name + "," + Subject + "," + Text + "," + Status + "," + str(Priority) + "," + Sound + "," + ImageFile)

    def onDisconnect(self):
        Domoticz.Debug("onDisconnect called")

    def onHeartbeat(self):
        if self.lasthartbeat == -1 and self.hwidx > 0:  # This is our first heartbeat and we have a zwave controller... Obtain ZWave nodes
            self.lasthartbeat = 0
            self.APIRequest = "/json.htm?type=openzwavenodes&idx=" + str(self.hwidx)
            Domoticz.Connect()
        else:
            self.lasthartbeat += 1
            if self.lasthartbeat >= self.maxhartbeats:
                self.lasthartbeat = 0
            elif self.lasthartbeat == 1:
                self.APIRequest = "/json.htm?type=devices&filter=all&order=Name"
                Domoticz.Connect()
                if self.debug:
                    Domoticz.Debug("Process loop called")

    # BatteryLevel specific methods

    def getZWaveController(self, listHW):
        if listHW["status"] == "OK":
            Domoticz.Debug("Hardware scanned")
            for x in listHW["result"]:
                if x["Type"] == 21:
                    Domoticz.Log("ZWave controller found: name = " + x["Name"] + ", idx=" + str(x["idx"]))
                    self.hwidx = int(x["idx"])
                    break
            if self.hwidx == 0:
                Domoticz.Error("No ZWave controller found")
        else:
            Domoticz.Error("Hardware scan failed")

    def getZWaveNodes(self, listNodes):
        if listNodes["status"] == "OK":
            Domoticz.Debug("ZWave nodes scanned")
            for x in listNodes["result"]:
                Domoticz.Debug("Zwave node found: " + str(x["NodeID"]) + " " + x["Name"])
                self.zwNodes[str(x["NodeID"])] = x["Name"]
        else:
            Domoticz.Error("ZWave nodes scan failed")

    def scanDevices(self, listDevs):
        """
        scans all devices in the target Domoticz system and extracts all these that
        a) are battery operated and
        b) belong to the zwave controller
        c) updates the self.BatteryNodes dictionnary accordingly
        d) updates the Domoticz devices
        :return: nothing 
        """
        self.BatteryNodes = {}
        if listDevs["status"] == "OK":
            Domoticz.Debug("Devices scanned")
            for device in listDevs["result"]:
                if device["BatteryLevel"] < 255 and device["HardwareID"] == self.hwidx:
                    FullID = int(device["ID"], 16)
                    #ID1 = (FullID & 0xFF000000) >> 24
                    ID2 = (FullID & 0x00FF0000) >> 16
                    ID3 = (FullID & 0x0000FF00) >> 8
                    #ID4 = (FullID & 0x000000FF)
                    nodeID = (ID2 << 8) | ID3
                    if nodeID == 0:
                        nodeID = FullID
                    s_nodeID = str(nodeID)
                    Domoticz.Debug("Battery device found: name = " + device["Name"] + ", idx=" + str(device["idx"]) +
                                   ", Battery=" + str(device["BatteryLevel"]) + ", Zwave Node = " + s_nodeID)
                    if s_nodeID in self.zwNodes:
                        self.BatteryNodes[str(nodeID)] = c_node(self.zwNodes[s_nodeID], device["BatteryLevel"])
                    else:
                        Domoticz.Debug("Skipped processing of device idx = " + str(device["idx"]) + " due to invalid node = " + s_nodeID)
        else:
            Domoticz.Error("Devices scan failed")

        for node in self.BatteryNodes:
            unit = int(node)
            Domoticz.Debug(
                "Battery Node " + node + " " + self.BatteryNodes[node].name + " " +
                str(self.BatteryNodes[node].level))
            # if device does not yet exist, then create it
            if not (unit in Devices):
                Domoticz.Device(Name=self.BatteryNodes[node].name, Unit=unit, TypeName="Custom",
                                Options={"Custom": "1;%"}).Create()
            self.UpdateDevice(unit, str(self.BatteryNodes[node].level))

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
