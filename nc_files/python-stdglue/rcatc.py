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
from enum import StrEnum

# noinspection PyUnresolvedReferences
import emccanon
# noinspection PyUnresolvedReferences
from interpreter import *
import hal
import linuxcnc
from qtvcp import logger
from inspect import currentframe, getframeinfo

throw_exceptions = 1

log = logger.getLogger(__name__)
log.setLevel(logger.DEBUG)


# noinspection PyUnresolvedReferences
class RcatcConstants:
    EXECUTE_FINISH = INTERP_EXECUTE_FINISH
    OK = INTERP_OK
    ERROR = INTERP_ERROR


class RcatcPosition:
    def __init__(self, x: float|None = None, y: float|None = None, z: float|None = None):
        self.in_x = x
        self.in_y = y
        self.in_z = z

        self.stat = linuxcnc.stat()

    def adjust(self, x: float|None = None, y: float|None = None, z: float|None = None):
        self.stat.poll()
        abs_position = self.stat.position
        if x:
            self.in_x = (self.in_x if self.in_x is not None else abs_position[0]) + x
        if y:
            self.in_y = (self.in_y if self.in_y is not None else abs_position[1]) + y
        if z:
            self.in_z = (self.in_z if self.in_z is not None else abs_position[2]) + z

    @property
    def x(self):
        self.stat.poll()
        abs_position = self.stat.position
        return (self.in_x if self.in_x is not None else abs_position[0]) - (abs_position[0] - self.curr_x)

    @property
    def y(self):
        self.stat.poll()
        abs_position = self.stat.position
        return (self.in_y if self.in_y is not None else abs_position[1]) - (abs_position[1] - self.curr_y)

    @property
    def z(self):
        self.stat.poll()
        abs_position = self.stat.position
        return (self.in_z if self.in_z is not None else abs_position[2]) - (abs_position[2] - self.curr_z)

    @property
    def curr_x(self):
        return emccanon.GET_EXTERNAL_POSITION_X()

    @property
    def curr_y(self):
        return emccanon.GET_EXTERNAL_POSITION_Y()

    @property
    def curr_z(self):
        return emccanon.GET_EXTERNAL_POSITION_Z()

    def __str__(self):
        return str([self.x, self.y, self.z])


class RcatcCanon:
    @staticmethod
    def reset_coordinates():
        log.debug('reset_coordinates')

        # emccanon.SET_MOTION_CONTROL_MODE(emccanon.CANON_EXACT_STOP)  # Use exact stop mode
        emccanon.STOP_CUTTER_RADIUS_COMPENSATION()  # Cutter comp off, otherwise G53 might go wrong
        emccanon.USE_TOOL_LENGTH_OFFSET(EmcPose())  # Cancel tool offset (not needed until the end)

    @staticmethod
    def feed_z(pos: RcatcPosition, feed: int):
        log.debug('F %d' % feed)
        emccanon.SET_FEED_RATE(feed)
        log.debug('G1 %s at F%d' % ([pos.curr_x, pos.curr_y, pos.z], feed))
        emccanon.STRAIGHT_FEED(2, pos.curr_x, pos.curr_y, pos.z, 0, 0, 0, 0, 0, 0)

    @staticmethod
    def rapid_safe(pos: RcatcPosition):
        log.debug('G0 %s' % [pos.curr_x, pos.curr_y, pos.z])
        emccanon.STRAIGHT_TRAVERSE(1, pos.curr_x, pos.curr_y, pos.z, 0, 0, 0, 0, 0, 0)
        log.debug('G0 %s' % [pos.x, pos.y, pos.z])
        emccanon.STRAIGHT_TRAVERSE(2, pos.x, pos.y, pos.z, 0, 0, 0, 0, 0, 0)

    @staticmethod
    def queuebuster():
        # I probably use this too often
        emccanon.WAIT(10, 1, 3, 0.01)
        return RcatcConstants.EXECUTE_FINISH

    @staticmethod
    def probe(z_distance: float, feed: int):
        pos = RcatcPosition()
        pos.adjust(z=-z_distance)

        log.debug('F %d' % feed)
        emccanon.SET_FEED_RATE(feed)
        log.debug('G38.2 %s' % [pos.x, pos.y, pos.z])
        emccanon.STRAIGHT_PROBE(1, pos.x, pos.y, pos.z, 0, 0, 0, 0, 0, 0, 229)


