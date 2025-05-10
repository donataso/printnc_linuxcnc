#!/usr/bin/env python3
#MIT License

# Copyright (c) 2023 Kenneth Thompson, https://github.com/KennethThompson

# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:

# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.

# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

from enum import StrEnum
from os import path
import time
from PyQt5.QtCore import QCoreApplication
#import debugpy
import linuxcnc

s = linuxcnc.stat()

import sys
import hal
_translate = QCoreApplication.translate
#from subprocess import PIPE, Popen
#import emccanon

# 5678 is the default attach port in the VS Code debug configurations. Unless a host and port are specified, host defaults to 127.0.0.1
#debugpy.listen(('0.0.0.0',5678))
#print("Waiting for debugger attach")
#debugpy.wait_for_client()
#debugpy.breakpoint()
#print('break on this line')

# Set up logging
from qtvcp import logger
from qtvcp.core import Info, Status, Qhal, Action

from PyQt5 import QtGui

log = logger.getLogger(__name__)

INFO = Info()
STATUS = Status()
QHAL = Qhal()
ACTION = Action()

# Set the log level for this module
log.setLevel(logger.DEBUG) # One of DEBUG, INFO, WARNING, ERROR, CRITICAL

key_index = 0
comp_input_index = 1
default_value = 2

class ToolEntry():
    def __init__(self, line:str) -> None:
        self.params, self.comment = line.split(';')
        self.params = self.params.split()
        self.id = self.params[0]
        self.pocket = self.params[1]

'''
    ToolTableReader bypasses a bug in LinuxCNC that prevents tool pockets from being identified.
'''
class ToolTableReader():
    def __init__(self, tooldb:str) -> None:
        self.tools = []
        self.tooldbpath = tooldb
        self.load_tool_db()

    def load_tool_db(self):
        self.tools.clear()
        file = open(self.tooldbpath, 'r')
        lns = file.readlines()
        for line in lns:
            self.tools.append(ToolEntry(line))

    def get_tool_pocket(self, toolid:int) -> int:
        for tool in self.tools:
            if tool.id == f'T{str(toolid)}':
                return int(tool.pocket[1:])
        return -1

    def get_tools(self) -> dict:
        ret = {}
        for tool in self.tools:
            ret[tool.id] = int(tool.pocket[1:])
        return ret


class AtcHalPin(StrEnum):
    SAFE_Z = 'safe_z'
    Z_IR_ENGAGE = 'z_ir_engage'
    NUM_POCKETS = 'num_pockets'
    POCKET_OFFSET = 'pocket_offset'
    FIRST_POCKET_X = 'first_pocket_x'
    FIRST_POCKET_Y = 'first_pocket_y'
    ENGAGE_Z =  'engage_z'
    ENGAGE_Z_DROP_OFFSET = 'engage_z_drop_offset'
    ALIGN_AXIS = 'align_axis'
    #ALIGN_DIR = 'align_dir'
    IR_HAL_DPIN = 'ir_hal_dpin'
    COVER_HAL_DPIN = 'cover_hal_dpin'
    DROP_RATE = 'drop_feed_rate'
    PICKUP_RATE = 'pickup_feed_rate'
    SPINDLE_SPEED_PICKUP = 'spindle_speed_pickup'
    SPINDLE_SPEED_DROP = 'spindle_speed_drop'
    X_MANUAL_CHANGE_POS = 'x_manual_change_pos'
    Y_MANUAL_CHANGE_POS = 'y_manual_change_pos'
    CURRENT_TOOL_POCKET = 'current_tool_pocket'
    #TOOL_INDEX = 'tool_'
    IR_ENABLED = 'ir_enabled'
    COVER_ENABLED = 'cover_enabled'
    DUST_COVER_STATE = 'dust_cover_state'
    def __str__(self) -> str:
        return self.value

class ConfigElement(StrEnum):
    ATC_SECTION = 'RAPID_ATC'
    VERSA_PROBE_SECTION = 'VERSA_PROBE_OPTIONS'
    NUM_POCKETS = 'num_pockets'
    POCKET_OFFSET = 'pocket_offset'
    FIRST_POCKET_X = 'first_pocket_x'
    FIRST_POCKET_Y = 'first_pocket_y'
    Z_ENGAGE = 'z_engage'
    Z_ENGAGE_DROP_OFFSET = 'z_engage_drop_offset'
    Z_IR_ENGAGE = 'z_ir_engage'
    COVER_HAL_DPIN = 'cover_hal_dpin'
    IR_HAL_DPIN = 'ir_hal_dpin'
    Z_SAFE_CLEARANCE = 'z_safe_clearance'
    X_MANUAL_CHANGE_POS = 'x_manual_change_pos'
    Y_MANUAL_CHANGE_POS = 'y_manual_change_pos'
    ALIGN_AXIS = 'align_axis'
    #ALIGN_DIR = 'align_dir'
    PICKUP_RATE = 'pickup_rate'
    DROP_RATE = 'drop_rate'
    SPINDLE_SPEED_PICKUP = 'spindle_speed_pickup'
    SPINDLE_SPEED_DROP = 'spindle_speed_drop'
    IR_ENABLED = 'ir_enabled'
    COVER_ENABLED = 'cover_enabled'
    VERSA_PROBE_SENSOR_HT = 'ps_probe_height'
    VERSA_BLOCK_HT = 'ps_block_height'

    def __str__(self) -> str:
        return self.value



###################################
# **** HANDLER CLASS SECTION **** #
###################################

