#!/usr/bin/env python3

"""
Author: Donatas Olsevicius

This program is free software: you can redistribute it and/or modify it under the terms of the GNU General Public
License as published by the Free Software Foundation, either version 3 of the License, or (at your option) any later
version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied
warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program. If not, see
<https://www.gnu.org/licenses/>.
"""

# noinspection PyUnresolvedReferences
import emccanon
# noinspection PyUnresolvedReferences
import interpreter
# noinspection PyUnresolvedReferences
from interpreter import EmcPose
import hal
import linuxcnc
from qtvcp import logger
from .config import *
from .emc import *

throw_exceptions = 1

log = logger.getLogger(__name__)
log.setLevel(logger.WARNING)

__all__ = ['Rcatc']


class Rcatc:
    _DEBUG_LOG = 0x00000001
    _DEBUG_RELOAD_CONFIG = 0x00000010

    def __init__(self, runtime: interpreter):
        self.stat = linuxcnc.stat()

        self.runtime = runtime

        self.original_pos = [self.runtime.origin_offset_x, self.runtime.origin_offset_y]

        self.stat.poll()
        inifile = linuxcnc.ini(self.stat.ini_filename)

        self.config_path = inifile.find('RCATC', 'CONFIG_PATH') or ''
        if not self.config_path:
            raise RuntimeError('RCATC config file not defined')
        self.config = Config(self.config_path)
        self.config.read()

        debug_flags = int(inifile.find('RCATC', 'DEBUG')) or 0
        self.reload_config = bool(debug_flags & Rcatc._DEBUG_RELOAD_CONFIG)
        if debug_flags & Rcatc._DEBUG_LOG:
            log.setLevel(logger.DEBUG)


    def change_tool(self):
        log.debug('change_tool')

        if self.reload_config:
            self.config.read()

        if not self.ok_for_mdi():
            self.runtime.set_errormsg("cannot execute commands")
            yield Constants.ERROR
            return

        selected_pocket = self.runtime.selected_pocket
        if selected_pocket == -1:
            self.runtime.set_errormsg("pocket not prepared")
            yield Constants.ERROR
            return

        self.original_pos = [self.runtime.origin_offset_x, self.runtime.origin_offset_y]

        Canon.reset_coordinates()

        current_pocket = self.runtime.current_pocket
        manual_drop = current_pocket > self.config[ConfigNames.NUM_POCKETS]
        manual_pickup = selected_pocket > 0 and selected_pocket > self.config[ConfigNames.NUM_POCKETS]
        has_tool = bool(current_pocket)
        same_tool = selected_pocket == current_pocket

        if not same_tool:
            if has_tool and not manual_drop:
                yield from self.drop_tool()
            if manual_drop or manual_pickup:
                yield from self.manual_change(drop_only=not manual_pickup)
            if not manual_pickup and selected_pocket > 0:
                yield from self.pickup_tool()

        yield Canon.queuebuster()

        if self.runtime.current_tool:
            yield from self.probe_tool_length()

        # go back to the original XY position
        Canon.rapid_safe(Position(x=self.original_pos[0], y=self.original_pos[1], z=self.config[ConfigNames.SAFE_Z]))
        yield Canon.queuebuster()

        yield Constants.OK

    def pickup_tool(self):
        log.debug('pickup_tool')

        selected_pocket = self.runtime.selected_tool # pocket gets set to -1 when coming from manual_change(). no idea why
        current_pocket = self.runtime.current_pocket

        if current_pocket > 0:
            self.runtime.set_errormsg('Tool still in spindle - Aborting!')
            yield Constants.ERROR
            return

        if selected_pocket > self.config[ConfigNames.NUM_POCKETS]:
            self.runtime.set_errormsg('Pocket number (%d) higher than ATC pockets number (%d) - Aborting!' % (selected_pocket, self.config[ConfigNames.NUM_POCKETS]))
            yield Constants.ERROR
            return

        self.go_to_pocket(selected_pocket)
        self.dust_cover_open()
        yield Canon.queuebuster()

        Canon.rapid_safe(Position(z=self.config[ConfigNames.IR_Z_ENGAGE]))
        yield Canon.queuebuster()

        if self.config[ConfigNames.IR_ENABLED] and self.ir_tool_present():
            self.runtime.set_errormsg('Tool still in spindle - Aborting!')
            yield Constants.ERROR
            return

        yield from Canon.spindle_cw(self.config[ConfigNames.PICKUP_SPINDLE_SPEED], self.config[ConfigNames.SPINDLE_START_TIME], self.config[ConfigNames.SPINDLE_AT_SPEED_DIGITAL_IN])

        for _ in range(self.config[ConfigNames.PICKUP_PLUNGE_COUNT]):
            Canon.feed_z(Position(z=self.config[ConfigNames.ENGAGE_Z]), self.config[ConfigNames.PICKUP_RATE])
            yield Canon.queuebuster()
            Canon.feed_z(Position(z=self.config[ConfigNames.ENGAGE_Z] + self.config[ConfigNames.PICKUP_Z_RETREAT]), self.config[ConfigNames.PICKUP_RATE])
            yield Canon.queuebuster()

        yield from Canon.spindle_stop(self.config[ConfigNames.SPINDLE_STOP_TIME])

        if self.config[ConfigNames.IR_ENABLED] and not self.ir_tool_present():
            self.runtime.set_errormsg('No tool in spindle - Aborting!')
            yield Constants.ERROR
            return

        emccanon.CHANGE_TOOL_NUMBER(selected_pocket)
        self.go_to_pocket(selected_pocket) # go up to safe Z
        yield Canon.queuebuster()

        self.dust_cover_close()
        yield Canon.queuebuster()

    def drop_tool(self):
        log.debug('drop_tool')

        current_pocket = self.runtime.current_pocket
        if current_pocket < 1:
            self.runtime.set_errormsg('No tool in spindle - Aborting!')
            yield Constants.ERROR
            return

        if current_pocket > self.config[ConfigNames.NUM_POCKETS]:
            self.runtime.set_errormsg('Pocket number (%d) higher than ATC pockets number (%d) - Aborting!' % (current_pocket, self.config[ConfigNames.NUM_POCKETS]))
            yield Constants.ERROR
            return

        self.go_to_pocket(current_pocket)
        self.dust_cover_open()
        yield Canon.queuebuster()

        Canon.rapid_safe(Position(z=self.config[ConfigNames.IR_Z_ENGAGE]))

        if self.config[ConfigNames.IR_ENABLED] and not self.ir_tool_present():
            self.runtime.set_errormsg('No tool in spindle - Aborting!')
            yield Constants.ERROR
            return

        yield from Canon.spindle_ccw(self.config[ConfigNames.DROP_SPINDLE_SPEED], self.config[ConfigNames.SPINDLE_START_TIME], self.config[ConfigNames.SPINDLE_AT_SPEED_DIGITAL_IN])

        for _ in range(1): # should I plunge more than once?
            Canon.feed_z(Position(z=self.config[ConfigNames.ENGAGE_Z]), self.config[ConfigNames.DROP_RATE])
            yield Canon.queuebuster()
            Canon.feed_z(Position(z=self.config[ConfigNames.ENGAGE_Z] + self.config[ConfigNames.PICKUP_Z_RETREAT]), self.config[ConfigNames.DROP_RATE])
            yield Canon.queuebuster()

        yield from Canon.spindle_stop(self.config[ConfigNames.SPINDLE_STOP_TIME])

        if self.config[ConfigNames.IR_ENABLED] and self.ir_tool_present():
            self.runtime.set_errormsg('Tool still in spindle - Aborting!')
            yield Constants.ERROR
            return

        yield Canon.queuebuster()

        emccanon.CHANGE_TOOL_NUMBER(0)
        self.runtime.current_pocket = 0
        self.runtime.current_tool = 0

        yield Canon.queuebuster()

        self.go_to_pocket(current_pocket) # go up to safe Z
        yield Canon.queuebuster()

        self.dust_cover_close()
        yield Canon.queuebuster()

    def manual_change(self, drop_only: bool = False):
        log.debug('manual_change, drop_only=%s' % drop_only)

        original_selected_tool = selected_tool = self.runtime.selected_tool
        original_selected_pocket = selected_pocket = self.runtime.selected_pocket
        if selected_pocket == -1 and selected_tool != 0:
            (_, selected_pocket) = self.runtime.find_tool_pocket(selected_tool)
            original_selected_pocket = selected_pocket

        if drop_only:
            selected_tool = 0
            selected_pocket = 0
            self.runtime.selected_pocket = selected_pocket
            self.runtime.selected_tool = selected_tool
            self.runtime.set_tool_parameters()

        Canon.rapid_safe(Position(x=self.config[ConfigNames.MANUAL_CHANGE_POS_X], y=self.config[ConfigNames.MANUAL_CHANGE_POS_Y], z=self.config[ConfigNames.SAFE_Z]))
        yield Canon.queuebuster()

        try:
            hal.set_p('hal_manualtoolchange.number', str(selected_tool))
        except Exception as e:
            log.debug('EXCEPTION tool number set: ' + str(e))
            yield Constants.ERROR

        emccanon.CHANGE_TOOL(selected_pocket)
        yield Canon.queuebuster()

        emccanon.CHANGE_TOOL_NUMBER(selected_pocket)
        yield Canon.queuebuster()
        self.runtime.current_pocket = selected_pocket
        self.runtime.current_tool = selected_tool

        if drop_only:
            self.runtime.selected_pocket = original_selected_pocket
            self.runtime.selected_tool = original_selected_tool

        self.runtime.set_tool_parameters()

        yield Canon.queuebuster()

    def probe_tool_length(self):
        # G49
        emccanon.USE_TOOL_LENGTH_OFFSET(EmcPose())

        yield Canon.queuebuster()

        current_tool = self.runtime.current_tool
        auto_probe = hal.get_value('qtversaprobe.enable')
        log.debug('probe_tool_length, tool=%d, auto_probe=%s' % (current_tool, auto_probe))

        # self.runtime.execute('G49') # cancel tool offset
        if not auto_probe:
            # G43
            emccanon.USE_TOOL_LENGTH_OFFSET(self.runtime.tool_offset) # no measurement, use offset from the tool table
            return

        self.stat.poll()
        inifile = linuxcnc.ini(self.stat.ini_filename)

        versa_x = inifile.find('VERSA_TOOLSETTER', 'X') or False
        versa_y = inifile.find('VERSA_TOOLSETTER', 'Y') or False
        versa_z = inifile.find('VERSA_TOOLSETTER', 'Z') or False
        versa_maxprobe = inifile.find('VERSA_TOOLSETTER', 'MAXPROBE') or False

        versa_x = float(versa_x)
        versa_y = float(versa_y)
        versa_z = float(versa_z)
        versa_maxprobe = float(versa_maxprobe)

        versa_searchvel = hal.get_value('qtversaprobe.searchvel')
        versa_probevel = hal.get_value('qtversaprobe.probevel')
        versa_backoffdist = hal.get_value('qtversaprobe.backoffdist')
        versa_probeheight = hal.get_value('qtversaprobe.probeheight')
        versa_blockheight = hal.get_value('qtversaprobe.blockheight')

        # go to tool setter
        Canon.rapid_safe(Position(x=versa_x, y=versa_y, z=self.config[ConfigNames.SAFE_Z]))
        yield Canon.queuebuster()
        Canon.rapid_safe(Position(z=versa_z))
        yield Canon.queuebuster()

        try:
            # probe at search speed
            Canon.probe(versa_maxprobe, versa_searchvel)
            yield Canon.queuebuster()

            self.stat.poll()
            if not self.stat.probe_tripped:
                self.runtime.set_errormsg('Probing error: probe not tripped')
                yield Constants.ERROR

            backoff_pos = Position()
            backoff_pos.adjust(z=versa_backoffdist)

            Canon.rapid_safe(backoff_pos)
            yield Canon.queuebuster()

            # reprobe at probe speed
            Canon.probe(versa_backoffdist * 1.2, versa_probevel)
            yield Canon.queuebuster()

            self.stat.poll()
            if not self.stat.probe_tripped:
                self.runtime.set_errormsg('Probing error: probe not tripped')
                yield Constants.ERROR
        except Exception as e:
            log.debug(e)
            self.runtime.set_errormsg('Probing error: %s' % e)
            yield Constants.ERROR
            return

        # go back up
        Canon.rapid_safe(Position(z=versa_z))

        z_offset = self.stat.probed_position[2] - versa_probeheight + versa_blockheight
        log.debug('probed position: %s, z offset: %s' % (self.stat.probed_position, z_offset))

        yield from self.set_tool_z_offset(current_tool, z_offset)
        # yield RcatcCanon.queuebuster()

    def set_tool_z_offset(self, tool_number: int, z_offset: float, use_offset: bool = True):
        self.stat.poll()

        pose = EmcPose()
        pose.z = z_offset

        # current tool is added at zero index in the tool table
        tool = self.stat.tool_table[0]

        # G10 L1 Px Zx
        emccanon.SET_TOOL_TABLE_ENTRY(tool_number, tool_number, pose, tool.diameter, tool.frontangle, tool.backangle, tool.orientation)
        yield Canon.queuebuster()

        if use_offset:
            # G43
            emccanon.USE_TOOL_LENGTH_OFFSET(pose)
            self.runtime.tool_offset = pose
            yield Canon.queuebuster()

    def dust_cover_open(self):
        if not self.config[ConfigNames.COVER_ENABLED]:
            return

        hal.set_p(self.config[ConfigNames.COVER_HAL_PIN], '1')
        yield from Canon.dwell(self.config[ConfigNames.COVER_OPEN_TIME])

    def dust_cover_close(self):
        if not self.config[ConfigNames.COVER_ENABLED]:
            return

        hal.set_p(self.config[ConfigNames.COVER_HAL_PIN], '0')

    def ir_tool_present(self):
        return False

    def go_to_pocket(self, pocket: int):
        if self.config[ConfigNames.ALIGN_AXIS].lower() == 'x':
            x = self.config[ConfigNames.FIRST_POCKET_X] + (pocket - 1) * self.config[ConfigNames.POCKET_OFFSET]
            y = self.config[ConfigNames.FIRST_POCKET_Y]
        else:
            x = self.config[ConfigNames.FIRST_POCKET_X]
            y = self.config[ConfigNames.FIRST_POCKET_Y] + (pocket - 1) * self.config[ConfigNames.POCKET_OFFSET]

        Canon.rapid_safe(Position(x=x, y=y, z=self.config[ConfigNames.SAFE_Z]))

    def get_machine_position(self):
        self.stat.poll()
        position = self.stat.position
        return {'X': position[0], 'Y': position[1], 'Z': position[2]}

    def ok_for_mdi(self):
        self.stat.poll()

        return not self.stat.estop and self.stat.enabled and (self.stat.homed.count(1) == self.stat.joints) and (self.stat.interp_state == linuxcnc.INTERP_IDLE)

    def setup_signals(self):
        for sig in hal.get_info_signals():
            if sig['NAME'] == 'rcatc-tool-prepare-loopback':
                # already set up
                return

        log.debug('preparing signals')

        # disconnecting as I need to change hal_manualtoolchange.number when dropping the tool manually
        hal.disconnect('hal_manualtoolchange.number')
        hal.disconnect('iocontrol.0.tool-prep-number')

        # disconnect and recreate the loopback to ensure it exists
        hal.disconnect('iocontrol.0.tool-prepared')
        hal.disconnect('iocontrol.0.tool-prepare')

        hal.new_sig('rcatc-tool-prepare-loopback', hal.HAL_BIT)
        hal.connect('iocontrol.0.tool-prepared', 'rcatc-tool-prepare-loopback')
        hal.connect('iocontrol.0.tool-prepare', 'rcatc-tool-prepare-loopback')