class RcatcConfig:
    def __init__(self):
        self.SAFE_Z = 0
        self.ENGAGE_Z = -146.5

        self.ALIGN_AXIS = 'Y'
        self.NUM_POCKETS = 2
        self.POCKET_OFFSET = 45
        self.FIRST_POCKET_X = 0.425
        self.FIRST_POCKET_Y = 73.44

        self.MANUAL_CHANGE_POS_X = 315
        self.MANUAL_CHANGE_POS_Y = 0

        self.PICKUP_PLUNGE_COUNT = 2
        self.PICKUP_Z_RETREAT = 25
        self.PICKUP_SPINDLE_SPEED = 1400
        self.PICKUP_RATE = 1800

        self.DROP_SPINDLE_SPEED = 1200
        self.DROP_RATE = 1500

        self.IR_ENABLED = False
        self.IR_HAL_PIN = ''
        self.IR_Z_ENGAGE = -90

        self.COVER_ENABLED = True
        self.COVER_HAL_PIN = 'flexi.output.AUX0'
        self.COVER_OPEN_TIME = 2

    def all(self):
        return {name: getattr(self, name) for name in vars(self) if not name.startswith('__')}

    def read(self):
        names = [name for name in vars(self) if not name.startswith('__')]

        stat = linuxcnc.stat()
        stat.poll()
        inifile = linuxcnc.ini(stat.ini_filename)

        for name in names:
            value: str = inifile.find('RCATC', name) or False
            # noinspection PySimplifyBooleanCheck
            if value != False:
                type_ = type(getattr(self, name))
                if type_ == bool:
                    setattr(self, name, value.lower() not in [0, 'false'])
                else:
                    setattr(self, name, type_(value))


