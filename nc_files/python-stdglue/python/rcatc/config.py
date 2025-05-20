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

import json
import os.path
from enum import StrEnum
from qtvcp import logger

throw_exceptions = 1

log = logger.getLogger(__name__)
log.setLevel(logger.WARNING)


class ConfigNames(StrEnum):
    SAFE_Z = 'safe_z'
    ENGAGE_Z = 'engage_z'

    ALIGN_AXIS = 'align_axis'
    NUM_POCKETS = 'num_pockets'
    POCKET_OFFSET = 'pocket_offset'
    FIRST_POCKET_X = 'first_pocket_x'
    FIRST_POCKET_Y = 'first_pocket_y'

    MANUAL_CHANGE_POS_X = 'manual_change_pos_x'
    MANUAL_CHANGE_POS_Y = 'manual_change_pos_y'

    PICKUP_PLUNGE_COUNT = 'pickup_plunge_count'
    PICKUP_Z_RETREAT = 'pickup_z_retreat'
    PICKUP_SPINDLE_SPEED = 'pickup_spindle_speed'
    PICKUP_RATE = 'pickup_rate'

    DROP_SPINDLE_SPEED = 'drop_spindle_speed'
    DROP_RATE = 'drop_rate'

    # -1 to disable, 0 in case of net spindle-at-speed motion.digital-in-00
    SPINDLE_AT_SPEED_DIGITAL_IN = 'spindle_at_speed_digital_in'
    SPINDLE_START_TIME = 'spindle_start_time'
    SPINDLE_STOP_TIME = 'spindle_stop_time'

    IR_ENABLED = 'ir_enabled'
    IR_HAL_PIN = 'ir_hal_pin'
    IR_Z_ENGAGE = 'ir_z_engage'

    COVER_ENABLED = 'cover_enabled'
    COVER_HAL_PIN = 'cover_hal_pin'
    COVER_OPEN_TIME = 'cover_open_time'


class Config:
    def __init__(self, path: str):
        self._path = os.path.expanduser(path)
        if not os.path.exists(self._path):
            raise RuntimeError('RCATC config file not found: "%s"' % self._path)

        self._data = {}

        self.read()

    def __getitem__(self, item):
        if not item in ConfigNames:
            raise KeyError('Config parameter %s does not exist' % item)

        if not item in self._data:
            raise KeyError('Config parameter %s not configured' % item)

        return self._data[item]

    def all(self):
        return self._data

    def read(self):
        with open(self._path) as fp:
            self._data = json.load(fp)
