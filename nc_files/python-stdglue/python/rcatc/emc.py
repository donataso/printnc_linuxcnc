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

from logging import Logger
import math
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
    def set_logger(log_: Logger):
        # ugly, but I'm not willing to fix this right now
        global log
        log = log_

    @staticmethod
    def initialized():
        return isinstance(Env.runtime, Interp)


# noinspection PyUnresolvedReferences
class Constants:
    EXECUTE_FINISH = INTERP_EXECUTE_FINISH
    OK = INTERP_OK
    ERROR = INTERP_ERROR


class Position:
    def __init__(self, x: float|None = None, y: float|None = None, z: float|None = None, a: float|None = None, b: float|None = None, c: float|None = None):
        if not Env.initialized():
            raise RuntimeError('Env not initialized')

        self.stat = linuxcnc.stat()
        self.stat.poll()
        abs_position = self.stat.position

        self._in_x = x if x is not None else abs_position[0]
        self._in_y = y if y is not None else abs_position[1]
        self._in_z = z if z is not None else abs_position[2]
        self._in_a = a if a is not None else abs_position[3]
        self._in_b = c if b is not None else abs_position[4]
        self._in_c = a if c is not None else abs_position[5]

        self._out_x = None
        self._out_y = None
        self._out_z = None
        self._out_a = None
        self._out_b = None
        self._out_c = None

    def copy(self):
        return Position(self._in_x, self._in_y, self._in_z, self._in_a, self._in_b, self._in_c)

    def set(self, x: float|None = None, y: float|None = None, z: float|None = None, a: float|None = None, b: float|None = None, c: float|None = None):
        self.stat.poll()

        if x:
            self._in_x = x
        if y:
            self._in_y = y
        if z:
            self._in_z = z
        if a:
            self._in_a = a
        if b:
            self._in_b = b
        if c:
            self._in_c = c

    def adjust(self, x: float|None = None, y: float|None = None, z: float|None = None, a: float|None = None, b: float|None = None, c: float|None = None):
        self.stat.poll()

        if x:
            self._in_x += x
        if y:
            self._in_y += y
        if z:
            self._in_z += z
        if a:
            self._in_a += a
        if b:
            self._in_b += b
        if c:
            self._in_c += c

    def _rotate(self, x: float, y: float, theta: float):
        t = math.radians(theta)
        return x * math.cos(t) - y * math.sin(t), x * math.sin(t) + y * math.cos(t)

    def _unoffset_and_unrotate(self):
        # todo: maybe not ignore u,v,w axis? :)
        # params names for them are here: https://github.com/LinuxCNC/linuxcnc/blob/1b88677955de70c657dde3961b33ffb87a5dd5d0/src/emc/rs274ngc/interp_find.cc#L467

        s = Env.runtime
        self.stat.poll()
        abs_position = self.stat.position

        x = self._in_x if self._in_x is not None else abs_position[0]
        y = self._in_y if self._in_y is not None else abs_position[1]
        z = self._in_z if self._in_z is not None else abs_position[2]
        a = self._in_a if self._in_a is not None else abs_position[3]
        b = self._in_b if self._in_b is not None else abs_position[4]
        c = self._in_c if self._in_c is not None else abs_position[5]

        # https://github.com/LinuxCNC/linuxcnc/blob/master/src/emc/task/emccanon.cc#L216
        # static CANON_POSITION unoffset_and_unrotate_pos(const CANON_POSITION& pos) {
        x -= s.tool_offset.tran.x
        y -= s.tool_offset.tran.y
        z -= s.tool_offset.tran.z
        a -= s.tool_offset.a
        b -= s.tool_offset.b
        c -= s.tool_offset.c

        x -= s.origin_offset_x
        y -= s.origin_offset_y
        z -= s.origin_offset_z
        a -= s.AA_origin_offset
        b -= s.BB_origin_offset
        c -= s.CC_origin_offset

        (x, y) = self._rotate(x, y, -s.rotation_xy)

        x -= s.axis_offset_x
        y -= s.axis_offset_y
        z -= s.axis_offset_z
        a -= s.AA_axis_offset
        b -= s.BB_axis_offset
        c -= s.CC_axis_offset

        self._out_x = x
        self._out_y = y
        self._out_z = z
        self._out_a = a
        self._out_b = b
        self._out_c = c

    @property
    def x(self):
        self._unoffset_and_unrotate()
        return self._out_x

    @property
    def y(self):
        self._unoffset_and_unrotate()
        return self._out_y

    @property
    def z(self):
        self._unoffset_and_unrotate()
        return self._out_z

    @property
    def a(self):
        self._unoffset_and_unrotate()
        return self._out_a

    @property
    def b(self):
        self._unoffset_and_unrotate()
        return self._out_b

    @property
    def c(self):
        self._unoffset_and_unrotate()
        return self._out_c

    @property
    def curr_x(self):
        return emccanon.GET_EXTERNAL_POSITION_X()

    @property
    def curr_y(self):
        return emccanon.GET_EXTERNAL_POSITION_Y()

    @property
    def curr_z(self):
        return emccanon.GET_EXTERNAL_POSITION_Z()

    @property
    def curr_a(self):
        return emccanon.GET_EXTERNAL_POSITION_A()

    @property
    def curr_b(self):
        return emccanon.GET_EXTERNAL_POSITION_B()

    @property
    def curr_c(self):
        return emccanon.GET_EXTERNAL_POSITION_C()

    def __str__(self):
        return str([self.x, self.y, self.z])


class Canon:
    _SPINDLE_DIR_CW = 1
    _SPINDLE_DIR_CCW = 2

    @staticmethod
    def feed_z(pos: Position, feed: int):
        log.debug('F %d' % feed)
        emccanon.SET_FEED_RATE(feed)
        log.debug('G1 %s at F%d' % ([pos.curr_x, pos.curr_y, pos.z], feed))
        emccanon.STRAIGHT_FEED(2, pos.curr_x, pos.curr_y, pos.z, pos.curr_a, pos.curr_b, pos.curr_c, 0, 0, 0)

    @staticmethod
    def rapid_safe(pos: Position):
        log.debug('G0 %s' % [pos.curr_x, pos.curr_y, pos.z])
        emccanon.STRAIGHT_TRAVERSE(1, pos.curr_x, pos.curr_y, pos.z, pos.curr_a, pos.curr_b, pos.curr_c, 0, 0, 0)
        log.debug('G0 %s' % [pos.x, pos.y, pos.z])
        emccanon.STRAIGHT_TRAVERSE(2, pos.x, pos.y, pos.z, pos.a, pos.b, pos.c, 0, 0, 0)

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
        log.debug('G38.2 %s' % [pos.x, pos.y, pos.z])
        emccanon.STRAIGHT_PROBE(1, pos.x, pos.y, pos.z, pos.curr_a, pos.curr_b, pos.curr_c, 0, 0, 0, 229)

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