class Rcatc:
    def __init__(self, runtime):
        self.config = RcatcConfig()
        self.config.read()

        self.stat = linuxcnc.stat()

        self.runtime = runtime

        self.original_pos = [self.runtime.origin_offset_x, self.runtime.origin_offset_y]

    def change_tool(self):
        log.debug('change_tool')

        if not self.ok_for_mdi():
            self.runtime.set_errormsg("cannot execute commands")
            yield RcatcConstants.ERROR
            return

        selected_pocket = self.runtime.selected_pocket
        if selected_pocket == -1:
            self.runtime.set_errormsg("pocket not prepared")
            yield RcatcConstants.ERROR
            return

        self.original_pos = [self.runtime.origin_offset_x, self.runtime.origin_offset_y]

        RcatcCanon.reset_coordinates()

        current_pocket = self.runtime.current_pocket
        manual_drop = current_pocket > self.config.NUM_POCKETS
        manual_pickup = selected_pocket > 0 and selected_pocket > self.config.NUM_POCKETS
        has_tool = bool(current_pocket)
        same_tool = selected_pocket == current_pocket

        if not same_tool:
            if has_tool and not manual_drop:
                for res in self.drop_tool():
                    yield res
            if manual_drop or manual_pickup:
                for res in self.manual_change(drop_only=not manual_pickup):
                    yield res
            if not manual_pickup and selected_pocket > 0:
                for res in self.pickup_tool():
                    yield res

        yield RcatcCanon.queuebuster()

        if self.runtime.current_tool:
            for res in self.probe_tool_length():
                yield res

        # go back to the original XY position
        RcatcCanon.rapid_safe(RcatcPosition(x=self.original_pos[0], y=self.original_pos[1], z=self.config.SAFE_Z))
        yield RcatcCanon.queuebuster()

        yield RcatcConstants.OK

    def pickup_tool(self):
        log.debug('pickup_tool')

        selected_pocket = self.runtime.selected_tool # pocket gets set to -1 when coming from manual_change(). no idea why
        current_pocket = self.runtime.current_pocket

        if current_pocket > 0:
            self.runtime.set_errormsg('Tool still in spindle - Aborting!')
            yield RcatcConstants.ERROR
            return

        if selected_pocket > self.config.NUM_POCKETS:
            self.runtime.set_errormsg('Pocket number (%d) higher than ATC pockets number (%d) - Aborting!' % (selected_pocket, self.config.NUM_POCKETS))
            yield RcatcConstants.ERROR
            return

        self.go_to_pocket(selected_pocket)
        self.dust_cover_open()
        yield RcatcCanon.queuebuster()

        # self.rapid_z(self.config.Z_IR_ENGAGE)
        RcatcCanon.rapid_safe(RcatcPosition(z=self.config.Z_IR_ENGAGE))
        yield RcatcCanon.queuebuster()

        if self.config.IR_ENABLED and self.ir_tool_present():
            self.runtime.set_errormsg('Tool still in spindle - Aborting!')
            yield RcatcConstants.ERROR
            return

        emccanon.SET_SPINDLE_SPEED(0, self.config.PICKUP_SPINDLE_SPEED)
        emccanon.START_SPINDLE_CLOCKWISE(0, 1)
        # wait 2secs for digital-input-00 to go high (linked to spindle.0.at-speed)
        # could as well dwell for 2s to make it simpler
        emccanon.WAIT(0, 1, 3, 2)
        yield RcatcCanon.queuebuster()

        for _ in range(self.config.PICKUP_PLUNGE_COUNT):
            RcatcCanon.feed_z(RcatcPosition(z=self.config.ENGAGE_Z), self.config.PICKUP_RATE)
            yield RcatcCanon.queuebuster()
            RcatcCanon.feed_z(RcatcPosition(z=self.config.ENGAGE_Z + self.config.PICKUP_Z_RETREAT), self.config.PICKUP_RATE)
            yield RcatcCanon.queuebuster()

        emccanon.STOP_SPINDLE_TURNING(0)
        RcatcCanon.rapid_safe(RcatcPosition(z=self.config.Z_IR_ENGAGE))
        emccanon.DWELL(1) # dwell to ensure the spindle is stopped
        yield RcatcCanon.queuebuster()

        if self.config.IR_ENABLED and not self.ir_tool_present():
            self.runtime.set_errormsg('No tool in spindle - Aborting!')
            yield RcatcConstants.ERROR
            return

        emccanon.CHANGE_TOOL_NUMBER(selected_pocket)
        self.go_to_pocket(selected_pocket) # go up to safe Z
        yield RcatcCanon.queuebuster()

        self.dust_cover_close()
        yield RcatcCanon.queuebuster()

    def drop_tool(self):
        log.debug('drop_tool')

        current_pocket = self.runtime.current_pocket
        if current_pocket < 1:
            self.runtime.set_errormsg('No tool in spindle - Aborting!')
            yield RcatcConstants.ERROR
            return

        if current_pocket > self.config.NUM_POCKETS:
            self.runtime.set_errormsg('Pocket number (%d) higher than ATC pockets number (%d) - Aborting!' % (current_pocket, self.config.NUM_POCKETS))
            yield RcatcConstants.ERROR
            return

        self.go_to_pocket(current_pocket)
        self.dust_cover_open()
        yield RcatcCanon.queuebuster()

        RcatcCanon.rapid_safe(RcatcPosition(z=self.config.Z_IR_ENGAGE))

        if self.config.IR_ENABLED and not self.ir_tool_present():
            self.runtime.set_errormsg('No tool in spindle - Aborting!')
            yield RcatcConstants.ERROR
            return

        emccanon.SET_SPINDLE_SPEED(0, self.config.DROP_SPINDLE_SPEED)
        emccanon.START_SPINDLE_COUNTERCLOCKWISE(0, 1)
        # wait 2secs for digital-input-00 to go high (linked to spindle.0.at-speed)
        # could as well dwell for 2s to make it simpler
        emccanon.WAIT(0, 1, 3, 2)
        yield RcatcCanon.queuebuster()

        for _ in range(1): # should I plunge more than once?
            RcatcCanon.feed_z(RcatcPosition(z=self.config.ENGAGE_Z), self.config.DROP_RATE)
            yield RcatcCanon.queuebuster()
            RcatcCanon.feed_z(RcatcPosition(z=self.config.ENGAGE_Z + self.config.PICKUP_Z_RETREAT), self.config.DROP_RATE)
            yield RcatcCanon.queuebuster()

        emccanon.STOP_SPINDLE_TURNING(0)
        # self.rapid_z(self.config.Z_IR_ENGAGE)
        RcatcCanon.rapid_safe(RcatcPosition(z=self.config.Z_IR_ENGAGE))
        emccanon.DWELL(1) # dwell to ensure the spindle is stopped
        yield RcatcCanon.queuebuster()

        if self.config.IR_ENABLED and self.ir_tool_present():
            self.runtime.set_errormsg('Tool still in spindle - Aborting!')
            yield RcatcConstants.ERROR
            return

        yield RcatcCanon.queuebuster()

        emccanon.CHANGE_TOOL_NUMBER(0)
        self.runtime.current_pocket = 0
        self.runtime.current_tool = 0

        yield RcatcCanon.queuebuster()

        self.go_to_pocket(current_pocket) # go up to safe Z
        yield RcatcCanon.queuebuster()

        self.dust_cover_close()
        yield RcatcCanon.queuebuster()

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

        RcatcCanon.rapid_safe(RcatcPosition(x=self.config.MANUAL_CHANGE_POS_X, y=self.config.MANUAL_CHANGE_POS_Y, z=self.config.SAFE_Z))
        yield RcatcCanon.queuebuster()

        try:
            hal.set_p('hal_manualtoolchange.number', str(selected_tool))
        except Exception as e:
            log.debug('EXCEPTION tool number set: ' + str(e))
            yield RcatcConstants.ERROR

        emccanon.CHANGE_TOOL(selected_pocket)
        yield RcatcCanon.queuebuster()

        emccanon.CHANGE_TOOL_NUMBER(selected_pocket)
        yield RcatcCanon.queuebuster()
        self.runtime.current_pocket = selected_pocket
        self.runtime.current_tool = selected_tool

        if drop_only:
            self.runtime.selected_pocket = original_selected_pocket
            self.runtime.selected_tool = original_selected_tool

        self.runtime.set_tool_parameters()

        yield RcatcCanon.queuebuster()

    def probe_tool_length(self):
        # G49
        emccanon.USE_TOOL_LENGTH_OFFSET(EmcPose())

        yield RcatcCanon.queuebuster()

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
        RcatcCanon.rapid_safe(RcatcPosition(x=versa_x, y=versa_y, z=self.config.SAFE_Z))
        yield RcatcCanon.queuebuster()
        RcatcCanon.rapid_safe(RcatcPosition(z=versa_z))
        yield RcatcCanon.queuebuster()

        try:
            # probe at search speed
            RcatcCanon.probe(versa_maxprobe, versa_searchvel)
            yield RcatcCanon.queuebuster()

            self.stat.poll()
            if not self.stat.probe_tripped:
                yield self.handle_probe_error()

            backoff_pos = RcatcPosition()
            backoff_pos.adjust(z=versa_backoffdist)

            RcatcCanon.rapid_safe(backoff_pos)
            yield RcatcCanon.queuebuster()

            # reprobe at probe speed
            RcatcCanon.probe(versa_backoffdist * 1.2, versa_probevel)
            yield RcatcCanon.queuebuster()

            self.stat.poll()
            if not self.stat.probe_tripped:
                yield self.handle_probe_error()
        except Exception as e:
            log.debug(e)
            yield self.handle_probe_error()
            return

        # go back up
        RcatcCanon.rapid_safe(RcatcPosition(z=versa_z))

        z_offset = self.stat.probed_position[2] - versa_probeheight + versa_blockheight
        log.debug('probed position: %s, z offset: %s' % (self.stat.probed_position, z_offset))

        for res in self.set_tool_z_offset(current_tool, z_offset):
            yield res
        # yield RcatcCanon.queuebuster()

    def set_tool_z_offset(self, tool_number: int, z_offset: float, use_offset: bool = True):
        self.stat.poll()

        pose = EmcPose()
        pose.z = z_offset

        # current tool is added at zero index in the tool table
        tool = self.stat.tool_table[0]

        # G10 L1 Px Zx
        emccanon.SET_TOOL_TABLE_ENTRY(tool_number, tool_number, pose, tool.diameter, tool.frontangle, tool.backangle, tool.orientation)
        yield RcatcCanon.queuebuster()

        if use_offset:
            # G43
            emccanon.USE_TOOL_LENGTH_OFFSET(pose)
            self.runtime.tool_offset = pose
            yield RcatcCanon.queuebuster()


    def handle_probe_error(self):
        # self.runtime.execute("G90")
        self.runtime.set_errormsg("tool_probe_m6 remap error:")
        return RcatcConstants.ERROR

    def dust_cover_open(self):
        if not self.config.COVER_ENABLED:
            return

        hal.set_p(self.config.COVER_HAL_PIN, '1')
        emccanon.DWELL(self.config.COVER_OPEN_TIME)

    def dust_cover_close(self):
        if not self.config.COVER_ENABLED:
            return

        hal.set_p(self.config.COVER_HAL_PIN, '0')

    def ir_tool_present(self):
        return False

    def go_to_pocket(self, pocket: int):
        if self.config.ALIGN_AXIS == 'X':
            x = self.config.FIRST_POCKET_X + (pocket - 1) * self.config.POCKET_OFFSET
            y = self.config.FIRST_POCKET_Y
        else:
            x = self.config.FIRST_POCKET_X
            y = self.config.FIRST_POCKET_Y + (pocket - 1) * self.config.POCKET_OFFSET

        RcatcCanon.rapid_safe(RcatcPosition(x=x, y=y, z=self.config.SAFE_Z))

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



