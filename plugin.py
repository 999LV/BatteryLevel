# Domoticz Python plugin for Monitoring and logging of battery level for z-wave nodes
#
# Author: Logread
#
# Version: 0.1.0: First Beta release
#
"""
<plugin key="BatteryLevel" name="Battery monitoring for Z-Wave nodes" author="logread" version="0.1.0" wikilink="http://www.domoticz.com/wiki/plugins/plugin.html" externallink="https://github.com/999LV/BatteryLevel">
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
import urllib.request as request

hwidx = 0  # hardware idx of zwave controller
zwNodes = {}  # list of all zwave nodes
BatteryNodes = {}  # work dictionary for the plugin
icons = {"batterylevelfull": "batterylevelfull icons.zip",
         "batterylevelok": "batterylevelok icons.zip",
         "batterylevellow": "batterylevellow icons.zip",
         "batterylevelempty": "batterylevelempty icons.zip"}

class BasePlugin:

    debug = False
    maxhartbeats = 59*6 # poll and update every 59 minutes, so that devices do not turn red in the GUI due to inactivity... this is a compromise setting
    #maxhartbeats = 6 # for debug
    lasthartbeat = 0

    def __init__(self):
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

        # perform initial poll and update
        PollAndUpdate()

    def onStop(self):
        Domoticz.Debug("onStop called")
        Domoticz.Debugging(0)

    def onConnect(self, Status, Description):
        Domoticz.Debug("onConnect called")
        return True

    def onMessage(self, Data, Status, Extra):
        Domoticz.Debug("onMessage called")

    def onCommand(self, Unit, Command, Level, Hue):
        Domoticz.Debug("onCommand called for Unit " + str(Unit) + ": Parameter '" + str(Command) + "', Level: " + str(Level))

    def onNotification(self, Name, Subject, Text, Status, Priority, Sound, ImageFile):
        Domoticz.Debug("Notification: " + Name + "," + Subject + "," + Text + "," + Status + "," + str(Priority) + "," + Sound + "," + ImageFile)

    def onDisconnect(self):
        Domoticz.Debug("onDisconnect called")

    def onHeartbeat(self):
        self.lasthartbeat += 1
        if self.lasthartbeat >= self.maxhartbeats:
            self.lasthartbeat = 0
            PollAndUpdate()
            if self.debug:
                Domoticz.Debug("onHeartbeat called")

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

# BatteryLevel specific functions

def dzAPICall(APIRequest):
    """
    Generic function to access the Domoticz API
    :param APIRequest: a valid API request e.g. '/json.htm?type=hardware'
    :return: the json object returned by the Domoticz API
    """
    url = "http://" + Parameters["Address"] + ":" + Parameters["Port"] + APIRequest
    retobj = {}
    try:
        response = request.urlopen(url, None, 30)
        if response.status == 200:
            Domoticz.Debug("Domoticz API Call '" + url + "' success")
            str_response = response.read().decode('utf-8')
            retobj = json.loads(str_response)
        else:
            Domoticz.Error("Domoticz API Call '" + url + "' failed")
            retobj["status"] = "Error"
    except request.URLError:
        Domoticz.Error("http call failed... Check network, IP, port or target system")
        retobj["status"] = "Error"
    return retobj

def getZWaveNodes():
    """
    Scans the target Domoticz system for a zwave controller (only the first one will be identified) and
    scans all dependant zwave nodes to build a dictionnary of zwave nodes with key = node ID
    :return: a dictionnary with all zwave nodes found. Also updates the self.hwidx variable with the hardware id of zwave controller found 
    """
    global hwidx
    listZWNodes = {}
    hwidx = 0
    listHW = dzAPICall("/json.htm?type=hardware")
    if listHW["status"] == "OK":
        Domoticz.Debug("Hardware scanned")
        for x in listHW["result"]:
            if x["Type"] == 21:
                Domoticz.Debug("ZWave controller found: name = " + x["Name"] + ", idx=" + str(x["idx"]))
                hwidx = int(x["idx"])
                break
        if hwidx == 0:
            Domoticz.Error("No ZWave controller found")
    else:
        Domoticz.Error("Hardware scan failed")

    if hwidx > 0:
        listNodes = dzAPICall("/json.htm?type=openzwavenodes&idx=" + str(hwidx))
        if listNodes["status"] == "OK":
            Domoticz.Debug("ZWave nodes scanned")
            for x in listNodes["result"]:
                Domoticz.Debug("Zwave node found: " + str(x["NodeID"]) + " " + x["Name"])
                listZWNodes[str(x["NodeID"])] = x["Name"]
        else:
            Domoticz.Error("ZWave nodes scan failed")
    return listZWNodes

def scanDevices():
    """
    scans all devices in the target Domoticz system and extracts all these that
    a) are battery operated and
    b) belong to the zwave controller
    updates the self.BatteryNodes dictionnary accordingly
    :return: nothing 
    """
    global hwidx, BatteryNodes
    BatteryNodes = {}
    listDevs = dzAPICall("/json.htm?type=devices&filter=all&order=Name")
    if listDevs["status"] == "OK":
        Domoticz.Debug("Devices scanned")
        for x in listDevs["result"]:
            if x["BatteryLevel"] < 255 and x["HardwareID"] == hwidx:
                nodeID = int(x["ID"][:-2], 16)  # calculate the zwave node id that the domoticz device belongs to
                Domoticz.Debug("Battery device found: name = " + x["Name"] + ", idx=" + str(x["idx"]) + \
                      ", Battery=" + str(x["BatteryLevel"]) + ", Zwave Node = " + str(nodeID))
                BatteryNodes[str(nodeID)] = {"Name": zwNodes[str(nodeID)], "Level": x["BatteryLevel"]}
    else:
        Domoticz.Error("Devices scan failed")

def PollAndUpdate():
    """
    wrapper main function:
    Scans the target Domoticz system for zwave nodes,
    Polls devices for battery level and create/update plugin devices accordingly
    :return: nothing
    """
    global zwNodes, BatteryNodes
    zwNodes= getZWaveNodes()
    if len(zwNodes) > 0:
        scanDevices()
        for node in BatteryNodes:
            unit = int(node)
            Domoticz.Debug("Battery Node " + node + " " + BatteryNodes[node]["Name"] + " " + str(BatteryNodes[node]["Level"]))
            # if device does not yet exist, then create it
            if not (unit in Devices):
                Domoticz.Device(Name=BatteryNodes[node]["Name"], Unit=unit, TypeName="Custom", Options={"Custom": "1;%"}).Create()
            UpdateDevice(unit, str(BatteryNodes[node]["Level"]))

def UpdateDevice(Unit, Percent):
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
        Devices[Unit].Update(nValue=0, sValue=Percent, Image=Images[icon].ID)
    return

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