class HandlerClass:
    #r = rapidChangeBase()

    ########################
    # **** INITIALIZE **** #
    ########################
    # widgets allows access to  widgets from the QtVCP files
    # at this point the widgets and hal pins are not instantiated
    def __init__(self, halcomp,widgets,paths):
        self.hal = halcomp
        self.w = widgets
        self.PATHS = paths
        self.iniFile = INFO.INI
        self.machineName = self.iniFile.find('EMC', 'MACHINE')
        self.probeName = self.iniFile.find('PROBE', 'USE_PROBE')
        self.c = hal.component('rapid_atc')
        self.configPath = paths.CONFIGPATH
        self.toolTablePath = path.join(self.configPath, 'tool.tbl')
        self.tooldb = ToolTableReader(tooldb=self.toolTablePath)
        self.currentTool = 0
        self.currentToolPocketNo = 0

        # Create HAL pins for monitoring tool change
        #self.hal.newpin("tool_change_active", hal.HAL_BIT, hal.HAL_OUT)
        #self.hal.newpin("tool_number", hal.HAL_S32, hal.HAL_OUT)
        #self.hal["tool_change_active"] = False
        #self.hal["tool_number"] = 0



    def onTextChanged(self, s:str):
        print(f'Text Changed: {s}')

    ##########################################
    # SPECIAL FUNCTIONS SECTION              #
    ##########################################

    # at this point:
    # the widgets are instantiated.
    # the HAL pins are built but HAL is not set ready
    # This is where you make HAL pins or initialize state of widgets etc
    def initialized__(self):
        log.debug('INIT qtvcp handler')
        if not self.w.MAIN.PREFS_:
            err = "CRITICAL - no preference file found, enable preferences in screenoptions widget"
            log.debug(err)
            print(err)
            return

        if self.w.MAIN.PREFS_:
            '''
            [ATC]
            NUM_POCKETS = 4
            FIRST_POCKET_X = 476.8
            FIRST_POCKET_Y = 1
            FIRST_POCKET_Z = 4.3
            DELTA_X = 52
            DELTA_Y = 0
            OFF_HEIGHT_Z = 35
            WAIT_SPINDLE = 2
            CHANGE_X = 200
            CHANGE_Y = 1
            CHANGE_Z = 167
            SPINDLE_SPEED = 800
            UNLOAD_ZSPEED = 2000
            LOAD_ZSPEED = 870
            '''

            # PIN definitions
            self.c.newpin(AtcHalPin.SAFE_Z, hal.HAL_FLOAT, hal.HAL_IN)
            self.c.newpin(AtcHalPin.Z_IR_ENGAGE, hal.HAL_FLOAT, hal.HAL_IN)
            self.c.newpin(AtcHalPin.NUM_POCKETS, hal.HAL_S32, hal.HAL_IN)
            self.c.newpin(AtcHalPin.POCKET_OFFSET, hal.HAL_FLOAT, hal.HAL_IN)
            self.c.newpin(AtcHalPin.FIRST_POCKET_X, hal.HAL_FLOAT, hal.HAL_IN)
            self.c.newpin(AtcHalPin.FIRST_POCKET_Y, hal.HAL_FLOAT, hal.HAL_IN)
            self.c.newpin(AtcHalPin.X_MANUAL_CHANGE_POS, hal.HAL_FLOAT, hal.HAL_IN)
            self.c.newpin(AtcHalPin.Y_MANUAL_CHANGE_POS, hal.HAL_FLOAT, hal.HAL_IN)
            self.c.newpin(AtcHalPin.ENGAGE_Z, hal.HAL_FLOAT, hal.HAL_IN)
            self.c.newpin(AtcHalPin.ENGAGE_Z_DROP_OFFSET, hal.HAL_FLOAT, hal.HAL_IN)
            self.c.newpin(AtcHalPin.ALIGN_AXIS, hal.HAL_BIT, hal.HAL_IN)
            #self.c.newpin(AtcHalPin.ALIGN_DIR, hal.HAL_S32, hal.HAL_IN)
            self.c.newpin(AtcHalPin.DROP_RATE, hal.HAL_S32, hal.HAL_IN)
            self.c.newpin(AtcHalPin.PICKUP_RATE, hal.HAL_S32, hal.HAL_IN)
            self.c.newpin(AtcHalPin.SPINDLE_SPEED_PICKUP, hal.HAL_S32, hal.HAL_IN)
            self.c.newpin(AtcHalPin.SPINDLE_SPEED_DROP, hal.HAL_S32, hal.HAL_IN)
            self.c.newpin(AtcHalPin.CURRENT_TOOL_POCKET, hal.HAL_S32, hal.HAL_IN)
            self.c.newpin(AtcHalPin.IR_ENABLED, hal.HAL_BIT, hal.HAL_IN)
            self.c.newpin(AtcHalPin.COVER_ENABLED, hal.HAL_BIT, hal.HAL_IN)
            self.c.newpin(AtcHalPin.IR_HAL_DPIN, hal.HAL_S32, hal.HAL_IN)
            self.c.newpin(AtcHalPin.COVER_HAL_DPIN, hal.HAL_S32, hal.HAL_OUT)
            self.c.newpin(AtcHalPin.DUST_COVER_STATE, hal.HAL_BIT, hal.HAL_OUT)

            # Wire periodic update function
            STATUS.connect('periodic', lambda w: self.updatePeriodic())
            STATUS.connect('general', self.dialog_return)

            #self.ok_pin = QHAL.newpin("oktest", QHAL.HAL_BIT, QHAL.HAL_IN)
            #self.ok_pin.value_changed.connect(lambda s: self.dialog_return(s))


            # UI elements
            self.w.btnSetXYPocketOne.clicked.connect( lambda: self.setXYPocketOne() )

            self.w.btnSetZEngage.clicked.connect(lambda: self.setZEngage() )

            self.w.btnSetZIREngage.clicked.connect(lambda: self.setZIREngage() )

            self.w.btnAdd.clicked.connect(lambda: (self.w.tooloffsetview.add_tool(),\
                                            self.w.tooloffsetview.repaint()))
            self.w.btnDelete.clicked.connect(lambda:(self.w.tooloffsetview.delete_tools(),\
                                                self.w.tooloffsetview.repaint()))
            #self.w.pbSafeZ.clicked.connect(
            #    lambda: self.executeProgram('o<_go_to_pos> call')
            #)
            #self.w.pbToolChangeTest.clicked.connect(
            #    lambda: self.executeProgram('o<_tool_change> call [5]')
            #)
            self.w.btnDropTool.clicked.connect(
                lambda: self.executeProgram(f'o<_drop_tool> call [{self.currentToolPocketNo}]')
            )

            self.w.btnPickupTool.clicked.connect(
                lambda: self.loadToolViaATC()
            )



            self.w.btnDustCoverToggle.clicked.connect(
                lambda: self.toggleDustCover()
            )


            self.w.btnM61.clicked.connect( lambda: self.loadToolViaM61() )

            self.w.btnM6tn.clicked.connect( lambda: self.loadToolViaM6tn() )

            '''
            future items, which may never be implemented
            '''
            #self.w.gbToolSetter.setVisible(False)
            #self.w.gbToolSetterTouch.setVisible(False)

            '''
                Removed columns from tooloffsetview that are extraneous/unused by ATC Logic
            '''
            # https://linuxcnc.org/docs/2.9/html/gui/qtvcp-widgets.html#sub:qtvcp:widgets:tooloffsetview
           # self.w.tooloffsetview.hideColumn(2)
            self.w.tooloffsetview.hideColumn(3)
            self.w.tooloffsetview.hideColumn(4)
            self.w.tooloffsetview.hideColumn(5)
            self.w.tooloffsetview.hideColumn(6)
            self.w.tooloffsetview.hideColumn(7)
            self.w.tooloffsetview.hideColumn(8)
            self.w.tooloffsetview.hideColumn(9)
            self.w.tooloffsetview.hideColumn(10)
            self.w.tooloffsetview.hideColumn(11)

            '''
                num_pockets : Number of tool pocketsi available for tool changing
            '''
            num_pockets = self.w.MAIN.PREFS_.getpref(ConfigElement.NUM_POCKETS, 4, int, ConfigElement.ATC_SECTION)
            log.debug(f'{ConfigElement.NUM_POCKETS} = {num_pockets}')
            self.c[AtcHalPin.NUM_POCKETS] = int(num_pockets)
            self.numPocketInput = self.w.leNoPockets
            self.numPocketInput.setText(str(num_pockets))
            self.numPocketInput.editingFinished.connect(
                lambda: (self.w.MAIN.PREFS_.putpref(ConfigElement.NUM_POCKETS, int(self.numPocketInput.text()), int, ConfigElement.ATC_SECTION),
                        log.debug(f'SETTING {ConfigElement.NUM_POCKETS} = {self.numPocketInput.text()} in preferences'),
                         self.setPinValue( pinName = AtcHalPin.NUM_POCKETS, pinVal = int(self.numPocketInput.text()))))

            '''
                pocket_offset : Offset between tool pockets
            '''
            pocket_offset = self.w.MAIN.PREFS_.getpref(ConfigElement.POCKET_OFFSET, "45", str, ConfigElement.ATC_SECTION)
            log.debug(f'{ConfigElement.POCKET_OFFSET} = {pocket_offset}')
            self.c[AtcHalPin.POCKET_OFFSET] = float(pocket_offset)
            self.pocketOffsetInput = self.w.lePocketOffset

            self.pocketOffsetInput.setValidator(
            QtGui.QDoubleValidator(
                -5000, # bottom
                5000, # top
                3, # decimals
                notation=QtGui.QDoubleValidator.StandardNotation
            ))
            self.pocketOffsetInput.setText(str(pocket_offset))
            self.pocketOffsetInput.editingFinished.connect(
                lambda: (self.w.MAIN.PREFS_.putpref(ConfigElement.POCKET_OFFSET, self.pocketOffsetInput.text(), str, ConfigElement.ATC_SECTION),
                         log.debug(f'SETTING {ConfigElement.POCKET_OFFSET} = {self.pocketOffsetInput.text()} in preferences'),
                         self.setPinValue( pinName = AtcHalPin.POCKET_OFFSET, pinVal = float(self.pocketOffsetInput.text()))))


            '''
                first_pocket_x : X pos of first pocket
            '''
            first_pocket_x = self.w.MAIN.PREFS_.getpref(ConfigElement.FIRST_POCKET_X, "0", str, ConfigElement.ATC_SECTION)
            log.debug(f'{ConfigElement.FIRST_POCKET_X} = {first_pocket_x}')
            self.c[AtcHalPin.FIRST_POCKET_X] = float(first_pocket_x)
            self.firstPocketXInput = self.w.leLocPocketOneX
            self.firstPocketXInput.setValidator(
            QtGui.QDoubleValidator(
                -5000, # bottom
                5000, # top
                3, # decimals
                notation=QtGui.QDoubleValidator.StandardNotation
            ))
            self.firstPocketXInput.setText(str(first_pocket_x))
            self.firstPocketXInput.editingFinished.connect(
                    lambda: (self.w.MAIN.PREFS_.putpref(ConfigElement.FIRST_POCKET_X, self.firstPocketXInput.text(), str, ConfigElement.ATC_SECTION),
                    log.debug(f'SETTING {ConfigElement.FIRST_POCKET_X} = {self.firstPocketXInput.text()} in preferences'),
                    self.setPinValue( pinName = AtcHalPin.FIRST_POCKET_X, pinVal = float(self.firstPocketXInput.text()))))
            '''
                first_pocket_y : Y pos of first pocket
            '''
            first_pocket_y = self.w.MAIN.PREFS_.getpref(ConfigElement.FIRST_POCKET_Y, "0", str, ConfigElement.ATC_SECTION)
            log.debug(f'{ConfigElement.FIRST_POCKET_Y} = {first_pocket_y}')
            self.c[AtcHalPin.FIRST_POCKET_Y] = float(first_pocket_y)
            self.firstPocketYInput = self.w.leLocPocketOneY
            self.firstPocketYInput.setValidator(
            QtGui.QDoubleValidator(
                -5000, # bottom
                5000, # top
                3, # decimals
                notation=QtGui.QDoubleValidator.StandardNotation
            ))
            self.firstPocketYInput.setText(str(first_pocket_y))
            self.firstPocketYInput.editingFinished.connect(
                lambda: (self.w.MAIN.PREFS_.putpref(ConfigElement.FIRST_POCKET_Y, self.firstPocketYInput.text(), str, ConfigElement.ATC_SECTION),
                log.debug(f'SETTING {ConfigElement.FIRST_POCKET_Y} = {self.firstPocketYInput.text()} in preferences'),
                self.setPinValue( pinName = AtcHalPin.FIRST_POCKET_Y, pinVal = float(self.firstPocketYInput.text()))))
            '''
                z_engage : Z engage position
            '''
            z_engage = self.w.MAIN.PREFS_.getpref(ConfigElement.Z_ENGAGE, "0", str, ConfigElement.ATC_SECTION)
            log.debug(f'{ConfigElement.Z_ENGAGE} = {z_engage}')
            self.c[AtcHalPin.ENGAGE_Z] = float(z_engage)
            self.zEngageInput = self.w.leLocZEngage
            self.zEngageInput.setValidator(
            QtGui.QDoubleValidator(
                -5000, # bottom
                5000, # top
                3, # decimals
                notation=QtGui.QDoubleValidator.StandardNotation
            ))
            self.zEngageInput.setText(str(z_engage))
            self.zEngageInput.editingFinished.connect(
                lambda: (self.w.MAIN.PREFS_.putpref(ConfigElement.Z_ENGAGE, self.zEngageInput.text(), str, ConfigElement.ATC_SECTION),
                log.debug(f'SETTING {ConfigElement.Z_ENGAGE} = {self.zEngageInput.text()} in preferences'),
                self.setPinValue( pinName = AtcHalPin.ENGAGE_Z, pinVal = float(self.zEngageInput.text()))))
            '''
                z_engage_drop_offset : Z engage offset position for drops
            '''
            z_engage_drop_offset = self.w.MAIN.PREFS_.getpref(ConfigElement.Z_ENGAGE_DROP_OFFSET, "0", str, ConfigElement.ATC_SECTION)
            log.debug(f'{ConfigElement.Z_ENGAGE_DROP_OFFSET} = {z_engage_drop_offset}')
            self.c[AtcHalPin.ENGAGE_Z_DROP_OFFSET] = float(z_engage)
            self.zEngageDropOffsetInput = self.w.leZToolDropOffset
            self.zEngageDropOffsetInput.setValidator(
            QtGui.QDoubleValidator(
                -5000, # bottom
                5000, # top
                3, # decimals
                notation=QtGui.QDoubleValidator.StandardNotation
            ))
            self.zEngageDropOffsetInput.setText(str(z_engage_drop_offset))
            self.zEngageDropOffsetInput.editingFinished.connect(
                lambda: (self.w.MAIN.PREFS_.putpref(ConfigElement.Z_ENGAGE, self.zEngageDropOffsetInput.text(), str, ConfigElement.ATC_SECTION),
                log.debug(f'SETTING {ConfigElement.Z_ENGAGE_DROP_OFFSET} = {self.zEngageDropOffsetInput.text()} in preferences'),
                self.setPinValue( pinName = AtcHalPin.ENGAGE_Z_DROP_OFFSET, pinVal = float(self.zEngageDropOffsetInput.text()))))


            '''
                z_ir_engage : Z IR engage position
            '''
            z_ir_engage = self.w.MAIN.PREFS_.getpref(ConfigElement.Z_IR_ENGAGE, "0", str, ConfigElement.ATC_SECTION)
            log.debug(f'{ConfigElement.Z_IR_ENGAGE} = {z_ir_engage}')
            self.c[AtcHalPin.Z_IR_ENGAGE] = float(z_ir_engage)
            self.zEngageIRInput = self.w.leLocZIREngage
            self.zEngageIRInput.setValidator(
            QtGui.QDoubleValidator(
                -5000, # bottom
                5000, # top
                3, # decimals
                notation=QtGui.QDoubleValidator.StandardNotation
            ))
            self.zEngageIRInput.setText(str(z_ir_engage))
            self.zEngageIRInput.editingFinished.connect(
                lambda: (self.w.MAIN.PREFS_.putpref(ConfigElement.Z_IR_ENGAGE, self.zEngageIRInput.text(), str, ConfigElement.ATC_SECTION),
                log.debug(f'SETTING {ConfigElement.Z_IR_ENGAGE} = {self.zEngageIRInput.text()} in preferences'),
                self.setPinValue( pinName = AtcHalPin.Z_IR_ENGAGE, pinVal = float(self.zEngageIRInput.text()))))
            '''
                z_safe_clearance
            '''
            z_safe_clearance = self.w.MAIN.PREFS_.getpref(ConfigElement.Z_SAFE_CLEARANCE, "0", str, ConfigElement.ATC_SECTION)
            log.debug(f'{ConfigElement.Z_SAFE_CLEARANCE} = {z_safe_clearance}')
            self.c[AtcHalPin.SAFE_Z] = float(z_safe_clearance)
            self.zSafeClearanceInput = self.w.leZSafeClearance
            self.zSafeClearanceInput.setValidator(
            QtGui.QDoubleValidator(
                -5000, # bottom
                5000, # top
                3, # decimals
                notation=QtGui.QDoubleValidator.StandardNotation
            ))
            self.zSafeClearanceInput.setText(z_safe_clearance)
            self.zSafeClearanceInput.editingFinished.connect(
                lambda: (self.w.MAIN.PREFS_.putpref(ConfigElement.Z_SAFE_CLEARANCE, self.zSafeClearanceInput.text(), str, ConfigElement.ATC_SECTION),
                log.debug(f'SETTING {ConfigElement.Z_SAFE_CLEARANCE} = {self.zSafeClearanceInput.text()} in preferences'),
                self.setPinValue( pinName = AtcHalPin.SAFE_Z, pinVal = float(self.zSafeClearanceInput.text()))))
            '''
                cover_hal_dpin
            '''
            cover_hal_dpin = self.w.MAIN.PREFS_.getpref(ConfigElement.COVER_HAL_DPIN, 2, int, ConfigElement.ATC_SECTION)
            log.debug(f'{ConfigElement.COVER_HAL_DPIN} = {cover_hal_dpin}')
            self.c[AtcHalPin.COVER_HAL_DPIN] = int(cover_hal_dpin)
            self.coverDPinInput = self.w.leCoverDPinInput
            self.coverDPinInput.setText(str(cover_hal_dpin))
            self.coverDPinInput.editingFinished.connect(
                lambda: (self.w.MAIN.PREFS_.putpref(ConfigElement.COVER_HAL_DPIN, self.coverDPinInput.text(), str, ConfigElement.ATC_SECTION),
                log.debug(f'SETTING {ConfigElement.COVER_HAL_DPIN} = {self.coverDPinInput.text()} in preferences'),
                self.setPinValue( pinName = AtcHalPin.COVER_HAL_DPIN, pinVal = int(self.coverDPinInput.text()))))
            '''
                ir_hal_dpin
            '''
            ir_hal_dpin = self.w.MAIN.PREFS_.getpref(ConfigElement.IR_HAL_DPIN, 3, int, ConfigElement.ATC_SECTION)
            log.debug(f'{ConfigElement.IR_HAL_DPIN} = {ir_hal_dpin}')
            self.c[AtcHalPin.IR_HAL_DPIN] = int(ir_hal_dpin)
            self.irDPinInput = self.w.leIRDPinInput
            self.irDPinInput.setText(str(ir_hal_dpin))
            self.irDPinInput.editingFinished.connect(
                lambda: (self.w.MAIN.PREFS_.putpref(ConfigElement.IR_HAL_DPIN, self.irDPinInput.text(), str, ConfigElement.ATC_SECTION),
                log.debug(f'SETTING {ConfigElement.IR_HAL_DPIN} = {self.irDPinInput.text()} in preferences'),
                self.setPinValue( pinName = AtcHalPin.IR_HAL_DPIN, pinVal = int(self.irDPinInput.text()))))
            '''
                x_manual_change_pos
            '''
            x_manual_change_pos = self.w.MAIN.PREFS_.getpref(ConfigElement.X_MANUAL_CHANGE_POS, "0", str, ConfigElement.ATC_SECTION)
            log.debug(f'{ConfigElement.X_MANUAL_CHANGE_POS} = {x_manual_change_pos}')
            self.c[AtcHalPin.X_MANUAL_CHANGE_POS] = float(x_manual_change_pos)
            self.xManualChangePosInput = self.w.leXManualChangePos
            self.xManualChangePosInput.setValidator(
            QtGui.QDoubleValidator(
                -5000, # bottom
                5000, # top
                3, # decimals
                notation=QtGui.QDoubleValidator.StandardNotation
            ))
            self.xManualChangePosInput.setText(str(x_manual_change_pos))
            self.xManualChangePosInput.editingFinished.connect(
                lambda: (self.w.MAIN.PREFS_.putpref(ConfigElement.X_MANUAL_CHANGE_POS, self.xManualChangePosInput.text(), str, ConfigElement.ATC_SECTION),
                log.debug(f'SETTING {ConfigElement.X_MANUAL_CHANGE_POS} = {self.xManualChangePosInput.text()} in preferences'),
                self.setPinValue( pinName = AtcHalPin.X_MANUAL_CHANGE_POS, pinVal = float(self.xManualChangePosInput.text())
                )
            ))
            '''
                y_manual_change_pos
            '''
            y_manual_change_pos = self.w.MAIN.PREFS_.getpref(ConfigElement.Y_MANUAL_CHANGE_POS, "0", str, ConfigElement.ATC_SECTION)
            log.debug(f'{ConfigElement.Y_MANUAL_CHANGE_POS} = {y_manual_change_pos}')
            self.c[AtcHalPin.Y_MANUAL_CHANGE_POS] = float(y_manual_change_pos)
            self.yManualChangePosInput = self.w.leYManualChangePos
            self.yManualChangePosInput.setValidator(
            QtGui.QDoubleValidator(
                -5000, # bottom
                5000, # top
                3, # decimals
                notation=QtGui.QDoubleValidator.StandardNotation
            ))
            self.yManualChangePosInput.setText(str(y_manual_change_pos))
            self.yManualChangePosInput.editingFinished.connect(
                lambda: (self.w.MAIN.PREFS_.putpref(ConfigElement.Y_MANUAL_CHANGE_POS, self.yManualChangePosInput.text(), int, ConfigElement.ATC_SECTION),
                log.debug(f'SETTING {ConfigElement.Y_MANUAL_CHANGE_POS} = {self.yManualChangePosInput.text()} in preferences'),
                self.setPinValue( pinName = AtcHalPin.Y_MANUAL_CHANGE_POS, pinVal = float(self.yManualChangePosInput.text())
                )
            ))
            '''
                align_axis
            '''
            align_axis = self.w.MAIN.PREFS_.getpref(ConfigElement.ALIGN_AXIS, 'X', str, ConfigElement.ATC_SECTION)
            log.debug(f'{ConfigElement.ALIGN_AXIS} = {align_axis}')
            if align_axis.lower() == 'x':
                self.w.pbXAxis.setChecked(True)
                self.w.pbYAxis.setChecked(False)
                self.c[AtcHalPin.ALIGN_AXIS] = 0
            else:
                self.w.pbYAxis.setChecked(True)
                self.w.pbXAxis.setChecked(False)
                self.c[AtcHalPin.ALIGN_AXIS] = 1

            self.w.pbXAxis.clicked.connect(
                lambda: (self.w.MAIN.PREFS_.putpref(ConfigElement.ALIGN_AXIS, 'X', str, ConfigElement.ATC_SECTION),
                    self.w.pbXAxis.setEnabled(False),
                    self.w.pbYAxis.setEnabled(True),
                    self.w.pbYAxis.setChecked(False),
                    self.setPinValue( pinName = AtcHalPin.ALIGN_AXIS, pinVal = 0),
                    log.debug(f'SETTING {ConfigElement.ALIGN_AXIS} = X in preferences'))
                )
            self.w.pbYAxis.clicked.connect(
                lambda: (self.w.MAIN.PREFS_.putpref(ConfigElement.ALIGN_AXIS, 'Y', str, ConfigElement.ATC_SECTION),
                    self.w.pbYAxis.setEnabled(False),
                    self.w.pbXAxis.setEnabled(True),
                    self.w.pbXAxis.setChecked(False),
                    self.setPinValue( pinName = AtcHalPin.ALIGN_AXIS, pinVal = 1),
                    log.debug(f'SETTING {ConfigElement.ALIGN_AXIS} = Y in preferences'))
                )
            '''
                align_dir

            align_dir = self.w.MAIN.PREFS_.getpref(ConfigElement.ALIGN_DIR, 'POS', str, ConfigElement.ATC_SECTION)
            log.debug(f'{ConfigElement.ALIGN_DIR} = {align_dir}')
            if align_dir.lower() == 'pos':
                self.w.pbDirectionPos.setChecked(True)
                self.w.pbDirectionNeg.setChecked(False)
                self.setPinValue( pinName = AtcHalPin.ALIGN_DIR, pinVal = 1)
            else:
                self.w.pbDirectionNeg.setChecked(True)
                self.w.pbDirectionPos.setChecked(False)
                self.setPinValue( pinName = AtcHalPin.ALIGN_DIR, pinVal = -1)

            self.w.pbDirectionPos.clicked.connect(
                lambda: (self.w.MAIN.PREFS_.putpref(ConfigElement.ALIGN_DIR, 'POS', str, ConfigElement.ATC_SECTION),
                    self.w.pbDirectionPos.setEnabled(False),
                    self.w.pbDirectionNeg.setEnabled(True),
                    self.w.pbDirectionNeg.setChecked(False),
                    self.setPinValue( pinName = AtcHalPin.ALIGN_DIR, pinVal = 1),
                    log.debug(f'SETTING {ConfigElement.ALIGN_DIR} = POS in preferences'))
                )
            self.w.pbDirectionNeg.clicked.connect(
                lambda: (self.w.MAIN.PREFS_.putpref(ConfigElement.ALIGN_DIR, 'NEG', str, ConfigElement.ATC_SECTION),
                    self.w.pbDirectionNeg.setEnabled(False),
                    self.w.pbDirectionPos.setEnabled(True),
                    self.w.pbDirectionPos.setChecked(False),
                    self.setPinValue( pinName = AtcHalPin.ALIGN_DIR, pinVal = -1),
                    log.debug(f'SETTING {ConfigElement.ALIGN_DIR} = NEG in preferences'))
                )
            '''
            '''
                engage_feed_rate

            engage_feed_rate = self.w.MAIN.PREFS_.getpref(ConfigElement.ENGAGE_FEED_RATE, 1800, int, ConfigElement.ATC_SECTION)
            log.debug(f'{ConfigElement.ENGAGE_FEED_RATE} = {engage_feed_rate}')
            self.engageFeedRateInput = self.w.leSFEngageFeedRate
            self.engageFeedRateInput.setText(str(engage_feed_rate))
            self.engageFeedRateInput.editingFinished.connect(
                lambda: (self.w.MAIN.PREFS_.putpref(ConfigElement.ENGAGE_FEED_RATE, int(self.engageFeedRateInput.text()), int, ConfigElement.ATC_SECTION),
                self.setPinValue( pinName = AtcHalPin.ENGAGE_FEED_RATE, pinVal = int(self.engageFeedRateInput.text())),
                log.debug(f'SETTING {ConfigElement.ENGAGE_FEED_RATE} = {self.engageFeedRateInput.text()} in preferences'))
                )

            self.engageFeedRateInput.setValidator(
            QtGui.QDoubleValidator(
                0, # bottom
                5000, # top
                0, # decimals
                notation=QtGui.QDoubleValidator.StandardNotation
            ))
            '''
            '''
                pickup_rate
            '''
            pickup_rate = self.w.MAIN.PREFS_.getpref(ConfigElement.PICKUP_RATE, 1800, int, ConfigElement.ATC_SECTION)
            log.debug(f'{ConfigElement.PICKUP_RATE} = {pickup_rate}')
            self.pickupRateInput = self.w.leSFPickUpRate
            self.pickupRateInput.setText(str(pickup_rate))
            self.c[AtcHalPin.PICKUP_RATE] = int(pickup_rate)
            self.pickupRateInput.editingFinished.connect(
                lambda: (self.w.MAIN.PREFS_.putpref(ConfigElement.PICKUP_RATE, int(self.pickupRateInput.text()), int, ConfigElement.ATC_SECTION),
                self.setPinValue( pinName = AtcHalPin.PICKUP_RATE, pinVal = int(self.pickupRateInput.text())),
                log.debug(f'SETTING {ConfigElement.PICKUP_RATE} = {self.pickupRateInput.text()} in preferences'))
                )

            self.pickupRateInput.setValidator(
            QtGui.QDoubleValidator(
                0, # bottom
                5000, # top
                0, # decimals
                notation=QtGui.QDoubleValidator.StandardNotation
            ))
            '''
                drop_rate
            '''
            drop_rate = self.w.MAIN.PREFS_.getpref(ConfigElement.DROP_RATE, 1800, int, ConfigElement.ATC_SECTION)
            log.debug(f'{ConfigElement.DROP_RATE} = {drop_rate}')
            self.dropRateInput = self.w.leSFDropRate
            self.dropRateInput.setText(str(drop_rate))
            self.c[AtcHalPin.DROP_RATE] = int(drop_rate)
            self.dropRateInput.editingFinished.connect(
                lambda: (self.w.MAIN.PREFS_.putpref(ConfigElement.DROP_RATE, int(self.dropRateInput.text()), int, ConfigElement.ATC_SECTION),
                self.setPinValue( pinName = AtcHalPin.DROP_RATE, pinVal = int(self.dropRateInput.text())),
                log.debug(f'SETTING {ConfigElement.DROP_RATE} = {self.dropRateInput.text()} in preferences')))

            self.dropRateInput.setValidator(
            QtGui.QDoubleValidator(
                0, # bottom
                5000, # top
                0, # decimals
                notation=QtGui.QDoubleValidator.StandardNotation
            ))
            '''
                spindle_speed_pickup
            '''
            spindle_speed_pickup = self.w.MAIN.PREFS_.getpref(ConfigElement.SPINDLE_SPEED_PICKUP, 1500, int, ConfigElement.ATC_SECTION)
            log.debug(f'{ConfigElement.SPINDLE_SPEED_PICKUP} = {spindle_speed_pickup}')
            self.spindleSpeedInput = self.w.leSpindleSpeedPickup
            self.spindleSpeedInput.setText(str(spindle_speed_pickup))
            self.c[AtcHalPin.SPINDLE_SPEED_PICKUP] = int(spindle_speed_pickup)
            self.spindleSpeedInput.editingFinished.connect(
                lambda: (self.w.MAIN.PREFS_.putpref(ConfigElement.SPINDLE_SPEED_PICKUP, int(self.spindleSpeedInput.text()), int, ConfigElement.ATC_SECTION),
                self.setPinValue( pinName = AtcHalPin.SPINDLE_SPEED_PICKUP, pinVal = int(self.spindleSpeedInput.text())),
                log.debug(f'SETTING {ConfigElement.SPINDLE_SPEED_PICKUP} = {self.spindleSpeedInput.text()} in preferences'))
                )
            self.spindleSpeedInput.setValidator(
            QtGui.QDoubleValidator(
                0, # bottom
                5000, # top
                0, # decimals
                notation=QtGui.QDoubleValidator.StandardNotation
            ))
            '''
                spindle speed drop
            '''
            spindle_speed_drop = self.w.MAIN.PREFS_.getpref(ConfigElement.SPINDLE_SPEED_DROP, 1500, int, ConfigElement.ATC_SECTION)
            log.debug(f'{ConfigElement.SPINDLE_SPEED_DROP} = {spindle_speed_drop}')
            self.spindleSpeedInputDrop = self.w.leSpindleSpeedDrop
            self.spindleSpeedInputDrop.setText(str(spindle_speed_drop))
            self.c[AtcHalPin.SPINDLE_SPEED_DROP] = int(spindle_speed_drop)
            self.spindleSpeedInputDrop.editingFinished.connect(
                lambda: (self.w.MAIN.PREFS_.putpref(ConfigElement.SPINDLE_SPEED_DROP, int(self.spindleSpeedInputDrop.text()), int, ConfigElement.ATC_SECTION),
                self.setPinValue( pinName = AtcHalPin.SPINDLE_SPEED_DROP, pinVal = int(self.spindleSpeedInputDrop.text())),
                log.debug(f'SETTING {ConfigElement.SPINDLE_SPEED_DROP} = {self.spindleSpeedInputDrop.text()} in preferences'))
                )
            self.spindleSpeedInputDrop.setValidator(
            QtGui.QDoubleValidator(
                0, # bottom
                5000, # top
                0, # decimals
                notation=QtGui.QDoubleValidator.StandardNotation
            ))
            '''
                ir_enabled
            '''
            ir_enabled = self.w.MAIN.PREFS_.getpref(ConfigElement.IR_ENABLED, True, bool, ConfigElement.ATC_SECTION)
            log.debug(f'{ConfigElement.IR_ENABLED} = {ir_enabled}')
            self.irEnabledInput = self.w.btn_ir_enabled
            self.irEnabledInput.setChecked(ir_enabled)
            self.setIREnabled(ir_enabled)
            self.w.btn_ir_enabled.clicked.connect(
                lambda: ( self.setIREnabled(self.w.btn_ir_enabled.isChecked()))
            )


            cover_enabled = self.w.MAIN.PREFS_.getpref(ConfigElement.COVER_ENABLED, True, bool, ConfigElement.ATC_SECTION)
            log.debug(f'{ConfigElement.COVER_ENABLED} = {cover_enabled}')
            self.coverEnabledInput = self.w.btnCoverEnabled
            self.coverEnabledInput.setChecked(cover_enabled)
            self.setCoverEnabled(cover_enabled)
            self.w.btnCoverEnabled.clicked.connect(
                lambda: ( self.setCoverEnabled(self.w.btnCoverEnabled.isChecked()))
            )



            if self.probeName is not None and self.probeName.lower() == 'versaprobe':
                self.w.gbVersaProbe.setVisible(True)
                #align_axis = self.w.MAIN.PREFS_.getpref(ConfigElement.ALIGN_AXIS, 'X', str, ConfigElement.ATC_SECTION)
                probe_ht = self.w.MAIN.PREFS_.getpref(ConfigElement.VERSA_PROBE_SENSOR_HT, "0", str, ConfigElement.VERSA_PROBE_SECTION)#QHAL.getvalue('qtversaprobe.probeheight')
                block_ht = self.w.MAIN.PREFS_.getpref(ConfigElement.VERSA_BLOCK_HT, "0", str, ConfigElement.VERSA_PROBE_SECTION)#QHAL.getvalue('qtversaprobe.blockheight')
                log.debug(f'probe_ht = {probe_ht}')
                log.debug(f'block_ht = {block_ht}')
                self.probeHTInput = self.w.leSensorHT
                self.probeHTInput.setText(probe_ht)
                self.probeHTInput.setValidator(
                QtGui.QDoubleValidator(
                    -5000, # bottom
                    5000, # top
                    3, # decimals
                    notation=QtGui.QDoubleValidator.StandardNotation
                ))

                self.blockHTInput = self.w.leBlockHT
                self.blockHTInput.setText(block_ht)
                self.blockHTInput.setReadOnly(True)
                self.blockHTInput.setValidator(
                QtGui.QDoubleValidator(
                    -5000, # bottom
                    5000, # top
                    3, # decimals
                    notation=QtGui.QDoubleValidator.StandardNotation
                ))



            '''
            tool_dict = self.tooldb.get_tools()
            for k, v in tool_dict.items():
                pin_name = f'{AtcHalPin.TOOL_INDEX}{k}'
                #if pin_name not in self.c.getpins():
                self.c.newpin(pin_name.lower(), hal.HAL_FLOAT, hal.HAL_IN)
                self.setPinValue(pinName=pin_name.lower(), pinVal=v)

            for x in range(len(tool_dict)+1, 25):
                pin_name = f'{AtcHalPin.TOOL_INDEX}T{x}'
                self.c.newpin(pin_name.lower(), hal.HAL_FLOAT, hal.HAL_IN)
            '''
            #error_pin = Popen(
            #    "halcmd getp gmoccapy.error ", shell=True, stdout=PIPE
            #).stdout.read()


            self.c.ready()

            #self.w.web_view.page().urlChanged.connect(self.onLoadFinished)

            # Register a periodic check for the tool change state
            #STATUS.connect('periodic', self.check_tool_change_state)

    #######################
    # CALLBACKS FROM FORM #
    #######################
    def executeProgram(self, s:str):
        command = linuxcnc.command()
        command.mode(linuxcnc.MODE_MDI)
        command.wait_complete()
        command.mdi(s)
        command.wait_complete()


    def ok_for_mdi(self):
        s.poll()
        return not s.estop and s.enabled and (s.homed.count(1) == s.joints) and (s.interp_state == linuxcnc.INTERP_IDLE)

    def setPinValue(self, pinName:str, pinVal):
        self.c[pinName] = pinVal

    def setIREnabled(self, b:bool):
        if b == True:
            self.setPinValue(pinName=AtcHalPin.IR_ENABLED, pinVal=1)
        else:
            self.setPinValue(pinName=AtcHalPin.IR_ENABLED, pinVal=0)
        self.w.MAIN.PREFS_.putpref(ConfigElement.IR_ENABLED, b, bool, ConfigElement.ATC_SECTION)
        self.w.btn_ir_enabled.setChecked(b)

    def setCoverEnabled(self, b:bool):
        if b == True:
            self.setPinValue(pinName=AtcHalPin.COVER_ENABLED, pinVal=1)
        else:
            self.setPinValue(pinName=AtcHalPin.COVER_ENABLED, pinVal=0)
        self.w.MAIN.PREFS_.putpref(ConfigElement.COVER_ENABLED, b, bool, ConfigElement.ATC_SECTION)
        self.w.btnCoverEnabled.setChecked(b)

        #info = "I LIKE CHEEEEEEZE!"
        #mess = {'NAME':'MESSAGE', 'TITLE':'SOME TITLE', 'ICON':'WARNING', 'ID':'__test1__', 'MESSAGE':'OVERWRITE FILE?', 'MORE':info, 'TYPE':'YESNO','NONBLOCKING':True}
        #ACTION.CALL_DIALOG(mess)

    def toggleDustCover(self):
        #b = self.c[AtcHalPin.DUST_COVER_STATE]
        cover_state = QHAL.getvalue(f'motion.digital-out-0{self.coverDPinInput.text()}')
        #self.w.ledIRTrigger.currentState = bool(ir_stat)
        if cover_state == False:
            self.executeProgram('o<_dust_cover_op> call [1]')
        else:
            self.executeProgram('o<_dust_cover_op> call [0]')

    def dialog_return(self, w, message):
        rtn = message.get('RETURN')
        name = message.get('NAME')
        tool_loaded_code = bool(message.get('ID') == '_toolloaded_')
        print(f'message = {message}')

        if tool_loaded_code and rtn == True:
            print(f'tool_loaded_code = {tool_loaded_code}')
            print(f'rtn = {rtn}')
            self.loadToolViaM61()
            t = self.getSelectedToolFromTable()
            print(f't = {t}')
            ACTION.CALL_MDI_WAIT( f"M6 T{t[0]}" )
            time.sleep(1)
            self.executeProgram(f'o<_auto_probe_tool> call [{t[0]}] [{t[0]}] [{self.c[AtcHalPin.CURRENT_TOOL_POCKET]}] [{self.c[AtcHalPin.CURRENT_TOOL_POCKET]}]')




    def toggleAllHomed(self, w, data):
        print(f'toggleAllHomed = {data}')
        pass

    def updatePeriodic(self):
        try:
            homed = QHAL.getvalue('motion.is-all-homed')
            machine_on = QHAL.getvalue('halui.machine.is-on')
            #if self.irEnabledInput:
            ir_stat = QHAL.getvalue(f'motion.digital-in-0{int(self.irDPinInput.text())}')

            if self.probeName is not None and self.probeName.lower() == 'versaprobe':
                block_ht = QHAL.getvalue(f'qtversaprobe.blockheight')
                self.blockHTInput.setText(str(block_ht))
                probe_ht = QHAL.getvalue(f'qtversaprobe.probeheight')
                self.probeHTInput.setText(str(probe_ht))

            self.w.gbToolActions.setEnabled((homed & machine_on))
            self.w.gbMacros.setEnabled((homed & machine_on))
            self.w.lblMachineOnNotice.setVisible(not (homed & machine_on))

            #s = self.getCurrentStat()
            #self.s.poll()
            #s.poll()
            if not self.ok_for_mdi():
                return
            if s.tool_in_spindle == 0 and self.currentTool != 0:
                self.w.lblToolNo.setText('EMPTY')
                self.w.lblToolNoL.setText('EMPTY')
                self.currentTool = 0
                self.currentToolPocketNo = 0
                self.setPinValue(pinName=AtcHalPin.CURRENT_TOOL_POCKET, pinVal=0)
                # Write directly to motion.analog-out-00 for G-code to read
                #hal.set_p("motion.analog-out-00", f'{0}')
                #if homed and machine_on:
                ACTION.CALL_MDI_WAIT( f"M68 E0 Q0" )
                self.w.lblToolPocket.setText('NONE')
                self.w.btnDropTool.setEnabled(False)
                self.w.btnPickupTool.setEnabled(True)
            else:
                if s.interp_state == linuxcnc.INTERP_IDLE and s.tool_in_spindle != self.currentTool and machine_on and homed:
                    print(f'Tool change detected. Current tool = {self.currentTool}, new tool = {s.tool_in_spindle}')
                    self.currentTool = s.tool_in_spindle
                    self.w.lblToolNo.setText(str(s.tool_in_spindle))
                    self.w.lblToolNoL.setText(str(s.tool_in_spindle))
                    self.tooldb.load_tool_db() # force a reload to catch any changes

                    p = self.getToolPocketByIndex(s.tool_in_spindle)
                    print(f'Tool lookup returned pocket = {p} for tool {s.tool_in_spindle}')
                    self.currentToolPocketNo = p

                    #if self.c[AtcHalPin.CURRENT_TOOL_POCKET] != p:
                    #if homed and machine_on:
                        #self.setPinValue(pinName=AtcHalPin.CURRENT_TOOL_POCKET, pinVal=p)
                        # Write directly to motion.analog-out-00 for G-code to read
                    ACTION.CALL_MDI_WAIT( f"M68 E0 Q{p}" )
                    self.w.lblToolPocket.setText(str(p))
                    self.w.btnDropTool.setEnabled(True)
                    self.w.btnPickupTool.setEnabled(False)
        except Exception as ex:
            print(ex)
            pass

    '''

        def check_tool_change_state(self, w):
        try:
            # Check if the tool change dialog is active
            # Use the correct HAL pin name for QtDragon_hd
            dialog_active = QHAL.getvalue("qtdragon.oktest-waiting")
            if dialog_active and not self.hal["tool_change_active"]:
                # Tool change dialog just became active
                self.hal["tool_change_active"] = True
                self.hal["tool_number"] = self.currentTool  # Set the current tool number
                log.info(f"Tool change dialog activated for tool: {self.currentTool}")

                # Update any UI elements to reflect the tool change state
                if hasattr(self.w, "lbl_tool_change_status"):
                    self.w.lbl_tool_change_status.setText(f"Changing to tool #{self.currentTool}")

            elif not dialog_active and self.hal["tool_change_active"]:
                # Tool change dialog just closed
                self.hal["tool_change_active"] = False
                log.info("Tool change completed")

                # Update any UI elements to reflect the completion
                if hasattr(self.w, "lbl_tool_change_status"):
                    self.w.lbl_tool_change_status.setText("Tool change completed")
        except Exception as e:
            log.error(f"Error in check_tool_change_state: {e}")
    '''


    def loadToolViaM61(self):
        t = self.getSelectedToolFromTable()
        if len(t) > 0:
            self.executeProgram(f'M61 Q{t[0]}')
            #emccanon.CHANGE_TOOL(2)
            self.w.tooloffsetview.repaint()
            cmd = linuxcnc.command()
            cmd.load_tool_table()

    def loadToolViaM6tn(self):
        t = self.getSelectedToolFromTable()
        if len(t) == 0:
            return
        # Make sure that the mode is set to MDI
        ACTION.CALL_MDI_WAIT( f"G90" )
        ACTION.CALL_MDI_WAIT( f"G53 G0 Z{self.c[AtcHalPin.SAFE_Z]}" )
        ACTION.CALL_MDI_WAIT( f"G53 G0 X[{self.c[AtcHalPin.X_MANUAL_CHANGE_POS]}] Y[{self.c[AtcHalPin.Y_MANUAL_CHANGE_POS]}]")

        #hal.set_p('qtdragon.manualtoolok', "1")
        info = _translate("HandlerClass",f"Load Tool #{t[0]} into the spindle. Then, press OK to continue, or Cancel to abort.")
        mess = {'NAME':'MESSAGE', 'ID':'_toolloaded_', 'MESSAGE':'LOAD TOOL', 'MORE':info, 'TYPE':'OKCANCEL'}
        ACTION.CALL_DIALOG(mess)


        # o<_auto_probe_tool> sub
        # #<tool_in_spindle> = #1
        # #<selected_tool> = #2
        # #<current_pocket> = #3
        # #<selected_pocket> = #4

        # Go to safe Z
        # Set the tool number
        #ACTION.CALL_MDI_WAIT( f"M61 Q{t[0]}" )




        #ACTION.CALL_MDI_WAIT( f"G10 L2 P0 Z%s" )

        #
        #
        #if len(t) > 0:
        #    # Set the current tool number for the dialog to display
        #    self.hal["tool_number"] = t[0]

        #    # Call the manual tool change subroutine with the selected tool number
        #

            # After the tool change is complete, update the tool table display
        #    self.w.tooloffsetview.repaint()
        #    cmd = linuxcnc.command()
        #    cmd.load_tool_table()

    def loadToolViaATC(self):
        t = self.getSelectedToolFromTable()
        if len(t) > 0:
            p = self.getToolPocketByIndex(t[0])
            self.executeProgram(f'o<_pickup_tool> call [{p}] [{t[0]}]')
            #self.w.tooloffsetview.repaint()
            #cmd = linuxcnc.command()
            #cmd.load_tool_table()


    def getSelectedToolFromTable(self):
        tool = self.w.tooloffsetview.get_checked_list()
        return tool

    def setXYPocketOne(self):
        s.poll()

        x_pos = round(s.position[0], 3)
        y_pos = round(s.position[1], 3)

        self.w.MAIN.PREFS_.putpref(ConfigElement.FIRST_POCKET_Y, str(x_pos), str, ConfigElement.ATC_SECTION)
        self.firstPocketXInput.setText(str(x_pos))
        self.w.MAIN.PREFS_.putpref(ConfigElement.FIRST_POCKET_X, str(y_pos), str, ConfigElement.ATC_SECTION)
        self.firstPocketYInput.setText(str(y_pos))

    def setZEngage(self):
        #stat = self.getCurrentStat()
        s.poll()
        z_pos = round(s.position[2], 3)
        self.w.MAIN.PREFS_.putpref(ConfigElement.Z_ENGAGE, str(z_pos), str, ConfigElement.ATC_SECTION)
        self.zEngageInput.setText(str(z_pos))

    def setZIREngage(self):
        #stat = self.getCurrentStat()
        s.poll()
        z_pos = round(s.position[2], 3)
        self.w.MAIN.PREFS_.putpref(ConfigElement.Z_IR_ENGAGE, str(z_pos), str, ConfigElement.ATC_SECTION)
        self.zEngageIRInput.setText(str(z_pos))

    def isMachineMetric(self) -> bool:
        return INFO.MACHINE_IS_METRIC

    def btn_systemtool_toggled(self, checked):
        """Handler for system tool button toggle event"""
        # Add your button toggle handling logic here
        pass
    ##############################
    # required class boiler code #
    ##############################
    def closing_cleanup__(self):
        #print('***CLOSE***', self.w.belt_1.isChecked())
        log.debug(f'Calling cleanup for shutdown..')
        self.c.exit() # Call Component's exist function per https://linuxcnc.org/docs/html/hal/halmodule.html
        if self.w.MAIN.PREFS_:
            pass

    def __getitem__(self, item):
        return getattr(self, item)
    def __setitem__(self, item, value):
        return setattr(self, item, value)

    def getToolPocketByIndex(self, index):
        return self.tooldb.get_tool_pocket(toolid=index)

    #def getCurrentStat(self):
    #    try:
    #        #s = linuxcnc.stat() # create a connection to the status channel
    #        self.s.poll() # get current values
    #        return self.s
    #    except linuxcnc.error as detail:
    #        log.error(f'Error: {detail}')
    #        sys.exit(1)

################################
# required handler boiler code #
################################

def get_handlers(halcomp,widgets,paths):
     return [HandlerClass(halcomp,widgets,paths)]