# REMAP=M6 modalgroup=6 prolog=change_prolog python=rcatc_tool_change epilog=change_epilog
def rcatc_tool_change(self):
    if self.task == 0:  # ignore the preview interpreter
        return RcatcConstants.OK

    config = RcatcConfig()
    config.read()

    atc = Rcatc(self)
    atc.setup_signals()

    try:
        for result in atc.change_tool():
            yield result
    except Exception as e:
        self.runtime.set_errormsg(str(e))
        log.debug(e)
        return RcatcConstants.ERROR

    return RcatcConstants.OK



def build_hal(self):
    #log.debug(getframeinfo(currentframe()).lineno)

    # emccanon.SET_G5X_OFFSET(int(self.params[5220]), 0, 0, -30, 0,0,0,0,0,0)
    # print(self.tool_offset)

    # stat = linuxcnc.stat()
    # stat.poll()
    # print(dir(stat.tool_table[6]))
    # print(stat.tool_table[6])
    # print(stat.tool_table[6].zoffset)

    comp = hal.component('rcatc')
    log.debug('build_hal')

    comp.newpin("use-atc", hal.HAL_BIT, hal.HAL_IN)
    comp.newpin("use-atc-asdf", hal.HAL_BIT, hal.HAL_IN)
    hal.set_p('rcatc.use-atc', 'True')

    comp.ready()
