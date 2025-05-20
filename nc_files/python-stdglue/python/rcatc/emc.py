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
from interpreter import *
# noinspection PyUnresolvedReferences
import interpreter
import linuxcnc
from qtvcp import logger

throw_exceptions = 1

log = logger.getLogger(__name__)
log.setLevel(logger.WARNING)


class Env:
    runtime: Interp

    @staticmethod
    def set_runtime(runtime: Interp):
        Env.runtime = runtime

    @staticmethod
    def initialized():
        return isinstance(Env.runtime, Interp)


# noinspection PyUnresolvedReferences
class Constants:
    EXECUTE_FINISH = INTERP_EXECUTE_FINISH
    OK = INTERP_OK
    ERROR = INTERP_ERROR


class Position:
    def __init__(self, x: float|None = None, y: float|None = None, z: float|None = None):
        if not Env.initialized():
            raise RuntimeError('Env not initialized')

        self._in_x = x
        self._in_y = y
        self._in_z = z

        self._out_x = None
        self._out_y = None
        self._out_z = None

        self.stat = linuxcnc.stat()

    def adjust(self, x: float|None = None, y: float|None = None, z: float|None = None):
        self.stat.poll()
        abs_position = self.stat.position
        if x:
            self._in_x = (self._in_x if self._in_x is not None else abs_position[0]) + x
        if y:
            self._in_y = (self._in_y if self._in_y is not None else abs_position[1]) + y
        if z:
            self._in_z = (self._in_z if self._in_z is not None else abs_position[2]) + z

    def _recalculate(self):
        self.stat.poll()
        abs_position = self.stat.position
        self._out_x = (self._in_x if self._in_x is not None else abs_position[0]) - (abs_position[0] - self.wcs_x)
        self._out_y = (self._in_y if self._in_y is not None else abs_position[1]) - (abs_position[1] - self.wcs_y)
        self._out_z = (self._in_z if self._in_z is not None else abs_position[2]) - (abs_position[2] - self.wcs_z)

    @property
    def abs_x(self):
        self._recalculate()
        return self._out_x

    @property
    def abs_y(self):
        self._recalculate()
        return self._out_y

    @property
    def abs_z(self):
        self._recalculate()
        return self._out_z

    @property
    def wcs_x(self):
        return emccanon.GET_EXTERNAL_POSITION_X()

    @property
    def wcs_y(self):
        return emccanon.GET_EXTERNAL_POSITION_Y()

    @property
    def wcs_z(self):
        return emccanon.GET_EXTERNAL_POSITION_Z()

    def __str__(self):
        return str([self.abs_x, self.abs_y, self.abs_z])


class Canon:
    _SPINDLE_DIR_CW = 1
    _SPINDLE_DIR_CCW = 2

    @staticmethod
    def reset_coordinates():
        log.debug('reset_coordinates')

        # emccanon.SET_MOTION_CONTROL_MODE(emccanon.CANON_EXACT_STOP)  # Use exact stop mode
        emccanon.STOP_CUTTER_RADIUS_COMPENSATION()  # Cutter comp off, otherwise G53 might go wrong
        emccanon.USE_TOOL_LENGTH_OFFSET(EmcPose())  # Cancel tool offset (not needed until the end)

    @staticmethod
    def feed_z(pos: Position, feed: int):
        log.debug('F %d' % feed)
        emccanon.SET_FEED_RATE(feed)
        log.debug('G1 %s at F%d' % ([pos.wcs_x, pos.wcs_y, pos.abs_z], feed))
        emccanon.STRAIGHT_FEED(2, pos.wcs_x, pos.wcs_y, pos.abs_z, 0, 0, 0, 0, 0, 0)

    @staticmethod
    def rapid_safe(pos: Position):
        log.debug('G0 %s' % [pos.wcs_x, pos.wcs_y, pos.abs_z])
        emccanon.STRAIGHT_TRAVERSE(1, pos.wcs_x, pos.wcs_y, pos.abs_z, 0, 0, 0, 0, 0, 0)
        log.debug('G0 %s' % [pos.abs_x, pos.abs_y, pos.abs_z])
        emccanon.STRAIGHT_TRAVERSE(2, pos.abs_x, pos.abs_y, pos.abs_z, 0, 0, 0, 0, 0, 0)

    @staticmethod
    def queuebuster():
        # I probably use this too often
        emccanon.WAIT(10, 1, 3, 0.01)
        return Constants.EXECUTE_FINISH

    @staticmethod
    def probe(z_distance: float, feed: int):
        pos = Position()
        pos.adjust(z=-z_distance)

        log.debug('F %d' % feed)
        emccanon.SET_FEED_RATE(feed)
        log.debug('G38.2 %s' % [pos.abs_x, pos.abs_y, pos.abs_z])
        emccanon.STRAIGHT_PROBE(1, pos.abs_x, pos.abs_y, pos.abs_z, 0, 0, 0, 0, 0, 0, 229)

    @staticmethod
    def spindle_cw(rpm: int, wait: int, at_speed_pin: int):
        yield from Canon._spindle_start(Canon._SPINDLE_DIR_CW, rpm, wait, at_speed_pin)

    @staticmethod
    def spindle_ccw(rpm: int, wait: int, at_speed_pin: int):
        yield from Canon._spindle_start(Canon._SPINDLE_DIR_CCW, rpm, wait, at_speed_pin)

    @staticmethod
    def _spindle_start(direction: int, rpm: int, wait: int, at_speed_pin: int):
        emccanon.SET_SPINDLE_SPEED(0, rpm)

        if direction == Canon._SPINDLE_DIR_CW:
            emccanon.START_SPINDLE_CLOCKWISE(0, 1)
        elif direction == Canon._SPINDLE_DIR_CCW:
            emccanon.START_SPINDLE_COUNTERCLOCKWISE(0, 1)
        else:
            yield Constants.ERROR

        yield Canon.queuebuster()

        if at_speed_pin >= 0:
            # wait 2secs for digital-input-00 to go high (linked to spindle.0.at-speed)
            emccanon.WAIT(at_speed_pin, 1, 3, 2)
            yield Canon.queuebuster()

        yield from Canon.dwell(wait)

    @staticmethod
    def spindle_stop(wait: int):
        emccanon.STOP_SPINDLE_TURNING(0)
        yield Canon.queuebuster()
        yield from Canon.dwell(wait)

    @staticmethod
    def dwell(time: int):
        if time:
            emccanon.DWELL(time)
        yield Canon.queuebuster()
